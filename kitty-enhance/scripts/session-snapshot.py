#!/usr/bin/env python3
"""Parse `kitty @ ls` JSON and generate a Kitty session file.

Usage: kitty @ ls | python3 session-snapshot.py > output.session
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SHELLS = {"bash", "zsh", "sh", "fish", "dash", "ksh", "csh", "tcsh"}

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
PROC_ROOT = Path("/proc")

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


def is_codex(cmdline: list[str]) -> bool:
    return bool(cmdline) and Path(cmdline[0]).name in {"codex", "codex-yolo"}


def codex_open_sessions(pid: int, codex_home: Path) -> dict[str, str]:
    """Read only rollout files held open by this process, never newest-by-cwd."""
    sessions: dict[str, str] = {}
    try:
        descriptors = list((PROC_ROOT / str(pid) / "fd").iterdir())
    except OSError:
        return sessions
    for descriptor in descriptors:
        try:
            path = descriptor.resolve(strict=True)
            if not path.is_relative_to(codex_home / "sessions") or path.suffix != ".jsonl":
                continue
            with path.open() as handle:
                record = json.loads(handle.readline())
            if record.get("type") == "session_meta":
                meta = record.get("payload") or {}
                if meta.get("id") and meta.get("cwd"):
                    sessions[meta["id"]] = meta["cwd"]
        except (OSError, RuntimeError, ValueError):
            continue
    return sessions


def codex_named_sessions(codex_home: Path, cwd: str, window_title: str) -> set[str]:
    """Match persisted conversation names, without relying on rollout lifetime."""
    title = window_title.strip()
    if title and "\u2800" <= title[0] <= "\u28ff":
        title = title[1:].lstrip()
    matches: set[str] = set()
    if not title:
        return matches
    for database in codex_home.glob("state_*.sqlite"):
        connection = None
        try:
            connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
            rows = connection.execute(
                "SELECT id, name, title, rollout_path FROM threads "
                "WHERE cwd IN (?, ?) AND archived = 0",
                (cwd, os.path.realpath(cwd)),
            )
            for session_id, name, initial_title, rollout_path in rows:
                names = [value for value in (name, initial_title) if value]
                if any(title == value or title.startswith(value + " | ") for value in names):
                    if Path(rollout_path).is_file():
                        matches.add(session_id)
        except (sqlite3.Error, OSError):
            continue
        finally:
            if connection is not None:
                connection.close()
    return matches


def get_codex_session_id(
    pid: int | None, cwd: str, cmdline: list[str], window_title: str = ""
) -> str | None:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    sessions = codex_open_sessions(pid, codex_home) if pid else {}
    if len(sessions) == 1:
        return next(iter(sessions))
    # Remote TUIs do not own the rollout. A local daemon may own several;
    # accept a cwd match only when it identifies exactly one loaded session.
    remote = next((arg.split("=", 1)[1] for arg in cmdline if arg.startswith("--remote=")), "")
    if "--remote" in cmdline:
        index = cmdline.index("--remote")
        remote = cmdline[index + 1] if index + 1 < len(cmdline) else ""
    for index, arg in enumerate(cmdline):
        if arg in {"-C", "--cd"} and index + 1 < len(cmdline):
            cwd = cmdline[index + 1]
        elif arg.startswith("--cd="):
            cwd = arg.split("=", 1)[1]
        elif arg.startswith("-C") and len(arg) > 2:
            cwd = arg[2:]
    if remote.startswith("unix://"):
        named = codex_named_sessions(codex_home, cwd, window_title)
        if named:
            return next(iter(named)) if len(named) == 1 else None
        try:
            processes = list(PROC_ROOT.iterdir())
        except OSError:
            processes = []
        for process in processes:
            if not process.name.isdigit():
                continue
            try:
                argv = [os.fsdecode(arg) for arg in (process / "cmdline").read_bytes().split(b"\0") if arg]
            except OSError:
                continue
            if is_codex(argv) and len(argv) > 1 and argv[1] == "app-server":
                sessions.update(codex_open_sessions(int(process.name), codex_home))
        matches = {sid for sid, directory in sessions.items() if os.path.realpath(directory) == os.path.realpath(cwd)}
        if len(matches) == 1:
            return matches.pop()
    return None


def resume_command(cmdline: list[str], session_id: str) -> str:
    """Replace launch-time session selectors with the currently active ID."""
    args = list(cmdline[1:])
    if is_claude(cmdline):
        cleaned: list[str] = []
        index = 0
        while index < len(args):
            arg = args[index]
            if arg in {"--continue", "-c", "--fork-session"}:
                index += 1
                continue
            if arg in {"--resume", "-r", "--session-id"}:
                index += 1
                if index < len(args) and not args[index].startswith("-"):
                    index += 1
                continue
            if arg.startswith(("--resume=", "--session-id=")):
                index += 1
                continue
            cleaned.append(arg)
            index += 1
        base = shlex.split(get_launch_command([cmdline[0]] + cleaned))
        return shlex.join(base + ["--resume", session_id])
    if "resume" in args:
        index = args.index("resume")
        args.pop(index)
        # Drop the old session ID and optional startup prompt.
        while index < len(args) and not args[index].startswith("-"):
            args.pop(index)
    args = [arg for arg in args if arg not in {"--last", "--all"}]
    return shlex.join(["codex", "resume", session_id] + args)


def is_restorable(cmdline: list[str]) -> bool:
    """Whether this non-claude, non-shell command is in the restore whitelist."""
    if not cmdline:
        return False
    basename = cmdline[0].rsplit("/", 1)[-1]
    return basename in RESTORABLE_COMMANDS


def find_ai_proc(fg_processes: list[dict]) -> dict | None:
    """Return the AI foreground process record (with pid + cmdline), or None.

    Walks the entire foreground process group because Claude Code hook
    subprocesses (bash on-tool-use.sh, sleep, etc.) can occupy fg[0] when
    `kitty @ ls` samples mid-hook.
    """
    for proc in fg_processes:
        cmd = proc.get("cmdline") or []
        if is_claude(cmd) or is_codex(cmd):
            return proc
    return None


def get_launch_command(cmdline: list[str]) -> str | None:
    """Determine the launch command for a window.

    Returns None for shells AND unrecognized foregrounds (transient commands
    like `kitten @ ls` shouldn't be re-executed on restore).
    For claude: normalizes argv[0] basename to 'claude', merges
    DEFAULT_CLAUDE_FLAGS in front of existing argv (deduped).
    For codex: preserves options; session selection is handled separately.
    For whitelisted commands: returns command verbatim with argv[0]
    normalized to its basename.
    """
    if is_shell(cmdline):
        return None
    if is_claude(cmdline):
        existing = list(cmdline[1:])
        merged = list(DEFAULT_CLAUDE_FLAGS)
        merged = [flag for flag in merged if flag not in existing]
        return shlex.join(["claude"] + merged + existing)
    if is_codex(cmdline):
        return shlex.join(["codex"] + list(cmdline[1:]))
    if is_restorable(cmdline):
        basename = cmdline[0].rsplit("/", 1)[-1]
        return shlex.join([basename] + list(cmdline[1:]))
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
        ai_window_count = sum(
            find_ai_proc(window.get("foreground_processes", [])) is not None
            for window in windows
        )

        print(
            f"[snapshot] Tab[{ti}] {title!r} ({len(windows)} windows)",
            file=sys.stderr,
        )

        lines.append(f"new_tab {title}")
        lines.append(f"layout {layout}")

        for i, window in enumerate(windows):
            cwd = window.get("cwd", "")
            fg = window.get("foreground_processes", [])

            # Prefer AI processes anywhere in fg (hooks can mask fg[0]).
            ai_proc = find_ai_proc(fg)
            if ai_proc is not None:
                cmdline = ai_proc.get("cmdline") or []
                ai_pid = ai_proc.get("pid")
                if is_claude(cmdline):
                    session_id = get_claude_session_id(ai_pid)
                    resumable = bool(session_id) and claude_session_has_log(cwd, session_id)
                else:
                    window_title = window.get("title") or (title if ai_window_count == 1 else "")
                    session_id = get_codex_session_id(ai_pid, cwd, cmdline, window_title)
                    resumable = bool(session_id)
            else:
                cmdline = fg[0].get("cmdline", []) if fg else []
                session_id = None
                resumable = False

            launch_cmd = get_launch_command(cmdline)
            if resumable:
                launch_cmd = resume_command(cmdline, session_id)

            if ai_proc is not None:
                agent = "claude" if is_claude(cmdline) else "codex"
                if resumable:
                    msg = f"{agent} session={session_id}"
                elif session_id:
                    msg = f"claude session={session_id} (idle, no jsonl → fresh restore)"
                else:
                    msg = f"{agent} (no session-id, fresh restore)"
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
