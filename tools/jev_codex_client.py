"""Small stdio client for the installed Codex app-server protocol."""

import json
import os
import queue
import signal
import subprocess
import threading


INSTRUCTIONS = """
This conversation is managed by an external Jev router. It selects the execution
model before each turn; entry routing has ALREADY happened. Do not repeat entry
routing through the legacy UserPromptSubmit hook or ask a parent model to dispatch.
When the execution model is gpt-5.6-luna, execute the bounded request directly,
run relevant actual checks for code changes, and return evidence and limitations.
When the execution model is the primary model, own design and integration and use
native Luna subagents for bounded independent work when runtime rules permit.
Existing repository instructions, bug reproduction, permissions, and validation
requirements still apply. Never infer task completion from a worker claim alone.
The external router verifies Luna results and delivers accepted answers directly.
"""


class CodexClient:
    def __init__(self, cwd, model=None):
        self.cwd = str(cwd)
        self.requested_model = model
        self.serial = 0
        self.events = []
        self.incoming = queue.Queue()
        self.process = None
        self.active_turn = None

    def __enter__(self):
        env = dict(os.environ, JEV_EXTERNAL_ROUTER="1")
        self.process = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"], cwd=self.cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
            start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.request("initialize", {"clientInfo": {"name": "jev_chat", "version": "0.1.0"},
                                        "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
            params = {"cwd": self.cwd, "developerInstructions": INSTRUCTIONS}
            if self.requested_model:
                params["model"] = self.requested_model
            result = self.request("thread/start", params)
            self.thread_id = result["thread"]["id"]
            self.primary_model = result["model"]
            return self
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                self.incoming.put(json.loads(line))
        except Exception:
            pass
        finally:
            self.incoming.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def receive(self):
        message = self.incoming.get(timeout=300)
        if message is None:
            raise RuntimeError("Codex app-server disconnected")
        return message

    def server_request(self, message):
        method, params = message["method"], message.get("params", {})
        if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            # Preserve host approval policy. A terminal approval is never automatic.
            print("\n[Codex 审批] " + json.dumps(params, ensure_ascii=False), flush=True)
            try:
                approve = input("允许这一次操作？输入 yes 批准，其他输入拒绝 > ") == "yes"
            except EOFError:
                approve = False
            self.send({"id": message["id"], "result": {"decision": "accept" if approve else "decline"}})
        elif method == "item/tool/requestUserInput":
            answers = {}
            for question in params.get("questions", []):
                print(question.get("question", ""), flush=True)
                for option in question.get("options") or []:
                    print("- " + option["label"] + ": " + option.get("description", ""))
                try:
                    answer = input("> ")
                except EOFError:
                    answer = ""
                answers[question["id"]] = {"answers": [answer] if answer else []}
            self.send({"id": message["id"], "result": {"answers": answers}})
        else:
            self.send({"id": message["id"], "error": {
                "code": -32601, "message": "This terminal client does not support " + method}})

    def request(self, method, params):
        self.serial += 1
        identity = self.serial
        self.send({"id": identity, "method": method, "params": params})
        while True:
            message = self.receive()
            if "method" in message and "id" in message:
                self.server_request(message)
            elif message.get("id") == identity:
                if "error" in message:
                    raise RuntimeError("Codex RPC failed: " + method)
                return message["result"]
            elif "method" in message:
                self.events.append(message)

    def run_turn(self, thread_id, model, prompt):
        response = self.request("turn/start", {
            "threadId": thread_id, "model": model,
            "input": [{"type": "text", "text": prompt, "text_elements": []}]})
        turn_id = response["turn"]["id"]
        self.active_turn = (thread_id, turn_id)
        items = {}
        while True:
            message = self.events.pop(0) if self.events else self.receive()
            if "method" in message and "id" in message:
                self.server_request(message)
                continue
            params = message.get("params", {})
            if params.get("threadId") != thread_id:
                continue
            method = message.get("method")
            if method == "item/completed" and params.get("turnId") == turn_id:
                item = params["item"]
                items[item["id"]] = item
                if item["type"] != "agentMessage":
                    print(f"[Codex] {item['type']}: {item.get('status', 'completed')}", flush=True)
            elif method == "turn/completed" and params["turn"]["id"] == turn_id:
                self.active_turn = None
                # Some protocol versions also include the items on completion.
                for item in params["turn"].get("items", []):
                    items[item["id"]] = item
                messages = [i for i in items.values() if i["type"] == "agentMessage"]
                final = [i for i in messages if i.get("phase") == "final_answer"]
                text = "\n".join(i["text"] for i in (final or messages))
                return {"status": params["turn"]["status"], "text": text,
                        "items": list(items.values())}

    def close(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            if self.active_turn:
                thread_id, turn_id = self.active_turn
                try:
                    self.send({"id": "interrupt", "method": "turn/interrupt",
                               "params": {"threadId": thread_id, "turnId": turn_id}})
                except (OSError, ValueError):
                    pass
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait()

    def __exit__(self, *args):
        self.close()
