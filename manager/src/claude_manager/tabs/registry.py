"""Registry reader for kitty terminals running Claude/Codex.

Reads /tmp/feishu-bridge/registry.json (written by existing kitty hooks)
and exposes a typed view of currently alive terminals.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


_SOCKET_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")


def socket_to_label(socket: str) -> str:
    """Return a short, file-safe label for a kitty socket."""
    value = (socket or "").strip()
    if value.startswith("unix:"):
        value = value[5:]
    if value.startswith("@"):
        value = value[1:]
    value = _SOCKET_LABEL_RE.sub("_", value).strip("_")
    return value or "kitty"


def build_terminal_id(window_id: str, socket: str) -> str:
    """Build a stable terminal id from kitty socket + window id."""
    wid = str(window_id or "").strip()
    if not wid:
        return ""
    label = socket_to_label(socket)
    return f"{wid}@{label}" if label else wid


@dataclass(frozen=True)
class TerminalInfo:
    """Read-only snapshot of a kitty terminal running an AI agent."""

    window_id: str
    socket: str
    tab_title: str
    cwd: str
    status: str          # "working" / "waiting" / "completed" / "idle"
    agent_kind: str      # "claude" / "codex"
    last_activity: float
    registered_at: float
    terminal_id: str = ""

    def __post_init__(self) -> None:
        if not self.terminal_id:
            object.__setattr__(
                self,
                "terminal_id",
                build_terminal_id(self.window_id, self.socket),
            )

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    @property
    def project_name(self) -> str:
        return Path(self.cwd).name or self.cwd

    @property
    def socket_label(self) -> str:
        return socket_to_label(self.socket)


REGISTRY_PATH = Path("/tmp/feishu-bridge/registry.json")


def _safe_float(value) -> float:
    """Best-effort float conversion; returns 0.0 for any unparseable value."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_registry_entry(entry_key: str, entry: dict) -> tuple[str, dict] | None:
    """Convert a registry entry to the canonical terminal-id keyed form."""
    if not isinstance(entry, dict):
        return None

    window_id = str(entry.get("window_id") or entry_key or "").strip()
    socket = str(entry.get("kitty_socket") or "").strip()
    if not window_id or not socket:
        return None

    terminal_id = str(entry.get("terminal_id") or "").strip() or build_terminal_id(window_id, socket)
    normalized = dict(entry)
    normalized["window_id"] = window_id
    normalized["kitty_socket"] = socket
    normalized["terminal_id"] = terminal_id
    normalized["socket_label"] = socket_to_label(socket)
    return terminal_id, normalized


def _pick_newer_entry(existing: dict, candidate: dict) -> dict:
    """Resolve collisions while migrating legacy registry keys."""
    existing_score = (_safe_float(existing.get("last_activity")), _safe_float(existing.get("registered_at")))
    candidate_score = (_safe_float(candidate.get("last_activity")), _safe_float(candidate.get("registered_at")))
    return candidate if candidate_score >= existing_score else existing


def load_registry() -> dict[str, dict]:
    """Read normalized registry dict keyed by terminal_id.

    Returns empty dict if the file is missing, corrupt, or not a JSON object.
    Never raises.
    """
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("failed to read %s: %s", REGISTRY_PATH, e)
        return {}
    if not isinstance(data, dict):
        logger.warning("%s is not a JSON object, ignoring", REGISTRY_PATH)
        return {}

    cleaned: dict[str, dict] = {}
    filtered_out = 0
    for entry_key, entry in data.items():
        normalized = _normalize_registry_entry(str(entry_key), entry)
        if not normalized:
            filtered_out += 1
            continue
        terminal_id, normalized_entry = normalized
        if terminal_id in cleaned:
            cleaned[terminal_id] = _pick_newer_entry(cleaned[terminal_id], normalized_entry)
        else:
            cleaned[terminal_id] = normalized_entry

    if filtered_out:
        logger.warning(
            "%s contained %d invalid entries, filtered out",
            REGISTRY_PATH,
            filtered_out,
        )
    return cleaned


KITTEN_LS_TIMEOUT = 5.0


def _get_alive_windows(socket: str) -> dict[str, dict]:
    """Query `kitten @ ls` for a single socket and return live windows.

    Returns dict mapping window_id (str) -> {"tab_title": str, "cwd": str}.
    On any failure (nonzero exit, timeout, missing kitten, malformed JSON)
    returns an empty dict — never raises.
    """
    try:
        result = subprocess.run(
            ["kitten", "@", "--to", socket, "ls"],
            capture_output=True,
            text=True,
            timeout=KITTEN_LS_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("kitten @ ls failed for socket %s: %s", socket, e)
        return {}

    if result.returncode != 0:
        logger.debug(
            "kitten @ ls nonzero rc=%d for %s: %s",
            result.returncode, socket, result.stderr.strip(),
        )
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("kitten @ ls returned non-JSON for %s", socket)
        return {}

    alive: dict[str, dict] = {}
    for os_window in data:
        for tab in os_window.get("tabs", []):
            tab_title = tab.get("title", "")
            for win in tab.get("windows", []):
                wid = str(win.get("id", ""))
                if not wid:
                    continue
                alive[wid] = {
                    "tab_title": tab_title,
                    "cwd": win.get("cwd", ""),
                }
    return alive


def list_alive_terminals() -> list[TerminalInfo]:
    """Read registry and return currently alive TerminalInfo, sorted by recency.

    Workflow:
    1. Load raw registry.
    2. Group entries by socket.
    3. For each socket, call `_get_alive_windows` once to get live window ids.
    4. Filter out entries whose window_id is not in the live set.
    5. Use live tab_title when available; fall back to registry value.
    6. Sort by last_activity descending (most recent first).
    """
    raw = load_registry()
    if not raw:
        return []

    by_socket: dict[str, list[dict]] = {}
    for entry in raw.values():
        socket = entry.get("kitty_socket", "")
        if not socket:
            continue
        by_socket.setdefault(socket, []).append(entry)

    results: list[TerminalInfo] = []
    for socket, entries in by_socket.items():
        alive = _get_alive_windows(socket)
        for entry in entries:
            wid = str(entry.get("window_id", ""))
            if wid not in alive:
                continue
            live_tab_title = alive[wid].get("tab_title") or entry.get("tab_title", "")
            results.append(
                TerminalInfo(
                    window_id=wid,
                    socket=socket,
                    tab_title=live_tab_title,
                    cwd=entry.get("cwd", ""),
                    status=entry.get("status", "idle"),
                    agent_kind=entry.get("agent_kind", "claude"),
                    last_activity=_safe_float(entry.get("last_activity", 0)),
                    registered_at=_safe_float(entry.get("registered_at", 0)),
                    terminal_id=str(entry.get("terminal_id") or build_terminal_id(wid, socket)),
                )
            )

    results.sort(key=lambda t: t.last_activity, reverse=True)
    return results
