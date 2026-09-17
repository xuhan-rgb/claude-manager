"""Tests for local task-summary discovery."""

import json
import os

from claude_manager.tabs.task_summary import clean_task_summary, task_summary_for


def test_clean_task_summary_uses_first_meaningful_line_and_truncates():
    summary = clean_task_summary("\n  修复标签页跳转逻辑\n补充回归测试\n")

    assert summary == "修复标签页跳转逻辑"


def test_clean_task_summary_returns_empty_for_noise():
    assert clean_task_summary("\n  \n") == ""


def test_task_summary_for_reads_latest_claude_index_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    index_dir = tmp_path / ".claude" / "projects" / "-mnt-data-demo"
    index_dir.mkdir(parents=True)
    index = {
        "entries": [
            {
                "projectPath": "/mnt/data/demo",
                "modified": "2026-08-07T01:00:00Z",
                "summary": "重构终端任务看板",
                "firstPrompt": "旧任务",
            }
        ]
    }
    (index_dir / "sessions-index.json").write_text(json.dumps(index), encoding="utf-8")

    parent_dir = tmp_path / ".claude" / "projects" / "-mnt-data"
    parent_dir.mkdir(parents=True)
    parent_index = {
        "entries": [
            {
                "projectPath": "/mnt/data",
                "modified": "2026-08-07T02:00:00Z",
                "summary": "不属于当前工程的任务",
            }
        ]
    }
    (parent_dir / "sessions-index.json").write_text(
        json.dumps(parent_index), encoding="utf-8"
    )

    assert task_summary_for("/mnt/data/demo", "claude") == "重构终端任务看板"


def test_task_summary_for_reads_latest_codex_user_message(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    session_dir = tmp_path / ".codex" / "sessions" / "2026" / "08" / "07"
    session_dir.mkdir(parents=True)
    session = [
        {
            "type": "session_meta",
            "payload": {"cwd": "/mnt/data/demo", "originator": "codex-tui"},
        },
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "整理任务卡片布局"},
        },
    ]
    exact_session = session_dir / "rollout-demo.jsonl"
    exact_session.write_text(
        "\n".join(json.dumps(item) for item in session), encoding="utf-8"
    )

    parent_session = [
        {"type": "session_meta", "payload": {"cwd": "/mnt/data"}},
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "父目录中的其他任务"},
        },
    ]
    parent_path = session_dir / "rollout-parent.jsonl"
    parent_path.write_text(
        "\n".join(json.dumps(item) for item in parent_session), encoding="utf-8"
    )
    os.utime(exact_session, (100, 100))
    os.utime(parent_path, (200, 200))

    assert task_summary_for("/mnt/data/demo", "codex") == "整理任务卡片布局"
