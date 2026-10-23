"""Tests for shared Kitty tab-color state transitions."""

from __future__ import annotations

import shutil

import pytest
import subprocess
from pathlib import Path


COMMON = Path(__file__).resolve().parent.parent / "hooks" / "tab-color-common.sh"
WORKING = Path(__file__).resolve().parent.parent / "scripts" / "codex-working.sh"


def test_forced_working_color_replaces_previous_completed_color(tmp_path):
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
source "$1"
STATE_DIR="$2"
kitty() { return 0; }
state_file="$(_state_file unix:@test 7)"
echo red > "$state_file"
set_tab_color unix:@test 7 blue force
cat "$state_file"
""",
            "bash",
            str(COMMON),
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "blue"


def test_clear_tab_color_state_resets_kitty_before_removing_state(tmp_path):
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
source "$1"
STATE_DIR="$2"
kitty() { printf '%s\n' "$*"; }
state_file="$(_state_file unix:@test 7)"
echo blue > "$state_file"
clear_tab_color_state unix:@test 7
test ! -f "$state_file" && echo state-cleared
""",
            "bash",
            str(COMMON),
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "active_bg=NONE" in result.stdout
    assert result.stdout.strip().endswith("state-cleared")


def test_focused_working_tab_sets_inactive_blue(tmp_path):
    scripts_dir = tmp_path / "scripts"
    bridge_dir = tmp_path / "feishu-bridge"
    scripts_dir.mkdir()
    bridge_dir.mkdir()
    working = scripts_dir / "codex-working.sh"
    shutil.copy2(WORKING, working)
    working.write_text(working.read_text().replace("/tmp/feishu-bridge/.registry.lock", str(tmp_path / "registry.lock")))
    state_file = tmp_path / "state"
    reset_log = tmp_path / "reset"
    (scripts_dir / "tab-color-common.sh").write_text(
        f"""
cleanup_focused_tabs() {{ :; }}
get_tab_info() {{ echo '7 1'; }}
_state_file() {{ echo '{state_file}'; }}
clear_tab_color_state() {{ echo reset > '{reset_log}'; rm -f '{state_file}'; }}
set_tab_color() {{ echo "$3" > '{state_file}'; }}
ensure_poller() {{ :; }}
debug() {{ :; }}
""",
        encoding="utf-8",
    )
    (bridge_dir / "terminal_registry.py").write_text(
        """
def build_terminal_id(window_id, socket): return window_id
def load_registry(): return {}
def save_registry(registry): pass
def socket_to_label(socket): return socket
""",
        encoding="utf-8",
    )

    subprocess.run(
        [str(working)],
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "KITTY_WINDOW_ID": "17",
            "KITTY_LISTEN_ON": "unix:@test",
            "PWD": "/work/project",
        },
    )

    assert not reset_log.exists()
    assert state_file.read_text(encoding="utf-8").strip() == "blue"


def test_working_color_uses_theme_when_selected_and_blue_when_unselected(tmp_path):
    result = subprocess.run(
        ["bash", "-c", """
source "$1"
STATE_DIR="$2"
kitty() { echo "$*"; }
debug() { :; }
set_tab_color unix:@test 7 blue
""", "bash", str(COMMON), str(tmp_path)],
        check=True, capture_output=True, text=True,
    )
    assert "active_bg=NONE active_fg=NONE inactive_bg=#1565C0" in result.stdout


def test_focusing_running_tab_preserves_inactive_blue(tmp_path):
    result = subprocess.run(
        ["bash", "-c", """
source "$1"
STATE_DIR="$2"
kitty() {
    if [ "$4" = ls ]; then
        echo '[{"is_focused":true,"tabs":[{"id":7,"is_focused":true}]}]'
    else
        echo "$*"
    fi
}
sf=$(_state_file unix:@test 7)
echo blue > "$sf"
cleanup_focused_tabs unix:@test
cat "$sf"
""", "bash", str(COMMON), str(tmp_path)],
        check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "blue"


def test_poller_timeout_preserves_running_state(tmp_path):
    result = subprocess.run(
        ["bash", "-c", """
source "$1"
STATE_DIR="$2"
kitty() { :; }
sleep() { :; }
seq() { :; }
disown() { :; }
sf=$(_state_file unix:@test 7)
echo blue > "$sf"
ensure_poller unix:@test
wait
cat "$sf"
""", "bash", str(COMMON), str(tmp_path)],
        check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "blue"


@pytest.mark.parametrize("previous", ["", "red", "none"])
def test_claude_tool_started_in_selected_tab_records_working(tmp_path, previous):
    hook = tmp_path / "on-tool-use.sh"
    source = COMMON.parent / "on-tool-use.sh"
    hook.write_text(source.read_text().replace(
        '/tmp/kitty-tabcache-${WINDOW_ID}', str(tmp_path / "cache")
    ))
    state_file = tmp_path / "state"
    if previous:
        state_file.write_text(previous)
    log = tmp_path / "colors"
    (tmp_path / "tab-color-common.sh").write_text(COMMON.read_text() + f"""
_state_file() {{ echo '{state_file}'; }}
get_tab_info() {{ echo '7 1'; }}
kitty() {{ echo "$*" >> '{log}'; }}
debug() {{ :; }}
""")
    (tmp_path / "feishu-register.sh").write_text('_feishu_register() { :; }')
    subprocess.run(
        ["bash", "-c", 'disown() { wait; }; export -f disown; bash "$1"', "bash", str(hook)],
        env={"PATH": "/usr/bin:/bin", "KITTY_WINDOW_ID": "17"},
        check=True,
    )
    assert state_file.read_text().strip() == "blue"
    assert "active_bg=NONE active_fg=NONE inactive_bg=#1565C0" in log.read_text()
