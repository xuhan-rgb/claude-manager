"""Tests for session-snapshot.py"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import sqlite3

import pytest
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
        """A tab with one bash window should produce new_tab + layout + launch --cwd."""
        ls_json = make_kitty_ls([
            make_tab("myterm", "stack", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab myterm" in output
        assert "layout stack" in output
        assert "launch --cwd /home/user" in output
        # Shell windows should NOT have an explicit launch command
        assert len([l for l in output.splitlines() if l.startswith("launch")]) == 1

    def test_cwd_with_spaces(self):
        """Paths with spaces should be quoted in launch directives."""
        ls_json = make_kitty_ls([
            make_tab("t", "stack", [
                make_window("/home/user/my project", ["/bin/bash"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "launch --cwd '/home/user/my project'" in output

    def test_claude_tab(self):
        """A tab running claude should produce launch claude."""
        ls_json = make_kitty_ls([
            make_tab("Claude Code", "tall", [
                make_window("/mnt/data/project", ["claude", "--dangerously-skip-permissions"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab Claude Code" in output
        assert "launch --cwd /mnt/data/project claude" in output
        assert " claude" in output
        # Preserve launch flags.
        assert "--dangerously-skip-permissions" in output


class TestMultiWindow:
    def test_tab_with_claude_and_shells(self):
        """A tab with claude + 2 shells: each window has its own cwd."""
        ls_json = make_kitty_ls([
            make_tab("work", "tall", [
                make_window("/mnt/data/proj", ["claude"]),
                make_window("/mnt/data", ["/bin/bash"]),
                make_window("/home/user", ["/bin/zsh"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        lines = output.strip().split("\n")
        # First window: explicit cwd and Claude launch
        assert "launch --cwd /mnt/data/proj claude" in output
        assert " claude" in output
        # Extra shell windows use launch --type=window
        type_window_lines = [l for l in lines if "--type=window" in l]
        assert len(type_window_lines) == 2

    def test_non_shell_command(self):
        """Unrecognized transient commands should restore as a shell."""
        ls_json = make_kitty_ls([
            make_tab("files", "stack", [
                make_window("/home/user", ["nautilus", "/home/user/Documents"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "launch --cwd /home/user" in output
        assert "nautilus" not in output


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
        assert "launch --cwd /tmp" in output
        assert len([l for l in output.splitlines() if l.startswith("launch")]) == 1

    def test_empty_input(self):
        """Empty kitty @ ls output should return a safe message."""
        output = run_snapshot("[]")
        assert "No windows found" in output

    def test_name_argument(self):
        """Session name should appear in the header comment."""
        ls_json = make_kitty_ls([
            make_tab("t", "stack", [
                make_window("/tmp", ["/bin/bash"]),
            ]),
        ])
        result = subprocess.run(
            [sys.executable, SCRIPT, "mywork"],
            input=ls_json,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Session: mywork" in result.stdout

    def test_unicode_tab_title(self):
        """Unicode in tab title should be preserved."""
        ls_json = make_kitty_ls([
            make_tab("✳ 调试面板", "tall", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab ✳ 调试面板" in output


SPEC = importlib.util.spec_from_file_location("session_snapshot", SCRIPT)
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


@pytest.fixture
def session_env(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(snapshot, "CLAUDE_SESSIONS_DIR", tmp_path / ".claude/sessions")
    monkeypatch.setattr(snapshot, "PROC_ROOT", tmp_path / "proc", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setattr(snapshot, "DEFAULT_CLAUDE_FLAGS", [])
    return tmp_path


def snapshot_window(cmdline, pid=123, cwd="/project"):
    window = make_window(cwd, cmdline)
    window["foreground_processes"][0]["pid"] = pid
    return [{"tabs": [make_tab("AI", "stack", [window])]}]


def claude_session(root, pid, session_id, cwd="/project", log=True):
    sessions = root / ".claude/sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{pid}.json").write_text(json.dumps({"sessionId": session_id, "cwd": cwd}))
    if log:
        path = root / ".claude/projects" / cwd.replace("/", "-").replace(".", "-") / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def codex_process(root, pid, session_id, cwd="/project", daemon=False):
    proc = root / "proc" / str(pid)
    (proc / "fd").mkdir(parents=True, exist_ok=True)
    (proc / "cmdline").write_bytes(b"codex\0app-server\0" if daemon else b"codex\0")
    path = root / ".codex/sessions" / f"rollout-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": session_id, "cwd": cwd}}) + "\n")
    (proc / "fd" / session_id).symlink_to(path)


def test_claude_saves_current_id_not_original_resume(session_env):
    claude_session(session_env, 123, "current")
    output = snapshot.generate_session(snapshot_window(["claude", "--resume", "old", "--continue"]))
    assert "claude --resume current" in output
    assert "old" not in output
    assert "--continue" not in output


def test_claude_idle_does_not_resume(session_env):
    claude_session(session_env, 123, "idle", log=False)
    output = snapshot.generate_session(snapshot_window(["claude"]))
    assert " claude" in output
    assert "--resume" not in output


def test_claude_hook_does_not_mask_process(session_env):
    claude_session(session_env, 123, "current")
    data = snapshot_window(["claude"])
    data[0]["tabs"][0]["windows"][0]["foreground_processes"].insert(0, {"cmdline": ["bash", "hook.sh"]})
    assert "claude --resume current" in snapshot.generate_session(data)


def test_codex_saves_exact_process_session_same_cwd(session_env):
    codex_process(session_env, 123, "first")
    codex_process(session_env, 456, "second")
    assert "codex resume first" in snapshot.generate_session(snapshot_window(["/usr/bin/codex"]))
    assert "codex resume second" in snapshot.generate_session(snapshot_window(["codex"], pid=456))


def test_codex_replaces_last_resume_and_preserves_quoted_config(session_env):
    codex_process(session_env, 123, "current")
    output = snapshot.generate_session(snapshot_window(["codex", "-c", 'model="my model"', "resume", "--last"]))
    command = next(l for l in output.splitlines() if l.startswith("launch"))
    assert shlex.split(command)[3:] == ["codex", "resume", "current", "-c", 'model="my model"']


def test_codex_local_daemon_unique_cwd(session_env):
    codex_process(session_env, 999, "current", daemon=True)
    codex_process(session_env, 999, "other", cwd="/other", daemon=True)
    output = snapshot.generate_session(snapshot_window(["codex", "--remote", "unix:///tmp/server.sock"]))
    assert "codex resume current --remote unix:///tmp/server.sock" in output


def test_codex_ambiguous_daemon_does_not_guess(session_env, capsys):
    codex_process(session_env, 999, "first", daemon=True)
    codex_process(session_env, 999, "second", daemon=True)
    output = snapshot.generate_session(snapshot_window(["codex", "--remote", "unix:///tmp/server.sock"]))
    assert "codex" in output
    assert "resume" not in output
    assert "no session-id" in capsys.readouterr().err


def test_codex_missing_session_restores_command(session_env):
    output = snapshot.generate_session(snapshot_window(["codex", "--no-alt-screen"]))
    assert "codex --no-alt-screen" in output
    assert "resume" not in output


@pytest.mark.parametrize("directory_args", [["-C", "/project"], ["--cd=/project"], ["-C/project"]])
def test_codex_daemon_uses_explicit_working_directory(session_env, directory_args):
    codex_process(session_env, 999, "current", daemon=True)
    output = snapshot.generate_session(snapshot_window(["codex", "--remote", "unix:///tmp/server.sock"] + directory_args, cwd="/shell"))
    assert "codex resume current" in output


def test_codex_hook_does_not_mask_process(session_env):
    codex_process(session_env, 123, "current")
    data = snapshot_window(["codex"])
    data[0]["tabs"][0]["windows"][0]["foreground_processes"].insert(0, {"cmdline": ["bash", "hook.sh"]})
    assert "codex resume current" in snapshot.generate_session(data)


def test_claude_resume_equals_and_repeated_option_values(session_env):
    claude_session(session_env, 123, "current")
    output = snapshot.generate_session(snapshot_window(["claude", "--resume=old", "--session-id", "old", "--model", "same", "--agent", "same"]))
    assert "--resume current" in output
    assert "old" not in output
    assert "--model same --agent same" in output



def test_tab_save_restore_round_trip(session_env):
    claude_session(session_env, 123, "claude-current")
    codex_process(session_env, 456, "codex-current")
    rollout = session_env / ".codex/sessions/rollout-codex-current.jsonl"
    # A real process owns the test rollout so the CLI exercises /proc lookup.
    holder = subprocess.Popen(
        [sys.executable, "-c", "import sys; f = open(sys.argv[1]); print('ready', flush=True); sys.stdin.read()", str(rollout)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        data = snapshot_window(["claude"])
        codex_window = make_window("/project", ["codex", "--no-alt-screen"])
        codex_window["foreground_processes"][0]["pid"] = holder.pid
        data[0]["tabs"][0]["windows"].append(codex_window)
        data[0]["id"] = 99
        data[0]["tabs"][0]["windows"][0]["id"] = 1
        fake_bin = session_env / "bin"
        fake_bin.mkdir()
        kitty = fake_bin / "kitty"
        kitty.write_text(
            "#!/usr/bin/env python3\nimport os, sys, json\nfrom pathlib import Path\n"
            "if sys.argv[-1] == 'ls': print(os.environ['SNAPSHOT_KITTY_JSON'])\n"
            "else: Path(os.environ['SNAPSHOT_RESTORE_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
        )
        kitty.chmod(0o755)
        env = os.environ.copy()
        env.update({
            "HOME": str(session_env), "CODEX_HOME": str(session_env / ".codex"),
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "KITTY_WINDOW_ID": "1", "CLAUDE_DEFAULT_FLAGS": "",
            "KITTY_ENHANCE_SESSION_DIR": str(session_env / "saved"),
            "SNAPSHOT_KITTY_JSON": json.dumps(data),
            "SNAPSHOT_RESTORE_ARGS": str(session_env / "restore.json"),
        })
        functions = Path(SCRIPT).parent.parent / "shell-functions.sh"
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; tab-save work --once && tab-restore work', "test", str(functions)],
            env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        saved = session_env / "saved/work.session"
        content = saved.read_text()
        assert "--resume claude-current" in content
        assert " claude " in content
        assert "codex resume codex-current --no-alt-screen" in content
        assert json.loads((session_env / "restore.json").read_text()) == ["--session", str(saved), "--detach"]
        assert json.loads((session_env / "saved/work.meta.json").read_text())["windows"] == 2
    finally:
        holder.communicate(timeout=5)



def codex_index(root, rows):
    db = root / ".codex/state_5.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE threads (id TEXT, cwd TEXT, name TEXT, title TEXT, rollout_path TEXT, archived INTEGER)")
    for session_id, name in rows:
        path = root / ".codex/sessions" / f"rollout-{session_id}.jsonl"
        connection.execute("INSERT INTO threads VALUES (?, ?, ?, ?, ?, 0)", (session_id, "/project", name, "greeting", str(path)))
    connection.commit()
    connection.close()


def test_codex_same_directory_matches_window_conversation_name(session_env):
    codex_process(session_env, 999, "english", daemon=True)
    codex_process(session_env, 999, "chinese", daemon=True)
    codex_index(session_env, [("english", "Respond to greeting"), ("chinese", "回应问候")])
    data = snapshot_window(["codex", "--remote", "unix:///tmp/server.sock"])
    data[0]["tabs"][0]["title"] = "回应问候 | project"
    output = snapshot.generate_session(data)
    assert "codex resume chinese" in output
    assert "resume english" not in output


def test_codex_name_lookup_does_not_require_open_rollout(session_env):
    codex_process(session_env, 999, "current", daemon=True)
    codex_index(session_env, [("current", "回应问候")])
    (session_env / "proc/999/fd/current").unlink()
    data = snapshot_window(["codex", "--remote", "unix:///tmp/server.sock"])
    data[0]["tabs"][0]["windows"][0]["title"] = "⠋ 回应问候 | project"
    assert "codex resume current" in snapshot.generate_session(data)


def test_codex_duplicate_names_still_do_not_guess(session_env):
    codex_process(session_env, 999, "first", daemon=True)
    codex_process(session_env, 999, "second", daemon=True)
    codex_index(session_env, [("first", "Same title"), ("second", "Same title")])
    data = snapshot_window(["codex", "--remote", "unix:///tmp/server.sock"])
    data[0]["tabs"][0]["windows"][0]["title"] = "Same title | project"
    assert "resume" not in snapshot.generate_session(data)
