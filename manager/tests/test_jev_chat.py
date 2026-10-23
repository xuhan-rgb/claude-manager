import importlib.util
from copy import deepcopy
from pathlib import Path
import sys

import pytest


CHAT_PATH = Path(__file__).parents[2] / "tools" / "jev_chat.py"
sys.path.insert(0, str(CHAT_PATH.parent))
SPEC = importlib.util.spec_from_file_location("jev_chat", CHAT_PATH)
jev_chat = importlib.util.module_from_spec(SPEC)


class FakeBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run_turn(self, thread_id, model, prompt):
        self.calls.append((thread_id, model, prompt))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeJudge:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def assess(self, state, questions):
        self.calls.append((state, questions))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(text="done", items=None, status="completed"):
    return {"text": text, "items": items or [], "status": status}


def load_module():
    SPEC.loader.exec_module(jev_chat)
    return jev_chat


def run(backend, judge, prompt="ship the fix", history=None):
    return load_module().execute_request(
        backend, judge, "thread-1", "gpt-5.6-primary", prompt, history if history is not None else []
    )


def safe_route():
    return {
        "architecture": 0,
        "ambiguity": 0,
        "broad_context": 0,
        "high_risk": 0,
        "not_local": 0,
    }


def safe_verify():
    return {"violation": 0, "unverified": 0}


def test_simple_request_uses_luna_once_without_primary_or_verification():
    backend = FakeBackend([response("luna answer", [{"kind": "result"}])])
    judge = FakeJudge([safe_route(), safe_verify()])

    result = run(backend, judge)

    assert result == {"model": "gpt-5.6-luna", "text": "luna answer", "escalated": False}
    assert [(model, thread) for thread, model, _ in backend.calls] == [
        ("gpt-5.6-luna", "thread-1")
    ]
    assert len(judge.calls) == 2


def test_complex_route_uses_configured_primary_model_without_fixed_astra():
    route = safe_route()
    route["broad_context"] = 0.21
    backend = FakeBackend([response("primary answer")])
    judge = FakeJudge([route])

    result = run(backend, judge)

    assert result["model"] == "gpt-5.6-primary"
    assert result["text"] == "primary answer"
    assert result["escalated"] is False
    assert len(backend.calls) == 1
    assert backend.calls[0][1] != "gpt-6-astra"


def test_route_failure_only_runs_primary_model():
    backend = FakeBackend([response("fallback")])
    judge = FakeJudge([RuntimeError("judge unavailable")])

    result = run(backend, judge)

    assert result["model"] == "gpt-5.6-primary"
    assert result["text"] == "fallback"
    assert len(backend.calls) == 1
    assert backend.calls[0][1] == "gpt-5.6-primary"


@pytest.mark.parametrize("value", [float("nan"), True, "bad"])
def test_invalid_route_signal_only_runs_primary_model(value):
    route = safe_route()
    route["architecture"] = value
    backend = FakeBackend([response("review")])
    judge = FakeJudge([route])

    result = run(backend, judge)

    assert result["model"] == "gpt-5.6-primary"
    assert len(backend.calls) == 1


def test_luna_execution_failure_escalates_without_verification():
    backend = FakeBackend([response("partial", status="failed"), response("rescued")])
    judge = FakeJudge([safe_route()])
    prompt = "repair the migration"

    result = run(backend, judge, prompt)

    assert result == {"model": "gpt-5.6-primary", "text": "rescued", "escalated": True}
    assert len(judge.calls) == 1
    assert [call[0:2] for call in backend.calls] == [
        ("thread-1", "gpt-5.6-luna"), ("thread-1", "gpt-5.6-primary")
    ]
    assert prompt in backend.calls[1][2]


def test_luna_verification_failure_escalates_on_same_thread():
    backend = FakeBackend([response("unsafe", [{"item": "evidence"}]), response("fixed")])
    judge = FakeJudge([safe_route(), {"violation": 0.31, "unverified": 0}])

    result = run(backend, judge, "implement the parser")

    assert result == {"model": "gpt-5.6-primary", "text": "fixed", "escalated": True}
    assert [call[0:2] for call in backend.calls] == [
        ("thread-1", "gpt-5.6-luna"), ("thread-1", "gpt-5.6-primary")
    ]
    assert "implement the parser" in backend.calls[1][2]


def test_verification_judge_exception_cannot_bypass_primary_escalation():
    backend = FakeBackend([response("unsafe"), response("reviewed")])
    judge = FakeJudge([safe_route(), RuntimeError("judge unavailable")])

    result = run(backend, judge)

    assert result["model"] == "gpt-5.6-primary"
    assert result["escalated"] is True
    assert len(backend.calls) == 2


def test_verification_evidence_items_are_given_to_judge():
    items = [{"tool": "pytest", "status": "passed", "id": "check-7"}]
    backend = FakeBackend([response("luna", items)])
    judge = FakeJudge([safe_route(), safe_verify()])

    run(backend, judge)

    assert len(judge.calls) == 2
    verification_state = judge.calls[1][0]
    assert "check-7" in repr(verification_state)
    assert verification_state["result"]["items"] == items


@pytest.mark.parametrize("signal", [
    {"violation": float("nan"), "unverified": 0},
    {"violation": 0, "unverified": "invalid"},
])
def test_invalid_verification_signal_cannot_accept(signal):
    backend = FakeBackend([response("luna"), response("primary")])
    judge = FakeJudge([safe_route(), signal])

    result = run(backend, judge)

    assert result["escalated"] is True
    assert len(backend.calls) == 2
    assert backend.calls[1][1] == "gpt-5.6-primary"


def test_history_is_not_modified_by_request():
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
    original = deepcopy(history)
    backend = FakeBackend([response("answer")])
    judge = FakeJudge([safe_route(), safe_verify()])

    run(backend, judge, history=history)

    assert history == original


def test_failed_primary_turn_raises_instead_of_returning_completion():
    backend = FakeBackend([response("failed", status="failed")])
    route = safe_route()
    route["broad_context"] = 0.3
    judge = FakeJudge([route])

    with pytest.raises(RuntimeError, match="did not complete"):
        run(backend, judge)


def test_escalation_is_false_when_primary_model_is_luna():
    backend = FakeBackend([response("unsafe"), response("reviewed")])
    judge = FakeJudge([safe_route(), {"violation": 0.8, "unverified": 0}])

    result = load_module().execute_request(
        backend, judge, "thread-1", "gpt-5.6-luna", "same model", []
    )

    assert result["model"] == "gpt-5.6-luna"
    assert result["escalated"] is False


def test_completed_empty_text_cannot_be_accepted():
    backend = FakeBackend([response(""), response("primary")])
    judge = FakeJudge([safe_route(), safe_verify()])

    result = run(backend, judge)

    assert result["escalated"] is True
    assert result["text"] == "primary"


def test_failed_command_evidence_requires_primary_review():
    items = [{"id": "command-1", "type": "commandExecution", "status": "failed"}]
    backend = FakeBackend([response("claimed", items), response("reviewed")])
    judge = FakeJudge([safe_route(), safe_verify()])

    result = run(backend, judge)

    assert result["escalated"] is True
    assert result["model"] == "gpt-5.6-primary"
