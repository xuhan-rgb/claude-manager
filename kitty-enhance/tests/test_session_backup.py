"""Targeted checks for the periodic backup command, without opening Kitty."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/session-backup.py"
SPEC = importlib.util.spec_from_file_location("session_backup", SCRIPT)
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def window(window_id=2, pane_id=22, cwd="/project"):
    return {"id": window_id, "tabs": [{"title": "work", "layout": "stack", "windows": [
        {"id": pane_id, "cwd": cwd, "foreground_processes": [{"cmdline": ["bash"]}]},
    ]}]}


@pytest.fixture
def environment(monkeypatch):
    calls = []
    monkeypatch.setenv("KITTY_WINDOW_ID", "22")
    monkeypatch.setenv("KITTY_PID", "123")
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:@test")
    monkeypatch.setattr(backup, "process_start", lambda pid: "start-token")
    monkeypatch.setattr(backup, "kitty_windows", lambda socket: [window(1, 11, "/other"), window()])
    monkeypatch.setattr(backup.subprocess, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    return calls


def test_save_overwrites_only_latest(tmp_path):
    backup.save_backup(window(), tmp_path, "work")
    backup.save_backup(window(cwd="/changed"), tmp_path, "work")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["work.meta.json", "work.session"]
    assert "/changed" in (tmp_path / "work.session").read_text()
    assert "/project" not in (tmp_path / "work.session").read_text()
    meta = json.loads((tmp_path / "work.meta.json").read_text())
    assert (meta["name"], meta["tabs"], meta["windows"], meta["automatic"]) == ("work", 1, 1, True)


def test_generation_failure_preserves_previous_backup(tmp_path, monkeypatch):
    original = backup.save_backup(window(), tmp_path, "work").read_text()
    def fail(*args, **kwargs):
        raise ValueError("snapshot failed")
    monkeypatch.setattr(backup.snapshot, "generate_session", fail)
    with pytest.raises(ValueError):
        backup.save_backup(window(), tmp_path, "work")
    assert (tmp_path / "work.session").read_text() == original


def test_selects_current_os_window():
    target = window()
    assert backup.select_window([window(1, 11), target], "22") is target
    with pytest.raises(ValueError):
        backup.select_window([target], "missing")


def test_start_saves_now_and_schedules_current_window(environment, tmp_path, capsys):
    backup.start_backup(SimpleNamespace(interval="10m", name="work", once=False), tmp_path)
    commands = environment
    timer = next(command for command in commands if command[0] == "systemd-run")
    assert "--on-active=10m" in timer
    assert "--on-unit-active=10m" in timer
    assert timer[timer.index("--os-window-id") + 1] == "2"
    assert timer[timer.index("--name") + 1] == "work"
    assert "/other" not in (tmp_path / "work.session").read_text()
    output = capsys.readouterr().out
    assert "周期保存已开启" in output
    assert "后台执行，不占用当前终端" in output
    assert "tab-restore work" in output
    assert "tab-backup status" in output


def test_once_does_not_change_timer(environment, tmp_path):
    backup.start_backup(SimpleNamespace(interval="10m", name="work", once=True), tmp_path)
    assert environment == []
    assert json.loads((tmp_path / "work.meta.json").read_text())["automatic"] is False


@pytest.mark.parametrize("interval", ["0m", "-1m", "abc", "1m;touch /tmp/bad"])
def test_invalid_interval_never_changes_schedule(environment, tmp_path, interval):
    with pytest.raises(ValueError):
        backup.start_backup(SimpleNamespace(interval=interval, name="work", once=False), tmp_path)
    assert environment == []
    assert not (tmp_path / "work.session").exists()


def test_failed_snapshot_does_not_stop_previous_timer(environment, tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "kitty_windows", lambda socket: [])
    with pytest.raises(ValueError):
        backup.start_backup(SimpleNamespace(interval="10m", name="work", once=False), tmp_path)
    assert environment == []


def test_missing_session_has_explicit_warning(tmp_path, monkeypatch, capsys):
    data = window()
    data["tabs"][0]["windows"][0]["foreground_processes"] = [{"cmdline": ["codex"], "pid": 999}]
    monkeypatch.setattr(backup.snapshot, "get_codex_session_id", lambda *args: None)
    backup.save_backup(data, tmp_path, "work")
    assert "1 个 AI 窗口未保存可恢复的对话 ID" in capsys.readouterr().out


def test_timer_updates_same_file_and_skips_when_kitty_exits(environment, tmp_path, monkeypatch):
    args = [str(SCRIPT), "run", "--socket", "unix:@test", "--os-window-id", "2",
            "--kitty-pid", "123", "--kitty-start", "start-token", "--directory", str(tmp_path), "--name", "work"]
    monkeypatch.setattr(sys, "argv", args)
    assert backup.main() == 0
    assert (tmp_path / "work.session").exists()
    previous = (tmp_path / "work.session").read_text()
    monkeypatch.setattr(backup, "process_start", lambda pid: "different-process")
    assert backup.main() == 0
    assert environment == []
    assert (tmp_path / "work.session").read_text() == previous


def test_restore_latest_automatic_snapshot(environment, tmp_path, monkeypatch):
    backup.save_backup(window(), tmp_path, "first")
    backup.save_backup(window(), tmp_path, "latest")
    meta_path = tmp_path / "first.meta.json"
    meta = json.loads(meta_path.read_text())
    meta["saved_at"] = "2020-01-01T00:00:00"
    meta_path.write_text(json.dumps(meta))
    backup.save_backup(window(), tmp_path, "manual", automatic=False)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "restore", "--directory", str(tmp_path)])
    assert backup.main() == 0
    assert environment[-1] == ["kitty", "--session", str(tmp_path / "latest.session"), "--detach"]


def test_process_start_reads_real_pid():
    assert backup.process_start(str(os.getpid())).isdigit()


def test_cli_default_name_and_period(environment, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "start", "--directory", str(tmp_path)])
    assert backup.main() == 0
    assert (tmp_path / "auto.session").exists()
    timer = next(command for command in environment if command[0] == "systemd-run")
    assert "--on-unit-active=10m" in timer



def test_closed_os_window_skips_save_and_preserves_timer(environment, tmp_path, monkeypatch, capsys):
    backup.save_backup(window(), tmp_path, "work")
    previous = (tmp_path / "work.session").read_text()
    monkeypatch.setattr(backup, "kitty_windows", lambda socket: [window(1, 11)])
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "run", "--socket", "unix:@test",
        "--os-window-id", "2", "--kitty-pid", "123", "--kitty-start", "start-token",
        "--directory", str(tmp_path), "--name", "work"])
    assert backup.main() == 0
    assert environment == []
    assert (tmp_path / "work.session").read_text() == previous
    assert "后台定时任务保留" in capsys.readouterr().out



def test_restore_starts_local_codex_daemon_before_kitty(environment, tmp_path):
    path = tmp_path / "work.session"
    path.write_text("new_tab work\nlaunch --cwd /project codex resume thread-id --remote unix:///tmp/codex.sock\n")
    backup.restore_session(path)
    assert environment == [
        ["codex", "app-server", "daemon", "start"],
        ["kitty", "--session", str(path), "--detach"],
    ]


@pytest.mark.parametrize("command", [
    "claude --resume thread-id", "codex resume thread-id",
    "codex resume thread-id --remote wss://example.test",
])
def test_restore_without_local_codex_daemon_does_not_start_it(environment, tmp_path, command):
    path = tmp_path / "work.session"
    path.write_text("launch --cwd /project " + command + "\n")
    backup.restore_session(path)
    assert environment == [["kitty", "--session", str(path), "--detach"]]


def test_daemon_failure_prevents_restore(tmp_path, monkeypatch):
    path = tmp_path / "work.session"
    path.write_text("launch codex --remote=unix:///tmp/codex.sock\n")
    calls = []
    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(backup.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        backup.restore_session(path)
    assert calls == [["codex", "app-server", "daemon", "start"]]



@pytest.mark.parametrize("action", ["tab-restore work", "tab-backup restore"])
@pytest.mark.parametrize("daemon_exit", [0, 42])
def test_restore_cli_daemon_order_and_failure(tmp_path, action, daemon_exit):
    directory = tmp_path / "saved"
    directory.mkdir()
    path = directory / "work.session"
    path.write_text("new_tab Bob's project\nlaunch --cwd '/my project' codex resume thread-id --remote=unix:///tmp/codex.sock\nlaunch claude --resume claude-id\n")
    (directory / "work.meta.json").write_text(json.dumps({
        "name": "work", "automatic": True, "saved_at": "2026-10-11T00:00:00",
    }))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "calls.jsonl"
    for executable in ("codex", "kitty"):
        script = fake_bin / executable
        script.write_text(
            "#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\n"
            "with Path(os.environ['RESTORE_CALL_LOG']).open('a') as f:\n"
            " f.write(json.dumps({'program': Path(sys.argv[0]).name, 'args': sys.argv[1:], 'window_id': os.environ.get('KITTY_WINDOW_ID')}) + '\\n')\n"
            + (f"sys.exit({daemon_exit})\n" if executable == "codex" else "")
        )
        script.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": str(fake_bin) + os.pathsep + env["PATH"],
        "KITTY_ENHANCE_SESSION_DIR": str(directory),
        "KITTY_WINDOW_ID": "22", "KITTY_LISTEN_ON": "unix:@test",
        "RESTORE_CALL_LOG": str(log),
    })
    functions = SCRIPT.parent.parent / "shell-functions.sh"
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; ' + action, "test", str(functions)],
        env=env, capture_output=True, text=True,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls[0] == {"program": "codex", "args": ["app-server", "daemon", "start"], "window_id": None}
    if daemon_exit:
        assert result.returncode != 0
        assert len(calls) == 1
        assert "已恢复" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert calls[1] == {"program": "kitty", "args": ["--session", str(path), "--detach"], "window_id": "22"}
        assert "Codex daemon 已就绪" in result.stdout
