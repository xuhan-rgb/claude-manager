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
