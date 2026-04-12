"""Tests for claude-manager tabs subcommand."""

import dataclasses
import json
import subprocess as sp
import sys
import time

import pytest

from claude_manager.tabs import cli as cli_module
from claude_manager.tabs import kitty as kitty_module
from claude_manager.tabs import registry as registry_module
from claude_manager.tabs.cli import format_time_ago, run
from claude_manager.tabs.kitty import focus_window
from claude_manager.tabs.registry import (
    TerminalInfo,
    list_alive_terminals,
    load_registry,
)


class TestTerminalInfo:
    """TerminalInfo dataclass tests."""

    def test_project_name_from_cwd(self):
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="my-tab",
            cwd="/home/user/my-project",
            status="idle",
            agent_kind="claude",
            last_activity=0.0,
            registered_at=0.0,
        )
        assert info.project_name == "my-project"

    def test_project_name_fallback_to_cwd_when_empty(self):
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="my-tab",
            cwd="",
            status="idle",
            agent_kind="claude",
            last_activity=0.0,
            registered_at=0.0,
        )
        assert info.project_name == ""

    def test_idle_seconds_computed_from_now(self):
        now = time.time()
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="my-tab",
            cwd="/",
            status="idle",
            agent_kind="claude",
            last_activity=now - 120,
            registered_at=now - 200,
        )
        assert 119 <= info.idle_seconds <= 122

    def test_frozen_dataclass_rejects_mutation(self):
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="t",
            cwd="/",
            status="idle",
            agent_kind="claude",
            last_activity=0.0,
            registered_at=0.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.status = "working"  # type: ignore[misc]


class TestLoadRegistry:
    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            registry_module, "REGISTRY_PATH", tmp_path / "nothing.json"
        )
        assert load_registry() == {}

    def test_returns_empty_when_json_corrupt(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        p.write_text("not valid json")
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        assert load_registry() == {}

    def test_returns_empty_when_top_level_not_dict(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        p.write_text("[]")
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        assert load_registry() == {}

    def test_returns_parsed_dict_when_valid(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        payload = {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "my-tab",
                "cwd": "/home/user/proj",
                "status": "working",
                "agent_kind": "claude",
                "agent_name": "Claude",
                "registered_at": 100.0,
                "last_activity": 200.0,
            }
        }
        p.write_text(json.dumps(payload))
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        data = load_registry()
        assert list(data) == ["42@mykitty-1"]
        assert data["42@mykitty-1"]["tab_title"] == "my-tab"
        assert data["42@mykitty-1"]["status"] == "working"
        assert data["42@mykitty-1"]["terminal_id"] == "42@mykitty-1"

    def test_filters_out_non_dict_values(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        p.write_text(json.dumps({
            "valid": {"window_id": "1", "kitty_socket": "unix:@m"},
            "bogus_string": "not a dict",
            "bogus_list": [1, 2, 3],
        }))
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        data = load_registry()
        assert list(data) == ["1@m"]
        assert "bogus_string" not in data
        assert "bogus_list" not in data

    def test_normalizes_legacy_window_id_keys(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        payload = {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-9",
                "tab_title": "legacy",
                "cwd": "/tmp",
                "status": "working",
                "last_activity": 123.0,
                "registered_at": 120.0,
            }
        }
        p.write_text(json.dumps(payload))
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        data = load_registry()
        assert list(data) == ["42@mykitty-9"]
        assert data["42@mykitty-9"]["terminal_id"] == "42@mykitty-9"


class TestGetAliveWindows:
    def test_parses_kitten_ls_output(self, monkeypatch):
        fake_stdout = json.dumps([
            {
                "tabs": [
                    {
                        "title": "tab-one",
                        "windows": [
                            {"id": 10, "cwd": "/home/a"},
                            {"id": 11, "cwd": "/home/b"},
                        ],
                    },
                    {
                        "title": "tab-two",
                        "windows": [
                            {"id": 20, "cwd": "/home/c"},
                        ],
                    },
                ]
            }
        ])

        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 0, fake_stdout, "")

        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        result = registry_module._get_alive_windows("unix:@mykitty-1")
        assert set(result.keys()) == {"10", "11", "20"}
        assert result["10"]["tab_title"] == "tab-one"
        assert result["20"]["tab_title"] == "tab-two"
        assert result["10"]["cwd"] == "/home/a"

    def test_returns_empty_on_nonzero_exit(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 1, "", "connection refused")
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_returns_empty_on_timeout(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd=cmd, timeout=5)
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_returns_empty_when_kitten_missing(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("kitten")
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_returns_empty_on_malformed_json(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 0, "not-json", "")
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_passes_socket_to_kitten(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return sp.CompletedProcess(cmd, 0, "[]", "")

        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        registry_module._get_alive_windows("unix:@mykitty-999")
        assert captured["cmd"] == [
            "kitten", "@", "--to", "unix:@mykitty-999", "ls"
        ]
        assert captured["kwargs"].get("timeout") == registry_module.KITTEN_LS_TIMEOUT


def _write_registry(path, entries):
    path.write_text(json.dumps(entries))


class TestListAliveTerminals:
    def test_empty_when_registry_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            registry_module, "REGISTRY_PATH", tmp_path / "absent.json"
        )
        assert list_alive_terminals() == []

    def test_filters_out_dead_windows(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "alive-tab-stale",
                "cwd": "/home/a",
                "status": "working",
                "agent_kind": "claude",
                "registered_at": 100.0,
                "last_activity": 200.0,
            },
            "99": {
                "window_id": "99",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "dead-tab",
                "cwd": "/home/b",
                "status": "idle",
                "agent_kind": "claude",
                "registered_at": 100.0,
                "last_activity": 150.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows",
            lambda socket: {
                "42": {"tab_title": "alive-tab-fresh", "cwd": "/home/a"},
            },
        )
        result = list_alive_terminals()
        assert len(result) == 1
        assert result[0].window_id == "42"

    def test_live_tab_title_overrides_stale_registry(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "stale-name",
                "cwd": "/home/a",
                "status": "working",
                "agent_kind": "claude",
                "registered_at": 100.0,
                "last_activity": 200.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows",
            lambda socket: {
                "42": {"tab_title": "fresh-name", "cwd": "/home/a"},
            },
        )
        result = list_alive_terminals()
        assert result[0].tab_title == "fresh-name"

    def test_sorted_by_last_activity_desc(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "1": {
                "window_id": "1", "kitty_socket": "unix:@mykitty-1",
                "tab_title": "old", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 100.0,
            },
            "2": {
                "window_id": "2", "kitty_socket": "unix:@mykitty-1",
                "tab_title": "middle", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 500.0,
            },
            "3": {
                "window_id": "3", "kitty_socket": "unix:@mykitty-1",
                "tab_title": "newest", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 900.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows",
            lambda socket: {
                "1": {"tab_title": "old", "cwd": "/"},
                "2": {"tab_title": "middle", "cwd": "/"},
                "3": {"tab_title": "newest", "cwd": "/"},
            },
        )
        result = list_alive_terminals()
        assert [t.window_id for t in result] == ["3", "2", "1"]

    def test_handles_multiple_sockets(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "1": {
                "window_id": "1", "kitty_socket": "unix:@mykitty-A",
                "tab_title": "a", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 100.0,
            },
            "2": {
                "window_id": "2", "kitty_socket": "unix:@mykitty-B",
                "tab_title": "b", "cwd": "/", "status": "idle",
                "agent_kind": "codex", "registered_at": 0.0,
                "last_activity": 200.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)

        socket_calls = []
        def fake_alive(socket):
            socket_calls.append(socket)
            return {
                "unix:@mykitty-A": {"1": {"tab_title": "a", "cwd": "/"}},
                "unix:@mykitty-B": {"2": {"tab_title": "b", "cwd": "/"}},
            }[socket]

        monkeypatch.setattr(registry_module, "_get_alive_windows", fake_alive)
        result = list_alive_terminals()
        assert len(result) == 2
        assert len(socket_calls) == 2
        assert set(socket_calls) == {"unix:@mykitty-A", "unix:@mykitty-B"}

    def test_keeps_same_window_id_from_different_sockets(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "1@mykitty-A": {
                "terminal_id": "1@mykitty-A",
                "window_id": "1",
                "kitty_socket": "unix:@mykitty-A",
                "tab_title": "a",
                "cwd": "/proj/a",
                "status": "working",
                "agent_kind": "claude",
                "registered_at": 100.0,
                "last_activity": 200.0,
            },
            "1@mykitty-B": {
                "terminal_id": "1@mykitty-B",
                "window_id": "1",
                "kitty_socket": "unix:@mykitty-B",
                "tab_title": "b",
                "cwd": "/proj/b",
                "status": "waiting",
                "agent_kind": "codex",
                "registered_at": 100.0,
                "last_activity": 300.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)

        monkeypatch.setattr(
            registry_module,
            "_get_alive_windows",
            lambda socket: {"1": {"tab_title": socket[-1].lower(), "cwd": "/"}},
        )

        result = list_alive_terminals()
        assert [t.terminal_id for t in result] == ["1@mykitty-B", "1@mykitty-A"]
        assert [t.window_id for t in result] == ["1", "1"]

    def test_skips_entries_without_socket(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "42": {
                "window_id": "42", "kitty_socket": "",
                "tab_title": "t", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 100.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows", lambda s: {}
        )
        assert list_alive_terminals() == []

    def test_handles_malformed_timestamps(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "t",
                "cwd": "/",
                "status": "idle",
                "agent_kind": "claude",
                "registered_at": "not-a-number",
                "last_activity": None,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows",
            lambda s: {"42": {"tab_title": "t", "cwd": "/"}},
        )
        result = list_alive_terminals()
        assert len(result) == 1
        assert result[0].last_activity == 0.0
        assert result[0].registered_at == 0.0


class TestFocusWindow:
    def test_success_invokes_kitten_with_correct_args(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "42")
        assert ok is True
        assert err == ""
        assert captured["cmd"] == [
            "kitten", "@", "--to", "unix:@mykitty-1",
            "focus-window", "--match", "id:42",
        ]
        assert captured["kwargs"].get("timeout") == kitty_module.FOCUS_TIMEOUT

    def test_failure_returns_stderr(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 1, "", "no matching window")

        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "99")
        assert ok is False
        assert "no matching window" in err

    def test_failure_generic_message_when_stderr_empty(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 2, "", "")

        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "99")
        assert ok is False
        assert err  # non-empty fallback message

    def test_timeout(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd=cmd, timeout=3)

        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "42")
        assert ok is False
        assert "timed out" in err

    def test_kitten_not_found(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("kitten")

        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "42")
        assert ok is False
        assert "not found" in err


# --- CLI Tests (Tasks 6-8) ---


def _make_terminal(**overrides) -> TerminalInfo:
    defaults = dict(
        window_id="42",
        socket="unix:@mykitty-1",
        tab_title="my-tab",
        cwd="/home/user/my-project",
        status="working",
        agent_kind="claude",
        last_activity=time.time() - 30,
        registered_at=time.time() - 300,
    )
    defaults.update(overrides)
    return TerminalInfo(**defaults)


class TestFormatTimeAgo:
    def test_recent(self):
        assert format_time_ago(0) == "刚刚"
        assert format_time_ago(59) == "刚刚"

    def test_minutes(self):
        assert format_time_ago(60) == "1分钟前"
        assert format_time_ago(180) == "3分钟前"
        assert format_time_ago(3599) == "59分钟前"

    def test_hours(self):
        assert format_time_ago(3600) == "1小时前"
        assert format_time_ago(7200) == "2小时前"

    def test_days(self):
        assert format_time_ago(86400) == "1天前"
        assert format_time_ago(172800) == "2天前"


class TestListCommand:
    def test_empty_list_shows_hint(self, capsys, monkeypatch):
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])
        rc = run(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "没有活跃的终端" in out
        assert "/tmp/feishu-bridge/registry.json" in out

    def test_list_shows_columns(self, capsys, monkeypatch):
        t1 = _make_terminal(window_id="42", tab_title="first-tab")
        t2 = _make_terminal(
            window_id="18",
            tab_title="second-tab",
            status="waiting",
            cwd="/home/user/other-proj",
            last_activity=time.time() - 250,
        )
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [t1, t2])
        rc = run(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "42" in out
        assert "18" in out
        assert "first-tab" in out
        assert "second-tab" in out
        assert "my-project" in out
        assert "other-proj" in out
        assert "共 2 个活跃终端" in out

    def test_list_includes_header_row(self, capsys, monkeypatch):
        monkeypatch.setattr(
            cli_module, "list_alive_terminals", lambda: [_make_terminal()]
        )
        rc = run(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        for col in ("ID", "TAB", "PROJECT", "AGENT", "STATUS", "IDLE"):
            assert col in out

    def test_active_flag_filters_completed_and_idle(self, capsys, monkeypatch):
        working = _make_terminal(window_id="1", status="working")
        waiting = _make_terminal(window_id="2", status="waiting")
        idle = _make_terminal(window_id="3", status="idle")
        completed = _make_terminal(window_id="4", status="completed")
        monkeypatch.setattr(
            cli_module,
            "list_alive_terminals",
            lambda: [working, waiting, idle, completed],
        )
        rc = run(["list", "--active"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "共 2 个活跃终端" in out

    def test_json_flag_emits_parseable_json(self, capsys, monkeypatch):
        t = _make_terminal(window_id="42", tab_title="hello")
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [t])
        rc = run(["list", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["window_id"] == "42"
        assert data[0]["terminal_id"] == "42@mykitty-1"
        assert data[0]["tab_title"] == "hello"
        assert data[0]["project_name"] == "my-project"
        assert "idle_seconds" in data[0]


class TestFocusCommand:
    def test_focus_success_prints_tab_title(self, capsys, monkeypatch):
        monkeypatch.setattr(
            cli_module,
            "list_alive_terminals",
            lambda: [_make_terminal(window_id="42", tab_title="my-tab")],
        )
        monkeypatch.setattr(cli_module, "focus_window", lambda s, w: (True, ""))
        rc = run(["focus", "42"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "my-tab" in out
        assert "42" in out

    def test_focus_not_in_registry_prints_error_and_alive_list(
        self, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli_module, "load_registry", lambda: {})
        monkeypatch.setattr(
            cli_module,
            "list_alive_terminals",
            lambda: [_make_terminal(window_id="42", tab_title="something")],
        )
        rc = run(["focus", "99"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "未找到" in err
        assert "99" in err
        assert "42" in err
        assert "something" in err

    def test_focus_not_in_registry_with_empty_alive_list(
        self, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli_module, "load_registry", lambda: {})
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])
        rc = run(["focus", "99"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "未找到" in err

    def test_focus_kitten_failure_propagates_error(self, capsys, monkeypatch):
        monkeypatch.setattr(
            cli_module,
            "list_alive_terminals",
            lambda: [_make_terminal(window_id="42", tab_title="my-tab")],
        )
        monkeypatch.setattr(
            cli_module, "focus_window", lambda s, w: (False, "no matching window")
        )
        rc = run(["focus", "42"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "no matching window" in err

    def test_focus_rejects_ambiguous_window_id(self, capsys, monkeypatch):
        t1 = _make_terminal(window_id="42", terminal_id="42@mykitty-a", tab_title="alpha")
        t2 = _make_terminal(window_id="42", terminal_id="42@mykitty-b", tab_title="beta")
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [t1, t2])
        monkeypatch.setattr(cli_module, "load_registry", lambda: {})

        rc = run(["focus", "42"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "不唯一" in err
        assert "42@mykitty-a" in err
        assert "42@mykitty-b" in err


class TestMainCliIntegration:
    """Test that 'claude-manager tabs' routes to tabs.cli.run via main()."""

    def test_main_routes_tabs_list(self, capsys, monkeypatch):
        from claude_manager import cli as main_cli

        monkeypatch.setattr(sys, "argv", ["claude-manager", "tabs", "list"])
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])

        rc = main_cli.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "没有活跃的终端" in out

    def test_main_routes_tabs_focus_error(self, capsys, monkeypatch):
        from claude_manager import cli as main_cli

        monkeypatch.setattr(
            sys, "argv", ["claude-manager", "tabs", "focus", "99"]
        )
        monkeypatch.setattr(cli_module, "load_registry", lambda: {})
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])

        rc = main_cli.main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "未找到" in err
