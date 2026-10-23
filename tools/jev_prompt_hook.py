"""Codex UserPromptSubmit hook: classify input without launching another model."""

import argparse
import json
import math
import os
import sys

import jev_state as states
import jev_settings


QUESTIONS = {
    "simple_request": "这是意图明确、范围有限、可由轻量模型完成的简单请求吗？",
    "coding_task": "这条输入是否要求处理代码、文件或执行工具？",
}
CRITERIA = {
    "simple_request": {
        "true": "A greeting, straightforward question, or bounded implementation with sufficiently clear intended behavior. No difficult architectural, security, or broad cross-system reasoning is needed.",
        "false": "Requires difficult reasoning, architectural choices, high-consequence changes, or essential missing context. Continuation requests without the referenced context are uncertain, not automatically simple.",
    },
    "coding_task": {
        "true": "Requests implementation, debugging, repository/file access, command execution, research or other tool use.",
        "false": "Can answer without tools or file changes, including greetings and asking the executor's model identity.",
    },
}


def judge(prompt):
    if not jev_settings.read_settings()["enabled"]:
        raise RuntimeError("jev_disabled")
    from typesafe_sdk import Noul, NoulCriteria, RetryPolicy, TypeSafeClient

    client = TypeSafeClient(model="jev-latest", timeout=15,
                           retry=RetryPolicy(max_retries=0))
    try:
        response = client.system_one(
            state={"user_input": prompt},
            questions={key: Noul(instructions=question,
                                  criteria=NoulCriteria(**CRITERIA[key]))
                       for key, question in QUESTIONS.items()},
        )
        return {key: response.nouls[key].noul for key in QUESTIONS}
    finally:
        client.close()


def valid_probability(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def classify(event, assessor, path):
    with states.locked(path):
        if path.exists():
            state = states.read(path)
            if state["prompt"] != event["prompt"]:
                raise ValueError("turn input changed")
            if state["state"] == "routing":
                state.update(state="current_required", reason="previous_routing_interrupted")
                states.save(path, state)
            return state
        state = {"version": 1, "session_id": event["session_id"], "turn_id": event["turn_id"],
                 "cwd": event.get("cwd", os.getcwd()), "prompt": event["prompt"],
                 "state": "routing", "questions": QUESTIONS, "scores": {}, "reason": ""}
        states.save(path, state)
        try:
            scores = assessor(event["prompt"])
            if not isinstance(scores, dict) or not all(valid_probability(scores.get(k)) for k in QUESTIONS):
                raise ValueError("invalid judgment")
            state["scores"] = scores
            coding = scores["coding_task"]
            simple = scores["simple_request"] >= .8 and (coding <= .2 or coding >= .8)
            state.update(state="luna_ready" if simple else "current_required",
                         mode="task" if coding >= .8 else "reply")
        except Exception as error:
            state.update(state="current_required", reason=type(error).__name__)
        states.save(path, state)
        return state


def handle(event, assessor=judge, state_root=None, print_judgments=None):
    if os.environ.get("JEV_EXTERNAL_ROUTER") == "1" or os.environ.get("JEV_SCRIPT_WORKER") == "1":
        return {}
    if event.get("hook_event_name") != "UserPromptSubmit":
        return {}
    try:
        settings = jev_settings.read_settings()
        if not settings["hook"]:
            return {}
        words = event.get("prompt", "").strip().split()
        if words and words[0] == "jev":
            try:
                message = jev_settings.control(words[1:])
            except ValueError:
                message = jev_settings.HELP
            # Consume explicit local control commands without calling any model.
            return {"decision": "block", "reason": message}
        if print_judgments is None:
            print_judgments = settings["print"]
        if not settings["enabled"] or not settings["entry"]:
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                    "additionalContext": "Jev entry routing is disabled by user configuration. "
                    "Handle this input in the current session; do not invoke an entry router. "
                    + ("Jev delegation review remains enabled." if settings["enabled"] else
                       "All Jev calls and the Jev execution/check/review pipeline are disabled. "
                       "Do not invoke jev-dispatch, jev-execute or jev-run. Handle work normally; "
                       "the current model decides delegation, checks and review under ordinary task rules.")}}
        if not isinstance(event.get("prompt"), str) or not event["prompt"].strip():
            raise ValueError("missing text input")
        path = states.turn_path(event, state_root)
        state = classify(event, assessor, path)
        lines = []
        for key, question in QUESTIONS.items():
            value = state["scores"].get(key)
            answer = f"P(是)={value:.3f}" if valid_probability(value) else "未获得有效结果"
            lines.append(f"[Jev] 问题: {question}\n      结果: {answer}")
        if state["reason"]:
            lines.append("[Jev] 判断不可用: " + state["reason"])
        selected = state["state"]
        lines.append("[Jev] 选择: " + ("Luna 执行，完成后不做模型审核" if selected == "luna_ready"
                                      else "当前会话处理" if selected == "current_required" else selected))
        context = f"Jev turn state: {path}\n"
        if selected == "luna_ready":
            context += ("Entry judgment is complete. Do not reclassify or answer the request yourself. "
                        "Call the authorized independent-worker script, not the native subagent tool: "
                        f"jev-dispatch {path}. ")
            if state["mode"] == "task":
                context += ("For this tool/code task, first prepare a scoped task JSON with task, context, "
                            "acceptance_criteria, allowed_paths and actual check argv, then append "
                            "--task-file /tmp/task.json. Add --sandbox workspace-write only for authorized "
                            "edits permitted in this session. Gather only necessary context; do not implement "
                            "the task before delegation. If essential details are missing, ask rather than guess. ")
            context += ("On done, deliver the worker answer without Jev or parent model review. "
                        "Do not repeat valid executable checks. On failed, handle the stated failure in this "
                        "session. Preserve all higher-priority restrictions; report a real limitation if blocked.")
        elif selected == "current_required":
            context += ("Jev chose the current session or could not safely choose Luna. Handle the request "
                        "here without another entry classification. For complex tasks, retain native Luna "
                        "subagents for bounded independent work permitted by runtime rules.")
        else:
            context += ("Read the persisted state. If done, deliver its saved result without another execution "
                        "or review. If running or failed, do not start another worker automatically.")
        result = {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": context}}
        if print_judgments:
            result["systemMessage"] = "\n".join(lines)
        elif state["reason"]:
            result["systemMessage"] = "[Jev] 判断不可用，交回当前会话: " + state["reason"]
        return result
    except Exception as error:
        return {"systemMessage": f"[Jev] 入口状态不可用 ({type(error).__name__})，交回当前会话。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-judgments", action=argparse.BooleanOptionalAction,
                        default=None, help="Print questions, probabilities and routing (default: on; JEV_PRINT_JUDGMENTS=0 hides them)")
    args = parser.parse_args()
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("invalid hook input")
        result = handle(event, print_judgments=args.print_judgments)
    except (ValueError, TypeError):
        result = {"systemMessage": "[Jev] 钩子输入无效，交回当前会话模型。"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
