"""Tests for session-snapshot.py"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "session-snapshot.py")


def run_snapshot(kitty_ls_json: str) -> str:
    """Run session-snapshot.py with given JSON on stdin, return stdout."""
    result = subprocess.run(
        [sys.executable, SCRIPT],
        input=kitty_ls_json,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    return result.stdout


def make_window(cwd: str, cmdline: list[str]) -> dict:
    """Helper to create a minimal kitty window dict."""
    return {
        "cwd": cwd,
        "foreground_processes": [{"cmdline": cmdline}],
    }


def make_tab(title: str, layout: str, windows: list[dict]) -> dict:
    return {"title": title, "layout": layout, "windows": windows}


def make_kitty_ls(tabs: list[dict]) -> str:
    return json.dumps([{"tabs": tabs}])


class TestSingleTab:
    def test_shell_only_tab(self):
        """A tab with one bash window should produce new_tab + layout + cd."""
        ls_json = make_kitty_ls([
            make_tab("myterm", "stack", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab myterm" in output
        assert "layout stack" in output
        assert "cd /home/user" in output
        # Shell windows should NOT have an explicit launch command
        assert "launch" not in output

    def test_claude_tab(self):
        """A tab running claude should produce launch claude."""
        ls_json = make_kitty_ls([
            make_tab("Claude Code", "tall", [
                make_window("/mnt/data/project", ["claude", "--dangerously-skip-permissions"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab Claude Code" in output
        assert "cd /mnt/data/project" in output
        assert "launch claude" in output
        # Should NOT preserve flags
        assert "--dangerously-skip-permissions" not in output


class TestMultiWindow:
    def test_tab_with_claude_and_shells(self):
        """A tab with claude + 2 shells: first window implicit, extra windows use launch --type=window."""
        ls_json = make_kitty_ls([
            make_tab("work", "tall", [
                make_window("/mnt/data/proj", ["claude"]),
                make_window("/mnt/data", ["/bin/bash"]),
                make_window("/home/user", ["/bin/zsh"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        lines = output.strip().split("\n")
        # First window: cd + launch claude
        assert "cd /mnt/data/proj" in output
        assert "launch claude" in output
        # Extra shell windows use launch --type=window
        type_window_lines = [l for l in lines if "launch --type=window" in l]
        assert len(type_window_lines) == 2

    def test_non_shell_command(self):
        """A window running a non-shell, non-claude command should preserve full cmdline."""
        ls_json = make_kitty_ls([
            make_tab("files", "stack", [
                make_window("/home/user", ["nautilus", "/home/user/Documents"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "launch nautilus /home/user/Documents" in output


class TestMultipleTabs:
    def test_two_tabs(self):
        """Multiple tabs each produce a new_tab block."""
        ls_json = make_kitty_ls([
            make_tab("tab1", "tall", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
            make_tab("tab2", "stack", [
                make_window("/mnt/data", ["claude"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert output.count("new_tab") == 2
        assert "new_tab tab1" in output
        assert "new_tab tab2" in output


class TestEdgeCases:
    def test_empty_foreground_processes(self):
        """Window with no foreground_processes should be treated as shell."""
        ls_json = make_kitty_ls([
            make_tab("empty", "stack", [
                {"cwd": "/tmp", "foreground_processes": []},
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "cd /tmp" in output
        assert "launch" not in output

    def test_unicode_tab_title(self):
        """Unicode in tab title should be preserved."""
        ls_json = make_kitty_ls([
            make_tab("✳ 调试面板", "tall", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab ✳ 调试面板" in output
