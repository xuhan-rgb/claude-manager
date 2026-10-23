import importlib.util
import json
import queue
import sys
from pathlib import Path

import pytest


CLIENT_PATH = Path(__file__).parents[2] / "tools" / "jev_codex_client.py"
sys.path.insert(0, str(CLIENT_PATH.parent))
SPEC = importlib.util.spec_from_file_location("jev_codex_client", CLIENT_PATH)
jev_codex_client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jev_codex_client)


def client():
    value = jev_codex_client.CodexClient.__new__(jev_codex_client.CodexClient)
    value.serial = 0
    value.events = []
    value.incoming = queue.Queue()
    value.process = None
    value.active_turn = None
    return value


def test_run_turn_collects_only_matching_thread_turn_and_preserves_command_evidence(monkeypatch):
    value = client()
    request_models = []

    def request(method, params):
        request_models.append((method, params))
        return {"turn": {"id": "turn-7"}}

    monkeypatch.setattr(value, "request", request)
    value.incoming.put({"method": "item/completed", "params": {
        "threadId": "other", "turnId": "turn-7",
        "item": {"id": "other-item", "type": "commandExecution", "status": "failed"}}})
    value.incoming.put({"method": "item/completed", "params": {
        "threadId": "thread-1", "turnId": "old",
        "item": {"id": "old-item", "type": "agentMessage", "text": "old"}}})
    command = {"id": "cmd-1", "type": "commandExecution", "status": "failed", "command": "pytest"}
    value.incoming.put({"method": "item/completed", "params": {
        "threadId": "thread-1", "turnId": "turn-7", "item": command}})
    value.incoming.put({"method": "item/completed", "params": {
        "threadId": "thread-1", "turnId": "turn-7",
        "item": {"id": "answer", "type": "agentMessage", "phase": "final_answer", "text": "done"}}})
    value.incoming.put({"method": "turn/completed", "params": {
        "threadId": "thread-1",
        "turn": {"id": "turn-7", "status": "completed", "items": [command]}}})

    result = value.run_turn("thread-1", "gpt-5.6-luna", "do it")

    assert result["status"] == "completed"
    assert result["text"] == "done"
    assert result["items"] == [command, {"id": "answer", "type": "agentMessage",
                                           "phase": "final_answer", "text": "done"}]
    assert request_models[0][1]["model"] == "gpt-5.6-luna"


def test_thread_handshake_freezes_server_primary_model(monkeypatch, tmp_path):
    value = jev_codex_client.CodexClient(tmp_path, "requested-model")
    sent = []
    responses = iter([
        {"result": {"ok": True}},
        {"result": {"thread": {"id": "thread-1"}, "model": "server-primary"}},
    ])

    class FakeProcess:
        stdin = None
        stdout = []

        def poll(self):
            return 1

    monkeypatch.setattr(jev_codex_client.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(jev_codex_client.threading, "Thread", lambda **kwargs: type(
        "NoopThread", (), {"start": lambda self: None})())
    monkeypatch.setattr(value, "send", sent.append)
    monkeypatch.setattr(value, "request", lambda method, params: next(responses)["result"])

    entered = value.__enter__()

    assert entered.primary_model == "server-primary"
    assert sent == [{"method": "initialized", "params": {}}]
    value.close()


def test_run_turn_explicitly_uses_requested_model_without_overriding_transport_policy(monkeypatch):
    value = client()
    calls = []

    def request(method, params):
        calls.append((method, params))
        return {"turn": {"id": "turn-1"}}

    monkeypatch.setattr(value, "request", request)
    value.incoming.put({"method": "turn/completed", "params": {
        "threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed",
                                                "items": [{"id": "a", "type": "agentMessage", "text": "ok"}]}}})

    value.run_turn("thread-1", "gpt-5.6-luna", "prompt")

    assert calls[0][1]["model"] == "gpt-5.6-luna"
    inputs = calls[0][1]["input"]
    assert inputs == [{"type": "text", "text": "prompt", "text_elements": []}]
    assert "approval" not in calls[0][1]
    assert "sandbox" not in calls[0][1]


def test_request_saves_early_notification_while_waiting_for_response(monkeypatch):
    value = client()
    sent = []
    value.send = sent.append
    value.incoming.put({"method": "turn/started", "params": {"threadId": "thread-1"}})
    value.incoming.put({"id": 1, "result": {"ok": True}})

    assert value.request("initialize", {}) == {"ok": True}
    assert value.events == [{"method": "turn/started", "params": {"threadId": "thread-1"}}]
    assert sent[0]["id"] == 1


def test_approval_requires_exact_yes_and_eof_declines(monkeypatch):
    value = client()
    sent = []
    value.send = sent.append
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    value.server_request({"id": 4, "method": "item/commandExecution/requestApproval",
                          "params": {"command": "rm -i"}})
    assert sent[-1] == {"id": 4, "result": {"decision": "decline"}}

    def eof(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    value.server_request({"id": 5, "method": "item/fileChange/requestApproval", "params": {}})
    assert sent[-1] == {"id": 5, "result": {"decision": "decline"}}


def test_unknown_server_request_returns_protocol_error():
    value = client()
    sent = []
    value.send = sent.append

    value.server_request({"id": 8, "method": "server/unknown", "params": {}})

    assert sent == [{"id": 8, "error": {"code": -32601,
                                         "message": "This terminal client does not support server/unknown"}}]
