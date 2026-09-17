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


def _write_session(
    path: Path,
    *,
    originator: str,
    cwd: str,
    timestamp: str | None = None,
) -> None:
    payload = {
        "id": "session-1",
        "timestamp": timestamp
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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


def test_discover_session_accepts_recently_updated_resumed_session(tmp_path):
    session_path = tmp_path / "sessions" / "2026" / "06" / "28" / "rollout.jsonl"
    _write_session(
        session_path,
        originator="codex-tui",
        cwd="/tmp/project",
        timestamp="2026-01-01T00:00:00Z",
    )

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


def test_user_message_updates_task_summary_for_this_window():
    codex_monitor = monitor.CodexEventMonitor(
        window_id="17",
        kitty_socket="unix:@mykitty",
        cwd="/tmp/project",
    )
    calls = []
    codex_monitor._run_script = lambda script, extra_env=None: calls.append(
        (script, extra_env)
    )

    codex_monitor._handle_event(
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "修复任务看板"},
        }
    )

    assert calls == [
        (codex_monitor.working_script, {"CM_TASK_SUMMARY": "修复任务看板"})
    ]


def test_user_message_ignores_events_from_before_monitor_started():
    codex_monitor = monitor.CodexEventMonitor(
        window_id="17",
        kitty_socket="unix:@mykitty",
        cwd="/tmp/project",
    )
    codex_monitor.start_time = time.time()
    calls = []
    codex_monitor._run_script = lambda script, extra_env=None: calls.append(
        (script, extra_env)
    )

    codex_monitor._handle_event(
        {
            "type": "event_msg",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"type": "user_message", "message": "旧任务"},
        }
    )

    assert calls == []


def test_window_spinner_triggers_working_once_per_visible_transition():
    codex_monitor = monitor.CodexEventMonitor(
        window_id="17",
        kitty_socket="unix:@mykitty",
        cwd="/tmp/project",
    )
    calls = []
    codex_monitor._run_script = lambda script, extra_env=None: calls.append(script)

    codex_monitor._sync_title_working_state("⠋ project")
    codex_monitor._sync_title_working_state("⠙ project")
    codex_monitor._sync_title_working_state("project")
    codex_monitor._sync_title_working_state("⠸ project")

    assert calls == [codex_monitor.working_script, codex_monitor.working_script]


def test_window_spinner_stopping_triggers_completed_after_grace(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(monitor.time, "time", lambda: now[0])
    codex_monitor = monitor.CodexEventMonitor(
        window_id="17",
        kitty_socket="unix:@mykitty",
        cwd="/tmp/project",
    )
    calls = []
    codex_monitor._run_script = lambda script, extra_env=None: calls.append(
        (script, extra_env)
    )

    codex_monitor._sync_title_working_state("⠋ project")
    codex_monitor._sync_title_working_state("project")
    now[0] += 1.0
    codex_monitor._sync_title_working_state("project")

    assert calls == [
        (codex_monitor.working_script, None),
        (codex_monitor.completed_script, {"CM_COMPLETED_MESSAGE": ""}),
    ]


def test_task_complete_prevents_duplicate_title_completion(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(monitor.time, "time", lambda: now[0])
    codex_monitor = monitor.CodexEventMonitor(
        window_id="17",
        kitty_socket="unix:@mykitty",
        cwd="/tmp/project",
    )
    calls = []
    codex_monitor._run_script = lambda script, extra_env=None: calls.append(
        (script, extra_env)
    )

    codex_monitor._sync_title_working_state("⠋ project")
    codex_monitor._handle_event(
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-1",
                "last_agent_message": "done",
            },
        }
    )
    codex_monitor._sync_title_working_state("project")
    now[0] += 1.0
    codex_monitor._sync_title_working_state("project")

    assert calls == [
        (codex_monitor.working_script, None),
        (codex_monitor.completed_script, {"CM_COMPLETED_MESSAGE": "done"}),
    ]
