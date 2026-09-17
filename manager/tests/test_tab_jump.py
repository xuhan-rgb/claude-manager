"""Command construction tests for work-status tab actions."""

import os
from subprocess import CompletedProcess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from claude_manager.tabs import work_status, work_status_gui
from claude_manager.tabs.work_status import OSWindowStatus, TabStatus


def test_close_tab_targets_selected_socket_and_tab(monkeypatch):
    app = QApplication.instance() or QApplication([])
    tab = TabStatus(42, "Target", True, 1, [])
    os_window = OSWindowStatus(7, "unix:@target", True, [tab])
    monkeypatch.setattr(work_status_gui, "scan_all_windows", lambda: [os_window])
    monkeypatch.setattr(work_status_gui.WorkStatusGUI, "load_visited_history", lambda self: None)
    monkeypatch.setattr(work_status_gui.WorkStatusGUI, "load_ignored_list", lambda self: None)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(work_status_gui.subprocess, "run", fake_run)
    window = work_status_gui.WorkStatusGUI()
    monkeypatch.setattr(window, "load_data", lambda: None)

    window.close_tab(os_window, tab)

    assert calls == [
        (
            [
                "kitty", "@", "--to", "unix:@target", "close-tab",
                "--match", "id:42",
            ],
            {"capture_output": True, "text": True, "timeout": 3, "check": True},
        )
    ]
    window.refresh_timer.stop()
    window.close()


def test_scan_uses_active_tab_for_nonfocused_kitty_window(monkeypatch):
    monkeypatch.setattr(work_status, "_find_all_kitty_sockets", lambda: ["unix:@demo"])
    monkeypatch.setattr(
        work_status,
        "_get_kitty_ls",
        lambda socket: [{
            "id": 1,
            "is_focused": False,
            "tabs": [
                {"id": 10, "title": "old", "is_active": False, "windows": []},
                {"id": 11, "title": "current", "is_active": True, "windows": []},
            ],
        }],
    )

    windows = work_status.scan_all_windows()

    assert [tab.is_focused for tab in windows[0].tabs] == [False, True]


def test_ai_process_uses_task_for_its_kitty_window(monkeypatch):
    monkeypatch.setattr(
        work_status,
        "task_summary_for",
        lambda *args: "不应使用目录回退任务",
    )
    kitty_windows = [
        {
            "id": 17,
            "foreground_processes": [
                {
                    "cmdline": ["codex"],
                    "cwd": "/mnt/data/demo",
                    "pid": 123,
                }
            ],
        }
    ]
    registry = {
        "17@demo": {
            "status": "waiting",
            "task_summary": "修复这个窗口的任务看板",
        }
    }

    processes = work_status._extract_ai_processes(
        kitty_windows,
        socket="unix:@demo",
        registry=registry,
        tab_title="demo",
    )

    assert processes[0].status == "waiting"
    assert processes[0].task_summary == "修复这个窗口的任务看板"
    assert processes[0].cwd == "/mnt/data/demo"
