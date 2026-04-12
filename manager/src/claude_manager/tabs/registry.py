"""Registry reader for kitty terminals running Claude/Codex.

Reads /tmp/feishu-bridge/registry.json (written by existing kitty hooks)
and exposes a typed view of currently alive terminals.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


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

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    @property
    def project_name(self) -> str:
        return Path(self.cwd).name or self.cwd


REGISTRY_PATH = Path("/tmp/feishu-bridge/registry.json")


def load_registry() -> dict[str, dict]:
    """Read raw registry dict from disk.

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
    return data


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
