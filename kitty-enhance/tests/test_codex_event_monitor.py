"""Tests for codex-event-monitor.py."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "codex-event-monitor.py"
SPEC = importlib.util.spec_from_file_location("codex_event_monitor", SCRIPT)
assert SPEC and SPEC.loader
monitor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


def _write_session(path: Path, *, originator: str, cwd: str) -> None:
    payload = {
        "id": "session-1",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cwd": cwd,
        "originator": originator,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "session_meta", "payload": payload}) + "\n", encoding="utf-8")
    now = time.time()
    os.utime(path, (now, now))


def test_discover_session_accepts_codex_cli_rs(tmp_path):
    session_path = tmp_path / "sessions" / "2026" / "06" / "28" / "rollout.jsonl"
    _write_session(session_path, originator="codex_cli_rs", cwd="/tmp/project")

    codex_monitor = monitor.CodexEventMonitor(
        window_id="1",
        kitty_socket="unix:@mykitty",
        cwd="/tmp/project",
    )
    codex_monitor.sessions_root = tmp_path / "sessions"
    codex_monitor.start_time = time.time()

    candidate = codex_monitor._discover_session()

    assert candidate is not None
    assert candidate.path == session_path


def test_discover_session_rejects_unsupported_originator(tmp_path):
    session_path = tmp_path / "sessions" / "2026" / "06" / "28" / "rollout.jsonl"
    _write_session(session_path, originator="codex_vscode", cwd="/tmp/project")

    codex_monitor = monitor.CodexEventMonitor(
        window_id="1",
        kitty_socket="unix:@mykitty",
        cwd="/tmp/project",
    )
    codex_monitor.sessions_root = tmp_path / "sessions"
    codex_monitor.start_time = time.time()

    candidate = codex_monitor._discover_session()

    assert candidate is None
