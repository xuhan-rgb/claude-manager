"""XTerm terminal adapter.

Creates separate xterm OS windows as panels. No remote control is available,
so focus/resize/send_text are not supported.
"""

import os
import shutil
import shlex
import subprocess
import time
import sys
import tempfile
import uuid
from typing import Optional, List

from .adapter import TerminalAdapter, WindowInfo, SplitResult


class XtermAdapter(TerminalAdapter):
    """XTerm adapter (spawns separate windows)."""

    def __init__(self, xterm_cmd: str = "xterm", terminal_args: Optional[list[str]] = None):
        self._xterm_cmd = xterm_cmd
        self._terminal_args = terminal_args or ["-T", "Claude Manager", "-e"]
        self._windows: dict[str, dict[str, object]] = {}

    @property
    def name(self) -> str:
        return "xterm"

    def is_available(self) -> tuple[bool, str]:
        if not shutil.which(self._xterm_cmd):
            return False, "xterm not found"
        return True, "xterm available"

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    # ========== Window operations ==========

    def create_split(
        self,
        direction: str = "vertical",
        command: str = "bash",
        cwd: Optional[str] = None
    ) -> SplitResult:
        window_id = str(uuid.uuid4())
        tty_file = os.path.join(tempfile.gettempdir(), f"cm-tty-{window_id}")

        shell_cmd = ""
        if cwd:
            shell_cmd += f"cd {shlex.quote(str(cwd))}; "
        shell_cmd += f"tty > {shlex.quote(tty_file)} 2>/dev/null; "
        shell_cmd += f"exec {command or 'bash'}"

        args = [self._xterm_cmd] + list(self._terminal_args) + [
            "bash",
            "-lc",
            shell_cmd,
        ]
        try:
            proc = subprocess.Popen(args)
        except Exception as exc:
            return SplitResult(False, error=str(exc))

        self._windows[window_id] = {
            "pid": proc.pid,
            "tty_file": tty_file,
            "command": command,
        }
        return SplitResult(True, window_id=window_id)

    def close_window(self, window_id: str) -> bool:
        info = self._windows.get(str(window_id))
        if not info:
            return False
        pid = info.get("pid")
        if not isinstance(pid, int):
            return False
        try:
            os.kill(pid, 15)
            return True
        except Exception:
            return False

    def focus_window(self, window_id: str) -> bool:
        return False

    def resize_window(
        self,
        window_id: str,
        columns: Optional[int] = None,
        increment: Optional[int] = None,
        axis: str = "horizontal"
    ) -> bool:
        return False

    def send_text(self, text: str, window_id: Optional[str] = None) -> bool:
        tty = None
        if window_id:
            tty = self._resolve_tty(window_id)
        if not tty and window_id is None:
            try:
                tty = os.ttyname(sys.stdout.fileno())
            except Exception:
                tty = None
        if not tty:
            return False
        for _ in range(3):
            if os.path.exists(tty):
                break
            time.sleep(0.05)
        try:
            fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY)
            try:
                os.write(fd, text.encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except Exception:
            return False

    # ========== Info helpers ==========

    def _read_tty(self, tty_file: str) -> Optional[str]:
        try:
            if os.path.exists(tty_file):
                with open(tty_file, "r", encoding="utf-8") as f:
                    value = f.read().strip()
                    if not value:
                        return None
                    if value == "not a tty":
                        return None
                    if value.startswith("/dev/"):
                        return value
                    return f"/dev/{value}"
        except Exception:
            return None
        return None

    def _resolve_tty(self, window_id: str) -> Optional[str]:
        info = self._windows.get(str(window_id))
        if not info:
            return None
        return self._read_tty(info.get("tty_file", ""))

    def get_window_info(self, window_id: str) -> Optional[WindowInfo]:
        info = self._windows.get(str(window_id))
        if not info:
            return None
        pid = info.get("pid")
        if not isinstance(pid, int) or not self._pid_alive(pid):
            return None
        tty = self._read_tty(info.get("tty_file", ""))
        return WindowInfo(id=str(window_id), tty=tty, pid=pid)

    def get_current_window(self) -> Optional[WindowInfo]:
        try:
            tty = os.ttyname(sys.stdout.fileno())
        except Exception:
            tty = None
        return WindowInfo(id=tty or "current", tty=tty, is_focused=True)

    def list_windows(self) -> List[WindowInfo]:
        windows: List[WindowInfo] = []
        for window_id, info in list(self._windows.items()):
            pid = info.get("pid")
            if not isinstance(pid, int) or not self._pid_alive(pid):
                continue
            tty = self._read_tty(info.get("tty_file", ""))
            windows.append(WindowInfo(id=str(window_id), tty=tty, pid=pid))
        return windows

    def get_total_columns(self) -> int:
        try:
            return os.get_terminal_size(sys.stdout.fileno()).columns
        except Exception:
            return 0

    # ========== Layout helpers ==========

    def set_layout(self, layout: str) -> bool:
        return True

    def lock_layout(self, layouts: List[str]) -> bool:
        return True
