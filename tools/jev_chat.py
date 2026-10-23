"""Route before inference; Luna and the configured primary share one Codex thread."""

import argparse
import json
import math
import os
from pathlib import Path
import sys

from jev_router import ROUTE_QUESTIONS, ROUTE_CRITERIA, question_spec


VERIFY = {
    "violation": question_spec(
        "结果是否违反用户要求，或包含实际证据所否定的结论？",
        "The answer or execution contradicts the request or observed evidence.",
        "The result satisfies the request without such contradictions."),
    "unverified": question_spec(
        "是否缺少完成任务所需的证据，包括代码任务的实际执行验证？",
        "Completion is unsupported. Code tasks require relevant actual checks, not claims alone.",
        "Evidence establishes completion; a simple greeting needs only an appropriate reply."),
}
LUNA = "gpt-5.6-luna"


def assess(judge, state, questions, limit):
    try:
        if len(json.dumps(state, ensure_ascii=False)) > 60000:
            raise ValueError("evidence too large")
        scores = judge.assess(state, questions)
        good = True
        for key, question in questions.items():
            value = scores.get(key)
            valid = type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1
            answer = f"P(是)={value:.3f}" if valid else "无有效结果"
            print(f"[Jev] 问题: {question['instructions']}\n      结果: {answer}", flush=True)
            good = good and valid and value <= limit
        return good
    except Exception as error:
        print(f"[Jev] 判断不可用（{type(error).__name__}），交给当前配置模型。", flush=True)
        return False


def execute_request(backend, judge, thread_id, primary_model, prompt, history):
    questions = {key: question_spec(question, *ROUTE_CRITERIA[key])
                 for key, question in ROUTE_QUESTIONS.items()}
    questions["ambiguity"] = question_spec(
        "为了正确满足本条请求，是否必须先澄清会实质改变结果的需求？",
        "Essential missing information prevents a correct response or implementation; different interpretations change the intended result.",
        "The request can be fulfilled as stated. Greetings and casual conversation do not require coding acceptance criteria.")
    # Make the local-change question apply to ordinary replies as well as coding.
    questions["not_local"] = question_spec(
        "这是否超出一个意图明确、范围有限的简单请求？",
        "Requires complex reasoning or broad, unspecified work.",
        "A simple greeting, self-contained answer, or explicitly bounded local implementation.")
    use_luna = assess(judge, {
        "request": prompt, "history": history,
        "routing_scope": "Classify what is necessary to satisfy this request. For greetings or non-coding conversation, architecture, cross-subsystem implementation and software-change risks do not apply. Do not invent an unstated coding task."}, questions, .2)
    model = LUNA if use_luna else primary_model
    print(f"[执行] 直接调用 {model}", flush=True)
    result = backend.run_turn(thread_id, model, prompt)
    escalated = False
    if use_luna:
        tool_failed = any(
            item.get("type") in ("commandExecution", "fileChange") and (
                item.get("status") == "failed" or item.get("exitCode") not in (None, 0))
            for item in result.get("items", []))
        accepted = (result.get("status") == "completed" and bool(result.get("text", "").strip())
                    and not tool_failed and assess(
            judge, {"request": prompt, "history": history, "result": result}, VERIFY, .3)
                    )
        if not accepted:
            print(f"[升级] 交给当前配置模型 {primary_model}", flush=True)
            result = backend.run_turn(
                thread_id, primary_model,
                "外部 Jev 级联要求接手上一轮任务。原用户请求：\n" + prompt +
                "\n请根据同一会话中的执行记录检查、补全或纠正结果，复用有效验证；"
                "不要把上一轮未经验证的完成声明当作证据。复杂任务使用合适的 Luna 子代理。")
            model = primary_model
            escalated = primary_model != LUNA
        else:
            print("[Jev] 验证通过，直接返回 Luna 结果。", flush=True)
    if result.get("status") != "completed" or not result.get("text", "").strip():
        raise RuntimeError("Codex turn did not complete; see session for partial work")
    return {"model": model, "text": result["text"], "escalated": escalated}


def main():
    from jev_codex_client import CodexClient
    from jev_router import Jev

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", help="single request; omit for interactive conversation")
    parser.add_argument("--model", help="primary model; defaults to Codex resolved configuration")
    parser.add_argument("--cd", default=os.getcwd())
    args = parser.parse_args()
    history = []
    judge = Jev("jev-latest")
    try:
        with CodexClient(Path(args.cd).resolve(), args.model) as backend:
            print(f"[Jev 会话] {backend.thread_id}\n[当前配置模型] {backend.primary_model}")
            print("[入口] 简单请求直接调用 Luna；复杂请求由当前配置模型接手并可使用子代理。")
            while True:
                try:
                    prompt = args.prompt if args.prompt is not None else input("\n你 > ")
                except EOFError:
                    break
                if not prompt.strip():
                    if args.prompt is not None:
                        break
                    continue
                if prompt.strip() == "/exit":
                    break
                result = execute_request(backend, judge, backend.thread_id,
                                         backend.primary_model, prompt, history)
                print(f"\n[{result['model']}]\n{result['text']}", flush=True)
                history.extend([{"role": "user", "content": prompt},
                                {"role": "assistant", "content": result["text"]}])
                if args.prompt is not None:
                    break
    except KeyboardInterrupt:
        print("\n已停止入口；部分任务可能已有修改，请检查会话记录。", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"入口失败（{type(error).__name__}）；未声称任务完成。", file=sys.stderr)
        return 1
    finally:
        judge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
