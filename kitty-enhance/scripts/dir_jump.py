#!/usr/bin/env python3
"""Jump to an existing kitty window by cwd.

Collects every kitty window's current working directory via `kitten @ ls`,
sorts by recent activity (using /tmp/feishu-bridge/registry.json when
available), shows an interactive picker, and focuses the selected window.

The selected window is the existing window — its shell history, running
command, and scrollback are preserved.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_PATH = Path("/tmp/feishu-bridge/registry.json")
KITTEN_TIMEOUT = 3.0
HOME = str(Path.home())


@dataclass
class WindowRef:
    socket: str
    window_id: str
    tab_title: str


@dataclass
class DirEntry:
    cwd: str
    last_activity: float           # epoch seconds; 0 if unknown
    window_refs: list[WindowRef] = field(default_factory=list)

    @property
    def display_cwd(self) -> str:
        if self.cwd.startswith(HOME):
            return "~" + self.cwd[len(HOME):]
        return self.cwd

    @property
    def primary_ref(self) -> WindowRef:
        return self.window_refs[0]

    @property
    def extra_count(self) -> int:
        return len(self.window_refs) - 1


# ─────────────────────────────────────────────────────────────────────
# Data collection
# ─────────────────────────────────────────────────────────────────────

def _load_registry() -> dict[tuple[str, str], float]:
    """Return {(socket, window_id): last_activity} from registry.json."""
    if not REGISTRY_PATH.exists():
        return {}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}

    out: dict[tuple[str, str], float] = {}
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        socket = str(entry.get("kitty_socket") or "").strip()
        wid = str(entry.get("window_id") or "").strip()
        if not socket or not wid:
            continue
        try:
            ts = float(entry.get("last_activity") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        # Keep the max if duplicate (window_id collisions across tmux panes).
        out[(socket, wid)] = max(ts, out.get((socket, wid), 0.0))
    return out


def _discover_sockets() -> list[str]:
    """Sockets to query: registry's known set + current $KITTY_LISTEN_ON."""
    sockets: set[str] = set()
    if REGISTRY_PATH.exists():
        try:
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for entry in data.values():
                    if isinstance(entry, dict):
                        s = str(entry.get("kitty_socket") or "").strip()
                        if s:
                            sockets.add(s)
        except (json.JSONDecodeError, OSError):
            pass

    current = os.environ.get("KITTY_LISTEN_ON", "").strip()
    if current:
        sockets.add(current)
    return sorted(sockets)


def _list_windows(socket: str) -> list[dict]:
    """Return [{'window_id', 'tab_title', 'cwd'}] for one kitty socket.

    Empty list on any failure.
    """
    try:
        result = subprocess.run(
            ["kitten", "@", "--to", socket, "ls"],
            capture_output=True,
            text=True,
            timeout=KITTEN_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    out: list[dict] = []
    for os_win in data:
        for tab in os_win.get("tabs", []):
            tab_title = tab.get("title", "")
            for win in tab.get("windows", []):
                wid = str(win.get("id", ""))
                cwd = win.get("cwd", "") or ""
                if not wid or not cwd:
                    continue
                out.append({"window_id": wid, "tab_title": tab_title, "cwd": cwd})
    return out


def collect_open_dirs() -> list[DirEntry]:
    """Aggregate every kitty window's cwd, attaching last_activity from registry."""
    registry = _load_registry()
    by_cwd: dict[str, DirEntry] = {}

    for socket in _discover_sockets():
        for win in _list_windows(socket):
            cwd = win["cwd"]
            wid = win["window_id"]
            ref = WindowRef(socket=socket, window_id=wid, tab_title=win["tab_title"])
            ts = _resolve_last_activity(socket, wid, registry)

            if cwd in by_cwd:
                entry = by_cwd[cwd]
                entry.window_refs.append(ref)
                entry.last_activity = max(entry.last_activity, ts)
            else:
                by_cwd[cwd] = DirEntry(cwd=cwd, last_activity=ts, window_refs=[ref])

    return list(by_cwd.values())


def _resolve_last_activity(
    socket: str,
    window_id: str,
    registry: dict[tuple[str, str], float],
) -> float:
    """Return last_activity for a window.

    Registry hit → use it. No hit (pure-shell window) → fallback below.

    TODO(user, 5–10 lines): pick the fallback for unknown windows.
    The choice decides whether brand-new shell windows surface to the TOP
    of the picker or sink to the BOTTOM.

    Inputs available:
      - window_id: kitty's monotonic integer (str). Higher = created later
        in this kitty instance. NOT comparable across kitty instances.
      - socket: the kitty instance the window belongs to.
      - time.time(): wall clock.

    Three reasonable strategies:
      1) Return 0.0   →  unknown sinks to BOTTOM (registry-known dirs win).
      2) Return time.time()  →  unknown floats to TOP (favors fresh shells).
      3) Map window_id into a synthetic timestamp (e.g. base - 10_000 + int(wid))
         →  newer windows beat older ones, but all still sit below true
         registry timestamps unless base is large.

    Pick one and return it.
    """
    hit = registry.get((socket, window_id))
    if hit is not None:
        return hit

    # ↓↓↓ USER FILLS THIS ↓↓↓
    raise NotImplementedError(
        "fallback for unknown windows — see TODO above"
    )
    # ↑↑↑ USER FILLS THIS ↑↑↑


# ─────────────────────────────────────────────────────────────────────
# Picker UI (alt-screen + raw mode, up/down + Enter)
# ─────────────────────────────────────────────────────────────────────

def _format_idle(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _read_key(fd: int) -> str:
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        seq = os.read(fd, 1)
        if seq == b"[":
            code = os.read(fd, 1)
            return {b"A": "up", b"B": "down"}.get(code, "")
        return "esc"
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"q":
        return "quit"
    if ch == b"j":
        return "down"
    if ch == b"k":
        return "up"
    return ""


def _write(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _render(entries: list[DirEntry], selected: int, now: float) -> None:
    cwd_w = max((len(e.display_cwd) for e in entries), default=10)
    cwd_w = min(cwd_w, 80)
    tab_w = max((len(e.primary_ref.tab_title) for e in entries), default=6)
    tab_w = min(tab_w, 30)

    buf = ["\033[2J\033[H"]
    header = f"  \033[1m{'CWD':<{cwd_w}}  {'TAB':<{tab_w}}  {'WIN':>4}  LAST\033[0m"
    buf.append(header)

    for i, e in enumerate(entries):
        cwd_disp = e.display_cwd
        if len(cwd_disp) > cwd_w:
            cwd_disp = "…" + cwd_disp[-(cwd_w - 1):]
        tab_disp = e.primary_ref.tab_title[:tab_w]
        extra = f"+{e.extra_count}" if e.extra_count > 0 else ""
        win_col = f"{e.primary_ref.window_id}{extra}"
        idle = _format_idle(now - e.last_activity) if e.last_activity > 0 else "—"

        line = f"  {cwd_disp:<{cwd_w}}  {tab_disp:<{tab_w}}  {win_col:>4}  {idle}"
        if i == selected:
            buf.append(f"\033[48;5;24m\033[1m> {line[2:]}\033[K\033[0m")
        elif i % 2 == 0:
            buf.append(f"\033[48;5;236m{line}\033[K\033[0m")
        else:
            buf.append(f"{line}\033[K")

    buf.append("")
    buf.append(
        f"  \033[90m↑↓/jk select  Enter jump  q/Esc quit  "
        f"({len(entries)} dirs)\033[0m"
    )
    _write("\r\n".join(buf))


def _focus(ref: WindowRef) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["kitten", "@", "--to", ref.socket,
             "focus-window", "--match", f"id:{ref.window_id}"],
            capture_output=True, text=True, timeout=KITTEN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "kitten focus-window timed out"
    except FileNotFoundError:
        return False, "kitten not found"
    if result.returncode != 0:
        return False, result.stderr.strip() or f"rc={result.returncode}"
    return True, ""


def run() -> int:
    entries = collect_open_dirs()
    if not entries:
        print("no kitty windows found")
        return 0

    entries.sort(key=lambda e: -e.last_activity)
    selected = 0
    now = time.time()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    _write("\033[?1049h\033[?25l")  # alt screen + hide cursor

    try:
        tty.setraw(fd)
        _render(entries, selected, now)
        while True:
            key = _read_key(fd)
            if key in ("quit", "esc"):
                return 0
            if key == "up":
                selected = (selected - 1) % len(entries)
            elif key == "down":
                selected = (selected + 1) % len(entries)
            elif key == "enter":
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                _write("\033[?25h\033[?1049l")
                ok, err = _focus(entries[selected].primary_ref)
                if not ok:
                    print(f"focus failed: {err}", file=sys.stderr)
                    return 1
                return 0
            else:
                continue
            _render(entries, selected, now)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        _write("\033[?25h\033[?1049l")


if __name__ == "__main__":
    sys.exit(run())
