import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / 'tools'))
import jev_settings as settings
import jev_prompt_hook as hook


def test_live_switches_are_independent(tmp_path, monkeypatch):
    monkeypatch.setenv('JEV_SETTINGS_FILE', str(tmp_path / 'settings.json'))
    assert settings.read_settings() == settings.DEFAULTS
    settings.change('entry', False)
    assert settings.read_settings() == {'enabled': True, 'entry': False, 'print': True, 'hook': True}
    settings.change('print', False)
    settings.change('enabled', False)
    settings.change('enabled', True)
    assert settings.read_settings() == {'enabled': True, 'entry': False, 'print': False, 'hook': True}


def test_disabled_entry_never_calls_jev_then_reenables_live(tmp_path, monkeypatch):
    monkeypatch.setenv('JEV_SETTINGS_FILE', str(tmp_path / 'settings.json'))
    calls = []
    def judge(prompt):
        calls.append(prompt)
        return {'simple_request': .99, 'coding_task': .01}
    event = {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': 't', 'prompt': 'hello'}
    for key in ('entry', 'enabled'):
        settings.change(key, False)
        result = hook.handle(event, judge, state_root=tmp_path / 'states')
        assert calls == []
        assert 'disabled' in result['hookSpecificOutput']['additionalContext']
        settings.change(key, True)
    result = hook.handle(event, judge, state_root=tmp_path / 'states')
    assert calls == ['hello']
    assert 'jev-dispatch' in result['hookSpecificOutput']['additionalContext']


def test_control_command_consumed_without_model_even_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv('JEV_SETTINGS_FILE', str(tmp_path / 'settings.json'))
    def forbidden(_):
        raise AssertionError('control command must not call Jev')
    for command in ('jev off', 'jev entry off', 'jev print off', 'jev status', 'jev on'):
        result = hook.handle({'hook_event_name': 'UserPromptSubmit', 'prompt': command}, forbidden)
        assert result['decision'] == 'block'
        assert 'Jev 总开关:' in result['reason']
    assert settings.read_settings() == {'enabled': True, 'entry': False, 'print': False, 'hook': True}
    result = hook.handle({'hook_event_name': 'UserPromptSubmit', 'prompt': 'jev print invalid'}, forbidden)
    assert result['decision'] == 'block'
    assert settings.read_settings()['print'] is False


def test_cli_and_plain_input_share_live_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('JEV_SETTINGS_FILE', str(tmp_path / 'settings.json'))
    assert settings.main(['print', 'off']) == 0
    assert '判断打印: off' in capsys.readouterr().out
    body = 'jev entry off'
    result = hook.handle({'hook_event_name': 'UserPromptSubmit', 'prompt': body})
    assert result['decision'] == 'block'
    assert settings.read_settings() == {'enabled': True, 'entry': False, 'print': False, 'hook': True}
