#!/usr/bin/env python3
"""Parse `kitty @ ls` JSON and generate a Kitty session file.

Usage: kitty @ ls | python3 session-snapshot.py > output.session
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

SHELLS = {"bash", "zsh", "sh", "fish", "dash", "ksh", "csh", "tcsh"}

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"

# Flags injected into every claude launch command if not already present.
# Lets us recover flags that argv lost (e.g. claude internally re-execs
# without --dangerously-skip-permissions). Override via env var.
DEFAULT_CLAUDE_FLAGS = shlex.split(os.environ.get("CLAUDE_DEFAULT_FLAGS", ""))

# Whitelist of long-running commands worth restoring verbatim. Anything not
# in this set (and not claude / shell) is treated as transient — restore
# opens a default shell so we don't re-execute one-shot commands like
# `kitten @ ls` that happened to be in the foreground at save time.
DEFAULT_RESTORABLE = (
    "vim,nvim,vi,emacs,nano,"
    "htop,top,btop,glances,"
    "ssh,mosh,"
    "less,more,man,"
    "ranger,yazi,nnn,lf,"
    "lazygit,gitui,tig,"
    "tmux,screen"
)
RESTORABLE_COMMANDS = {
    s
    for s in os.environ.get("KITTY_ENHANCE_RESTORABLE", DEFAULT_RESTORABLE).split(",")
    if s.strip()
}


def get_claude_session_id(pid: int | None) -> str | None:
    """Authoritative PID -> sessionId via Claude Code's per-pid session file.

    Claude Code maintains ~/.claude/sessions/<pid>.json containing
    {"pid", "sessionId", "cwd", ...} for each live process. This beats
    any mtime-based heuristic on the conversation jsonl, which doesn't
    exist for sessions that haven't received a first message yet.
    """
    if not pid:
        return None
    try:
        with (CLAUDE_SESSIONS_DIR / f"{pid}.json").open() as f:
            return json.load(f).get("sessionId")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def claude_session_has_log(cwd: str, session_id: str) -> bool:
    """Whether claude has written a conversation jsonl for this session.

    Idle claudes (no message sent yet) have a sessionId but no jsonl —
    `claude --resume <id>` against them fails, so we must skip --resume.
    cwd encoding: '/' and '.' both become '-'.
    """
    if not cwd or not session_id:
        return False
    encoded = cwd.replace("/", "-").replace(".", "-")
    return (Path.home() / ".claude" / "projects" / encoded / f"{session_id}.jsonl").exists()


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


def is_restorable(cmdline: list[str]) -> bool:
    """Whether this non-claude, non-shell command is in the restore whitelist."""
    if not cmdline:
        return False
    basename = cmdline[0].rsplit("/", 1)[-1]
    return basename in RESTORABLE_COMMANDS


def find_claude_proc(fg_processes: list[dict]) -> dict | None:
    """Return the claude foreground process record (with pid + cmdline), or None.

    Walks the entire foreground process group because Claude Code hook
    subprocesses (bash on-tool-use.sh, sleep, etc.) can occupy fg[0] when
    `kitty @ ls` samples mid-hook.
    """
    for proc in fg_processes:
        cmd = proc.get("cmdline") or []
        if is_claude(cmd):
            return proc
    return None


def get_launch_command(cmdline: list[str]) -> str | None:
    """Determine the launch command for a window.

    Returns None for shells AND unrecognized foregrounds (transient commands
    like `kitten @ ls` shouldn't be re-executed on restore).
    For claude: normalizes argv[0] basename to 'claude', merges
    DEFAULT_CLAUDE_FLAGS in front of existing argv (deduped).
    For whitelisted commands: returns command verbatim with argv[0]
    normalized to its basename.
    """
    if is_shell(cmdline):
        return None
    if is_claude(cmdline):
        existing = list(cmdline[1:])
        merged = list(DEFAULT_CLAUDE_FLAGS)
        for arg in existing:
            if arg not in merged:
                merged.append(arg)
        return " ".join(["claude"] + merged)
    if is_restorable(cmdline):
        basename = cmdline[0].rsplit("/", 1)[-1]
        return " ".join([basename] + list(cmdline[1:]))
    return None


def generate_session(kitty_ls: list[dict], name: str = "") -> str:
    """Generate Kitty session file content from kitty @ ls output."""
    if not kitty_ls:
        return "# No windows found\n"

    if len(kitty_ls) > 1:
        print(
            f"[snapshot] WARN: 只保存第 0 个 OS window，"
            f"其余 {len(kitty_ls) - 1} 个被丢弃",
            file=sys.stderr,
        )

    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    os_window = kitty_ls[0]
    tabs = os_window["tabs"]

    lines.append(f"# Session: {name} | Saved: {now} | Tabs: {len(tabs)}")
    lines.append("")

    for ti, tab in enumerate(tabs):
        title = tab.get("title", "")
        layout = tab.get("layout", "stack")
        windows = tab.get("windows", [])

        print(
            f"[snapshot] Tab[{ti}] {title!r} ({len(windows)} windows)",
            file=sys.stderr,
        )

        lines.append(f"new_tab {title}")
        lines.append(f"layout {layout}")

        for i, window in enumerate(windows):
            cwd = window.get("cwd", "")
            fg = window.get("foreground_processes", [])

            # Prefer claude anywhere in fg (hook subprocesses can mask fg[0]).
            claude_proc = find_claude_proc(fg)
            if claude_proc is not None:
                cmdline = claude_proc.get("cmdline") or []
                claude_pid = claude_proc.get("pid")
                session_id = get_claude_session_id(claude_pid)
                resumable = bool(session_id) and claude_session_has_log(cwd, session_id)
            else:
                cmdline = fg[0].get("cmdline", []) if fg else []
                session_id = None
                resumable = False

            launch_cmd = get_launch_command(cmdline)
            if launch_cmd and is_claude(cmdline) and "--resume" not in launch_cmd:
                if resumable:
                    launch_cmd = f"{launch_cmd} --resume {session_id}"

            if claude_proc is not None:
                if resumable:
                    msg = f"claude session={session_id}"
                elif session_id:
                    msg = f"claude session={session_id} (idle, no jsonl → fresh restore)"
                else:
                    msg = "claude (no session-id, fresh restore)"
                print(f"[snapshot]   win[{i}] cwd={cwd}  {msg}", file=sys.stderr)
            elif launch_cmd:
                print(
                    f"[snapshot]   win[{i}] cwd={cwd}  cmd={launch_cmd}",
                    file=sys.stderr,
                )
            elif cmdline and not is_shell(cmdline):
                basename = cmdline[0].rsplit("/", 1)[-1]
                print(
                    f"[snapshot]   win[{i}] cwd={cwd}  (skipped fg={basename}, restore as shell)",
                    file=sys.stderr,
                )
            else:
                print(f"[snapshot]   win[{i}] cwd={cwd}", file=sys.stderr)

            # Pin cwd per-launch (kitty's `cd` directive doesn't reliably
            # propagate across multiple launches in the same tab).
            args: list[str] = []
            if cwd:
                args.append(f"--cwd {shlex.quote(cwd)}")
            if i > 0:
                args.append("--type=window")
            if launch_cmd:
                args.append(launch_cmd)
            lines.append("launch " + " ".join(args) if args else "launch")

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
