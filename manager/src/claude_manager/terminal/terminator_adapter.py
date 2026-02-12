"""Terminator terminal adapter.

Supports both layout-based panes and spawning separate windows.
"""

import shutil
import os
import subprocess
import time

from .adapter import WindowInfo

from .xterm_adapter import XtermAdapter
from .terminator_layouts import build_layout_config


class TerminatorAdapter(XtermAdapter):
    """Terminator adapter (spawns separate windows)."""

    def __init__(self, layout: str | None = None):
        super().__init__(xterm_cmd="terminator", terminal_args=["-x"])
        self._layout_id = os.environ.get("CM_LAYOUT_ID")
        self._layout_config = os.environ.get("CM_LAYOUT_CONFIG")
        self._layout_mode = layout or ""

    @property
    def name(self) -> str:
        return "terminator"

    def is_available(self) -> tuple[bool, str]:
        if not shutil.which(self._xterm_cmd):
            return False, "terminator not found"
        return True, "terminator available"

    def start_layout(self, layout_name: str = "auto", options: dict | None = None) -> bool:
        if layout_name and layout_name != "auto":
            cmd = [self._xterm_cmd, "--layout", layout_name]
            try:
                subprocess.Popen(cmd)
                return True
            except Exception:
                return False

        options = options or {}
        columns = float(options.get("columns", 0.68))
        width = int(options.get("width", 1200))
        height = int(options.get("height", 800))
        layout_id, config_path = build_layout_config(columns=columns, width=width, height=height)
        env = os.environ.copy()
        env["CM_LAYOUT_ID"] = layout_id
        env["CM_LAYOUT_CONFIG"] = config_path
        cmd = [self._xterm_cmd, "--config", config_path, "--layout", layout_id]
        try:
            subprocess.Popen(cmd, env=env)
        except Exception:
            return False
        time.sleep(0.4)
        self._layout_id = layout_id
        self._layout_config = config_path
        return True

    def _resolve_tty(self, window_id: str):
        if self._layout_id and window_id in {"main", "cmd"}:
            path = f"/tmp/cm-tty-{self._layout_id}-{window_id}"
            return self._read_tty(path)
        return super()._resolve_tty(window_id)

    def get_window_info(self, window_id: str):
        if self._layout_id and window_id in {"main", "cmd"}:
            tty = self._resolve_tty(window_id)
            if not tty:
                return None
            return WindowInfo(id=str(window_id), tty=tty)
        return super().get_window_info(window_id)
