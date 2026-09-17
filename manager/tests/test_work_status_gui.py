"""Tests for the work-status GUI interactions."""

import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel
import pytest

from claude_manager.tabs import work_status_gui
from claude_manager.tabs.work_status import AIProcess, OSWindowStatus, TabStatus


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def sample_windows():
    return [
        OSWindowStatus(
            window_id=10,
            socket="unix:@first",
            is_focused=True,
            tabs=[
                TabStatus(
                    101,
                    "First tab",
                    True,
                    1,
                    [
                        AIProcess("claude", "/work/one", ["claude"], 1),
                        AIProcess("codex", "/work/two", ["codex"], 2),
                    ],
                ),
                TabStatus(102, "Second tab", False, 1, []),
            ],
        ),
        OSWindowStatus(
            window_id=20,
            socket="unix:@second",
            is_focused=False,
            tabs=[TabStatus(201, "Third tab", True, 1, [])],
        ),
    ]


@pytest.fixture
def window(app, monkeypatch, sample_windows):
    monkeypatch.setattr(work_status_gui, "scan_all_windows", lambda: sample_windows)
    monkeypatch.setattr(work_status_gui.WorkStatusGUI, "load_visited_history", lambda self: None)
    monkeypatch.setattr(work_status_gui.WorkStatusGUI, "load_ignored_list", lambda self: None)
    gui = work_status_gui.WorkStatusGUI()
    yield gui
    gui.refresh_timer.stop()
    gui.close()


def test_loads_all_tabs_for_selected_window(window, sample_windows):
    assert window.current_window == sample_windows[0]
    assert window.window_list.item(0).text() == "● ▶ Tab 101 · first"
    assert window.window_list.item(1).text() == "▶ Tab 201 · second"
    assert window.tab_list.topLevelItemCount() == 2
    first_item = window.tab_list.topLevelItem(0)
    assert first_item.data(0, Qt.UserRole).tab_id == 101
    assert first_item.text(0).splitlines() == [
        "▶ Tab 101: First tab",
        "  ● Claude Code → /work/one",
        "  ● Codex → /work/two",
    ]
    assert first_item.text(1) == "×"


def test_dashboard_uses_each_agent_working_directory(window):
    directories = {
        card.findChild(QLabel, "directoryLabel").text()
        for _, card in window.dashboard_entries
    }

    assert directories == {"/work/one", "/work/two"}


def test_arrow_selection_updates_tab_list(window, sample_windows):
    window.window_list.setCurrentRow(1)

    assert window.current_window == sample_windows[1]
    assert window.tab_list.topLevelItemCount() == 1
    assert window.tab_list.topLevelItem(0).data(0, Qt.UserRole).tab_id == 201


def test_tab_content_jumps_and_close_column_closes(window, monkeypatch):
    item = window.tab_list.topLevelItem(0)
    jumped = []
    closed = []
    monkeypatch.setattr(window, "jump_to_tab", lambda os_win, tab: jumped.append(tab.tab_id))
    monkeypatch.setattr(window, "close_tab", lambda os_win, tab: closed.append(tab.tab_id))

    window.on_tab_clicked(item, 0)
    window.on_tab_clicked(item, 1)

    assert jumped == [101]
    assert closed == [101]


def test_instance_lock_allows_only_one_process(tmp_path):
    lock_path = tmp_path / "work-status.lock"

    first_lock = work_status_gui._acquire_instance_lock(lock_path)
    second_lock = work_status_gui._acquire_instance_lock(lock_path)

    assert first_lock is not None
    assert second_lock is None

    first_lock.close()
    replacement_lock = work_status_gui._acquire_instance_lock(lock_path)
    assert replacement_lock is not None
    replacement_lock.close()


def test_background_launch_detaches_from_terminal(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/work-status"])
    monkeypatch.setattr(
        work_status_gui.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    assert work_status_gui._launch_background() == 0
    command, kwargs = calls[0]
    assert command == [sys.executable, "/usr/local/bin/work-status"]
    assert kwargs["env"][work_status_gui._BACKGROUND_ENV] == "1"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True


def test_main_does_not_spawn_when_instance_is_running(monkeypatch):
    monkeypatch.delenv(work_status_gui._BACKGROUND_ENV, raising=False)
    monkeypatch.setattr(work_status_gui, "_instance_is_running", lambda: True)
    monkeypatch.setattr(
        work_status_gui,
        "_launch_background",
        lambda: pytest.fail("must not launch a second instance"),
    )

    assert work_status_gui.main() == 0
