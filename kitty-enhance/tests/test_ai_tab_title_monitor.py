"""Tests for AI-aware Kitty tab titles."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ai-tab-title-monitor.py"
SPEC = importlib.util.spec_from_file_location("ai_tab_title_monitor", SCRIPT)
assert SPEC and SPEC.loader
monitor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor
SPEC.loader.exec_module(monitor)


def _window(
    window_id: int,
    cwd: str,
    *,
    ai: str | None = None,
    focused: bool = False,
) -> dict:
    processes = []
    if ai:
        processes.append({"cmdline": ["node", f"/opt/bin/{ai}"]})
    return {
        "id": window_id,
        "cwd": cwd,
        "is_focused": focused,
        "foreground_processes": processes,
    }


def _tab(*windows: dict, history: list[int], title: str = "dynamic") -> dict:
    return {
        "id": 7,
        "title": title,
        "active_window_history": history,
        "windows": list(windows),
    }


def test_selects_focused_ai_window_when_tab_has_multiple_ai_windows():
    tab = _tab(
        _window(10, "/work/first", ai="codex"),
        _window(11, "/work/second", ai="claude", focused=True),
        history=[10, 11],
    )

    selected = monitor.select_ai_window(tab)

    assert selected["id"] == 11
    assert monitor.ai_window_title(selected) == "second"


def test_selects_most_recent_ai_when_regular_window_is_focused():
    tab = _tab(
        _window(10, "/work/first", ai="codex"),
        _window(11, "/work/second", ai="claude"),
        _window(12, "/work/tools"),
        history=[12, 10, 11],
    )

    selected = monitor.select_ai_window(tab)

    assert selected["id"] == 10
    assert monitor.ai_window_title(selected) == "first"


def test_ai_window_title_preserves_live_working_indicator():
    window = _window(10, "/work/project", ai="codex")
    window["title"] = "⠙ project"

    assert monitor.ai_window_title(window) == "⠙ project"


def test_tracker_restores_dynamic_title_after_last_ai_exits():
    tracker = monitor.TabTitleTracker()
    ai_tab = _tab(_window(10, "/work/project", ai="codex"), history=[10])

    set_actions, has_ai = tracker.plan([{"tabs": [ai_tab]}])
    reset_actions, still_has_ai = tracker.plan(
        [{"tabs": [_tab(_window(12, "/work/tools"), history=[12], title="project")]}]
    )

    assert has_ai is True
    assert set_actions == [monitor.TitleAction(tab_id=7, title="project")]
    assert still_has_ai is False
    assert reset_actions == [monitor.TitleAction(tab_id=7, title=None)]


def test_tracker_leaves_ordinary_tabs_unchanged():
    tracker = monitor.TabTitleTracker()
    ordinary_tab = _tab(_window(12, "/work/tools"), history=[12])

    actions, has_ai = tracker.plan([{"tabs": [ordinary_tab]}])

    assert actions == []
    assert has_ai is False
