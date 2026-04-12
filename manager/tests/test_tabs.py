"""Tests for claude-manager tabs subcommand."""

import dataclasses
import json
import subprocess as sp
import time

import pytest

from claude_manager.tabs import registry as registry_module
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
        assert "42" in data
        assert data["42"]["tab_title"] == "my-tab"
        assert data["42"]["status"] == "working"

    def test_filters_out_non_dict_values(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        p.write_text(json.dumps({
            "valid": {"window_id": "1", "kitty_socket": "unix:@m"},
            "bogus_string": "not a dict",
            "bogus_list": [1, 2, 3],
        }))
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        data = load_registry()
        assert "valid" in data
        assert "bogus_string" not in data
        assert "bogus_list" not in data


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
