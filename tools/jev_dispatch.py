"""Consume a Jev turn decision once; execute Luna without post-model review."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

import jev_router as router
import jev_state as states


def dispatch(path, task_file=None, sandbox="read-only", timeout=900, check_timeout=300,
             worker=None):
    if os.environ.get("JEV_SCRIPT_WORKER") == "1":
        raise ValueError("recursive worker launch prohibited")
    if sandbox not in ("read-only", "workspace-write") or timeout <= 0 or check_timeout <= 0:
        raise ValueError("invalid execution options")
    if worker is None:
        from jev_execute import run_worker
        worker = run_worker
    with states.locked(path):
        state = states.read(path)
        if state["state"] in ("done", "failed", "current_required"):
            return state
        if state["state"] != "luna_ready":
            raise RuntimeError("turn already running or not ready; do not repeat it")
        if not router.read_settings()["enabled"]:
            state.update(state="current_required", reason="jev_disabled")
            states.save(path, state)
            return state
        reply = state["mode"] == "reply"
        if reply:
            task = {"task": state["prompt"], "context": "Reply to this user input directly. "
                    "The execution request uses model identifier gpt-5.6-luna; when asked about identity, "
                    "report this identifier, not a previous session model. No tools or file changes."}
            sandbox = "read-only"
        else:
            if task_file is None:
                raise ValueError("tool/code request needs a scoped task file and executable checks")
            task = router.load_task(task_file)
            task = dict(task, original_user_request=state["prompt"])
        run_dir = Path(tempfile.mkdtemp(prefix="jev-turn-"))
        state.update(state="luna_running", run_dir=str(run_dir), executor="gpt-5.6-luna",
                     post_model_review=False)
        states.save(path, state)
        print("[Luna] 开始执行；本轮完成后不调用审核模型。", file=sys.stderr)
        try:
            repo = Path(state["cwd"]).resolve()
            result = worker(repo, task, run_dir, sandbox=sandbox, timeout=timeout, reply=reply)
            state["result"] = result
            if result.get("failure"):
                state.update(state="failed", reason=result["failure"])
            else:
                checks = []
                if not reply:
                    for index, argv in enumerate(task["checks"]):
                        record = router.run_command(argv, repo, run_dir / f"check-{index}.log", check_timeout)
                        record["output_tail"] = Path(record["log"]).read_text(errors="replace")[-12000:]
                        checks.append(record)
                state["checks"] = checks
                if any(item["exit_code"] != 0 for item in checks):
                    state.update(state="failed", reason="checks_failed_or_unavailable")
                else:
                    state.update(state="done", answer=result["worker_report"]["summary"], reason="")
            states.save(path, state)
            print(f"[Luna] 状态: {state['state']}；未进行事后模型审核。", file=sys.stderr)
            return state
        except BaseException as error:
            state.update(state="failed", reason=type(error).__name__)
            states.save(path, state)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_file", type=Path)
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="read-only")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--check-timeout", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        state = dispatch(args.state_file, args.task_file, args.sandbox, args.timeout, args.check_timeout)
        print(json.dumps({"state": state["state"], "answer": state.get("answer", ""),
                          "reason": state.get("reason", ""), "state_file": str(args.state_file)},
                         ensure_ascii=False))
        return 0 if state["state"] in ("done", "current_required") else 1
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"state": "unavailable", "reason": type(error).__name__,
                          "state_file": str(args.state_file)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
