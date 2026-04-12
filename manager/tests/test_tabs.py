"""Tests for claude-manager tabs subcommand."""

import time

from claude_manager.tabs.registry import TerminalInfo


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
        import dataclasses
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
        try:
            info.status = "working"
            raised = False
        except dataclasses.FrozenInstanceError:
            raised = True
        assert raised, "TerminalInfo must be frozen"


import json

from claude_manager.tabs import registry as registry_module
from claude_manager.tabs.registry import load_registry


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
