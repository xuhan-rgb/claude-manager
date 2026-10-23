import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("jev_prompt_hook", TOOLS / "jev_prompt_hook.py")
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_SETTINGS_FILE", str(tmp_path / "settings.json"))


def event(prompt="hello", turn="turn-1"):
    return {"hook_event_name":"UserPromptSubmit", "session_id":"session-1",
            "turn_id":turn,"cwd":"/tmp", "prompt":prompt}


@pytest.mark.parametrize("prompt,scores,expected", [
    ("hello", {"simple_request":.97,"coding_task":.02}, "luna_ready"),
    ("write a bounded nms.py", {"simple_request":.9,"coding_task":.99}, "luna_ready"),
    ("redesign storage", {"simple_request":.1,"coding_task":.99}, "current_required"),
])
def test_every_input_reaches_jev(tmp_path,prompt,scores,expected):
    calls=[]
    def judge(value): calls.append(value); return scores
    result=hook.handle(event(prompt),judge,state_root=tmp_path)
    assert calls==[prompt]
    files=list(tmp_path.glob("*.json")); assert len(files)==1
    state=json.loads(files[0].read_text()); assert state["state"]==expected
    assert prompt not in result["systemMessage"]
    assert "问题:" in result["systemMessage"]
    if expected=="luna_ready": assert "jev-dispatch" in result["hookSpecificOutput"]["additionalContext"]


def test_same_turn_is_classified_once(tmp_path):
    calls=[]
    def judge(value): calls.append(value); return {"simple_request":.9,"coding_task":.01}
    first=hook.handle(event(),judge,state_root=tmp_path)
    second=hook.handle(event(),judge,state_root=tmp_path)
    assert len(calls)==1
    assert first==second


def test_provider_failure_and_invalid_scores_stay_current(tmp_path):
    def failing(_): raise RuntimeError("secret must not print")
    for index,judge in enumerate([failing,lambda _: {},lambda _: {"simple_request":float("nan"),"coding_task":0}]):
        result=hook.handle(event(turn=str(index)),judge,state_root=tmp_path)
        assert "当前会话" in result["systemMessage"]
        assert "secret must not print" not in str(result)
    assert all(json.loads(p.read_text())["state"]=="current_required" for p in tmp_path.glob("*.json"))


def test_worker_and_other_events_do_not_recurse(tmp_path,monkeypatch):
    def failing(_): raise AssertionError("must not call")
    assert hook.handle({"hook_event_name":"SubagentStart"},failing,state_root=tmp_path)=={}
    monkeypatch.setenv("JEV_SCRIPT_WORKER","1")
    assert hook.handle(event(),failing,state_root=tmp_path)=={}


def test_print_flag_hides_only_judgments(tmp_path, monkeypatch):
    calls = []
    def judge(prompt):
        calls.append(prompt)
        return {"simple_request": .95, "coding_task": .01}
    monkeypatch.setenv("JEV_PRINT_JUDGMENTS", "0")
    quiet = hook.handle(event(), judge, state_root=tmp_path)
    assert "systemMessage" not in quiet
    assert "jev-dispatch" in quiet["hookSpecificOutput"]["additionalContext"]
    visible = hook.handle(event(), judge, state_root=tmp_path, print_judgments=True)
    assert "问题:" in visible["systemMessage"]
    assert "P(是)=0.950" in visible["systemMessage"]
    assert "选择:" in visible["systemMessage"]
    assert quiet["hookSpecificOutput"] == visible["hookSpecificOutput"]
    assert calls == ["hello"]
