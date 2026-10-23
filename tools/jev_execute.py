"""One tool call from native Codex: route, run an independent Luna worker, verify."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import jev_router as router


REPORT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["completed", "needs_help", "blocked"]},
        "summary": {"type": "string"},
        "unresolved": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "unresolved"],
}
WORKER_RULES = """You are an independent Luna worker launched by the user's Jev script.
Entry routing has already happened. Do not run jev-execute, jev-chat, or another
entry router. Do not spawn agents or nested Codex processes. The parent owns
coordination and integration. Follow repository instructions, preserve others'
edits and change only the supplied allowed_paths. Do not commit, reset, or deploy.
Implement the supplied bounded task. For bugs, reproduce and add a failing
regression test before fixing. Run checks needed while developing. The script
will run the supplied final checks after you return, so do not rerun them merely
to produce a final report. Never claim checks you did not execute. Return the
requested JSON report; if blocked by permissions, missing context or ambiguity,
return needs_help or blocked with the actual limitation rather than guessing.
Do not inspect credentials or unrelated files. Do not open a UI unless the task
explicitly authorizes it. Existing runtime and user restrictions still apply.
"""
REPLY_RULES = """You are an independent Luna reply worker. Entry routing is already
complete. Do not invoke routers, agents or nested Codex processes.
Answer the user's request directly and briefly. Do not use tools,
modify files, run commands, or claim work that was not performed. Return only the
answer text in the required JSON report.
"""


def review(run_dir, result, reason):
    result["action"] = "current_review"
    result["review_reasons"] = [reason]
    router.write_json(run_dir / "result.json", result)
    print(f"[Jev] 交回当前会话：{reason}", file=sys.stderr)
    return result


def run_worker(repo, task, run_dir, sandbox="read-only", timeout=900, runner=None, reply=False):
    if os.environ.get("JEV_SCRIPT_WORKER") == "1":
        raise ValueError("recursive worker launch prohibited")
    if sandbox not in ("read-only", "workspace-write") or timeout <= 0:
        raise ValueError("invalid sandbox or timeout")
    runner = runner or router.run_command
    schema = run_dir / "worker-schema.json"
    report_path = run_dir / "worker-report.json"
    router.write_json(schema, REPORT_SCHEMA)
    argv = ["env", "JEV_SCRIPT_WORKER=1", "JEV_EXTERNAL_ROUTER=1",
            "codex", "exec", "-m", "gpt-5.6-luna", "--sandbox", sandbox,
            "-c", 'approval_policy="never"', "-c", "agents.enabled=false",
            "-c", "developer_instructions=" + json.dumps(REPLY_RULES if reply else WORKER_RULES),
            "--skip-git-repo-check", "--json", "--color", "never", "--output-schema", str(schema),
            "--output-last-message", str(report_path), "-"]
    print("[执行] 独立 gpt-5.6-luna 进程；不做事后模型审核。", file=sys.stderr)
    execution = runner(argv, repo, run_dir / "luna-exec.log", timeout,
                       stdin=json.dumps({"assigned_task": task}, ensure_ascii=False))
    result = {"execution": {"kind": "independent_codex_exec", "model": "gpt-5.6-luna",
                             "sandbox": sandbox, **execution}, "failure": None}
    if execution.get("exit_code") != 0:
        result["failure"] = "luna_execution_failed_or_timed_out"
        return result
    try:
        report = json.loads(report_path.read_text())
        if (not isinstance(report, dict) or report.get("status") != "completed"
                or not isinstance(report.get("summary"), str) or not report["summary"].strip()
                or report.get("unresolved") != []):
            result["failure"] = "worker_report_incomplete"
            result["worker_report"] = report if isinstance(report, dict) else None
            return result
    except (OSError, ValueError):
        result["failure"] = "worker_report_missing_or_invalid"
        return result
    result["worker_report"] = report
    return result


def execute(repo, task, jev, run_dir, sandbox="read-only", timeout=900,
            check_timeout=300, parent_run=None, runner=None):
    if os.environ.get("JEV_SCRIPT_WORKER") == "1":
        raise ValueError("recursive worker launch prohibited")
    if sandbox not in ("read-only", "workspace-write") or timeout <= 0 or check_timeout <= 0:
        raise ValueError("invalid sandbox or timeout")
    if not router.read_settings()["enabled"]:
        return {"action": "current", "routing": {"reasons": ["jev_disabled"]}}
    result = router.route(repo, task, jev, run_dir, parent_run=parent_run)
    router.print_decision("route", result, result["routing"]["reasons"],
                          worker_label="脚本启动独立 Luna 执行进程")
    if result["action"] == "current":
        return result
    worker = run_worker(repo, task, run_dir, sandbox, timeout, runner)
    result.update(worker)
    router.write_json(run_dir / "result.json", result)
    if worker["failure"]:
        return review(run_dir, result, worker["failure"])
    result = router.check_run(SimpleNamespace(timeout=check_timeout), run_dir,
                              worker["worker_report"])
    if parent_run is not None:
        # Delegated subtasks follow the full route/check/verify protocol. Entry
        # workers retain the lightweight check-only policy below.
        result = router.verify_run(run_dir, jev)
        result["policy"]["post_model_review"] = True
        router.print_decision("verify", result, result["review_reasons"])
    elif result["validation"]["reasons"]:
        result["action"] = "current_review"
        result["review_reasons"] = result["validation"]["reasons"]
    else:
        result["action"] = "accept"
        result["review_reasons"] = []
        result["policy"]["post_model_review"] = False
        print("[Jev] 实际检查通过，按用户策略不做模型审核。", file=sys.stderr)
    router.write_json(run_dir / "result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_file", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="read-only")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--check-timeout", type=int, default=300)
    parser.add_argument("--parent-run", type=Path)
    args = parser.parse_args(argv)
    run_dir = None
    jev = None
    try:
        if not router.read_settings()["enabled"]:
            print(json.dumps({"action": "current", "reasons": ["jev_disabled"],
                              "run_dir": None, "report": None}))
            return 0
        if os.environ.get("JEV_SCRIPT_WORKER") == "1":
            raise ValueError("recursive worker launch prohibited")
        task = router.load_task(args.task_file)
        repo = Path(router.git(args.repo.resolve(), "rev-parse", "--show-toplevel").decode().strip())
        run_dir = Path(tempfile.mkdtemp(prefix="jev-execute-"))
        settings = router.read_settings()
        if settings.get("enabled", True) and (settings.get("entry", True)
                                               or args.parent_run is not None):
            try:
                jev = router.Jev("jev-latest")
            except Exception:
                pass
        result = execute(repo, task, jev, run_dir, args.sandbox, args.timeout,
                         args.check_timeout, args.parent_run)
        print(json.dumps({"action": result["action"], "run_dir": str(run_dir),
                          "report": str(run_dir / "result.json"),
                          "summary": result.get("worker_report", {}).get("summary", ""),
                          "reasons": result.get("review_reasons", result["routing"]["reasons"])},
                         ensure_ascii=False))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"[Jev] 脚本未完成 ({type(error).__name__})，交回当前会话。", file=sys.stderr)
        print(json.dumps({"action": "current_review", "error_type": type(error).__name__,
                          "run_dir": str(run_dir) if run_dir else None,
                          "report": str(run_dir / "result.json") if run_dir else None}))
        return 2
    finally:
        if jev:
            jev.close()


if __name__ == "__main__":
    sys.exit(main())
