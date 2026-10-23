import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
import jev_hook_control as control
import jev_prompt_hook as hook
import jev_settings


def config_with_other_hook():
    return {"hooks": {"UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": "echo keep"},
                   {"type": "command", "command": "/x/jev_prompt_hook.py"}]}
    ], "SessionStart": [{"hooks": [{"type": "command", "command": "echo start"}]}]}}


def test_hook_off_removes_only_jev_hook_and_on_restores_it(tmp_path, monkeypatch):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps(config_with_other_hook()))
    monkeypatch.setenv("JEV_HOOKS_FILE", str(hooks))
    monkeypatch.setenv("JEV_SETTINGS_FILE", str(tmp_path / "settings.json"))
    control.apply("off")
    data = json.loads(hooks.read_text())
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"] == [
        {"type": "command", "command": "echo keep"}
    ]
    assert data["hooks"]["SessionStart"]
    assert jev_settings.read_settings()["hook"] is False
    control.apply("on")
    assert control.installed(hooks)
    assert jev_settings.read_settings()["hook"] is True


def test_disabled_cached_hook_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_SETTINGS_FILE", str(tmp_path / "settings.json"))
    jev_settings.change("hook", False)
    result = hook.handle({"hook_event_name": "UserPromptSubmit", "prompt": "hello"},
                         lambda _: (_ for _ in ()).throw(AssertionError("no Jev")))
    assert result == {}


def test_status_reports_installation(tmp_path, monkeypatch):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps({"hooks": {"UserPromptSubmit": []}}))
    monkeypatch.setenv("JEV_HOOKS_FILE", str(hooks))
    monkeypatch.setenv("JEV_SETTINGS_FILE", str(tmp_path / "settings.json"))
    assert control.apply("status")["installed"] is False
