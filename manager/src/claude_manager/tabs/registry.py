"""Registry reader for kitty terminals running Claude/Codex.

Reads /tmp/feishu-bridge/registry.json (written by existing kitty hooks)
and exposes a typed view of currently alive terminals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


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
