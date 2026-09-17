"""Tests for shared Kitty tab-color state transitions."""

from __future__ import annotations

import shutil
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


def test_focused_working_tab_resets_color_before_pausing(tmp_path):
    scripts_dir = tmp_path / "scripts"
    bridge_dir = tmp_path / "feishu-bridge"
    scripts_dir.mkdir()
    bridge_dir.mkdir()
    working = scripts_dir / "codex-working.sh"
    shutil.copy2(WORKING, working)
    state_file = tmp_path / "state"
    reset_log = tmp_path / "reset"
    (scripts_dir / "tab-color-common.sh").write_text(
        f"""
cleanup_focused_tabs() {{ :; }}
get_tab_info() {{ echo '7 1'; }}
_state_file() {{ echo '{state_file}'; }}
clear_tab_color_state() {{ echo reset > '{reset_log}'; rm -f '{state_file}'; }}
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

    assert reset_log.read_text(encoding="utf-8").strip() == "reset"
    assert state_file.read_text(encoding="utf-8").strip() == "blue-paused"
