#!/usr/bin/env python3
"""Parse `kitty @ ls` JSON and generate a Kitty session file.

Usage: kitty @ ls | python3 session-snapshot.py > output.session
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

SHELLS = {"bash", "zsh", "sh", "fish", "dash", "ksh", "csh", "tcsh"}


def is_shell(cmdline: list[str]) -> bool:
    """Check if cmdline represents a shell process."""
    if not cmdline:
        return True
    basename = cmdline[0].rsplit("/", 1)[-1]
    # Handle bash --posix, zsh -i, etc.
    return basename in SHELLS


def is_claude(cmdline: list[str]) -> bool:
    """Check if cmdline is a claude process."""
    if not cmdline:
        return False
    basename = cmdline[0].rsplit("/", 1)[-1]
    return basename == "claude"


def get_launch_command(cmdline: list[str]) -> str | None:
    """Determine the launch command for a window.

    Returns None for shell windows (session file default).
    Returns 'claude' for claude (strips flags).
    Returns full cmdline string for other commands.
    """
    if is_shell(cmdline):
        return None
    if is_claude(cmdline):
        return "claude"
    return " ".join(cmdline)


def generate_session(kitty_ls: list[dict], name: str = "") -> str:
    """Generate Kitty session file content from kitty @ ls output."""
    if not kitty_ls:
        return "# No windows found\n"

    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    os_window = kitty_ls[0]
    tabs = os_window["tabs"]

    lines.append(f"# Session: {name} | Saved: {now} | Tabs: {len(tabs)}")
    lines.append("")

    for tab in tabs:
        title = tab.get("title", "")
        layout = tab.get("layout", "stack")
        windows = tab.get("windows", [])

        lines.append(f"new_tab {title}")
        lines.append(f"layout {layout}")

        for i, window in enumerate(windows):
            cwd = window.get("cwd", "")
            fg = window.get("foreground_processes", [])
            cmdline = fg[0].get("cmdline", []) if fg else []

            launch_cmd = get_launch_command(cmdline)

            if i == 0:
                # First window: use cd + optional launch
                lines.append(f'cd "{cwd}"')
                if launch_cmd:
                    lines.append(f"launch {launch_cmd}")
            else:
                # Additional windows: launch --type=window
                lines.append(f'cd "{cwd}"')
                if launch_cmd:
                    lines.append(f"launch --type=window {launch_cmd}")
                else:
                    lines.append("launch --type=window")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?", default="")
    args = parser.parse_args()

    data = json.load(sys.stdin)
    print(generate_session(data, name=args.name))


if __name__ == "__main__":
    main()
