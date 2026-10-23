import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


TOOLS = Path(__file__).parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location("jev_execute", TOOLS / "jev_execute.py")
jev_execute = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jev_execute)


class FakeJev:
    def __init__(self, route=None, verification=None):
        self.route = route or {key: 0 for key in ("architecture", "ambiguity", "broad_context", "high_risk", "not_local")}
        self.verification = verification or {}
        self.calls = []

    def assess(self, state, questions):
        self.calls.append((state, questions))
        if "architecture" in questions:
            return {key: self.route.get(key, 0) for key in questions}
        return {key: self.verification.get(key, 0) for key in questions}


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "value.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "initial"], check=True)
    return tmp_path


def run_dir():
    return Path(tempfile.mkdtemp(prefix="jev-execute-test-"))


def task(check=None):
    return {
        "task": "change VALUE to 2",
        "context": "bounded fixture task",
        "acceptance_criteria": ["src/value.py defines VALUE = 2"],
        "allowed_paths": ["src"],
        "checks": [check or [sys.executable, "-B", "-c",
                             "from src.value import VALUE; assert VALUE == 2"]],
    }


def report_path(argv):
    index = argv.index("--output-last-message")
    return Path(argv[index + 1])


def successful_runner(argv, repo, log, timeout, stdin=None):
    report_path(argv).write_text(json.dumps({
        "status": "completed", "summary": "changed value", "unresolved": []
    }))
    (Path(repo) / "src" / "value.py").write_text("VALUE = 2\n")
    return {"argv": argv, "exit_code": 0, "log": str(log)}


def test_complex_route_stays_with_current_session_without_running_worker(repo):
    route = {"high_risk": 0.9}
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("worker must not run for current-session route")

    result = jev_execute.execute(repo, task(), FakeJev(route=route), run_dir(), runner=runner)

    assert result["action"] == "current"
    assert calls == []


def test_simple_worker_uses_luna_read_only_policy_and_prompt_scope(repo):
    calls = []

    def runner(argv, repo_path, log, timeout, stdin=None):
        calls.append((argv, stdin))
        return successful_runner(argv, repo_path, log, timeout, stdin)

    judge = FakeJev(verification={})
    result = jev_execute.execute(repo, task(), judge, run_dir(), runner=runner)

    assert result["action"] == "accept"
    assert len(judge.calls) == 1
    assert len(calls) == 1
    argv, prompt = calls[0]
    assert "gpt-5.6-luna" in argv
    assert "--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
    assert "-c" in argv
    assert "agents.enabled=false" in argv
    assert "change VALUE to 2" in prompt
    assert "src/value.py defines VALUE = 2" in prompt
    assert '"allowed_paths": ["src"]' in prompt
    assert "change VALUE to 2" in prompt
    assert "change VALUE to 2" not in " ".join(argv)


def test_worker_nonzero_exit_cannot_be_accepted(repo):
    def runner(argv, repo_path, log, timeout, stdin=None):
        return {"argv": argv, "exit_code": 1, "log": str(log)}

    result = jev_execute.execute(repo, task(), FakeJev(), run_dir(), runner=runner)

    assert result["action"] == "current_review"
    assert result.get("review_reasons") == ["luna_execution_failed_or_timed_out"]


def test_missing_or_invalid_worker_report_cannot_be_accepted(repo):
    def runner(argv, repo_path, log, timeout, stdin=None):
        report_path(argv).write_text("not json")
        return {"argv": argv, "exit_code": 0, "log": str(log)}

    result = jev_execute.execute(repo, task(), FakeJev(), run_dir(), runner=runner)

    assert result["action"] == "current_review"


@pytest.mark.parametrize("report", [{}, {"status": "completed", "summary": "", "unresolved": []},
                                     {"status": "needs_help", "summary": "blocked", "unresolved": ["x"]}])
def test_missing_or_incomplete_worker_report_cannot_be_accepted(repo, report):
    def runner(argv, repo_path, log, timeout, stdin=None):
        report_path(argv).write_text(json.dumps(report))
        return {"argv": argv, "exit_code": 0, "log": str(log)}

    result = jev_execute.execute(repo, task(), FakeJev(), run_dir(), runner=runner)

    assert result["action"] == "current_review"
    assert result["review_reasons"] == ["worker_report_incomplete"]


def test_route_jev_failure_stays_with_current_session(repo):
    class BrokenJev(FakeJev):
        def assess(self, state, questions):
            raise RuntimeError("unavailable")

    calls = []
    result = jev_execute.execute(repo, task(), BrokenJev(), run_dir(),
                                 runner=lambda *args, **kwargs: calls.append(args))

    assert result["action"] == "current"
    assert calls == []


def test_recursive_worker_guard_blocks_execution(repo, monkeypatch):
    monkeypatch.setenv("JEV_SCRIPT_WORKER", "1")
    with pytest.raises(ValueError, match="recursive"):
        jev_execute.execute(repo, task(), FakeJev(), run_dir(), runner=successful_runner)


def test_parent_run_skips_entry_routing_jev(repo):
    parent_dir = run_dir()
    parent_task = task()
    jev_execute.router.route(repo, parent_task, FakeJev(), parent_dir)
    child_jev = FakeJev(route={"high_risk": 0.9})
    result = jev_execute.execute(repo, parent_task, child_jev, run_dir(),
                                  parent_run=parent_dir, runner=lambda *a, **k: {
                                      "exit_code": 1, "log": str(a[2])
                                  })

    assert child_jev.calls == []
    assert result["action"] == "current_review"


def test_run_worker_is_reusable_without_git_or_jev_and_reply_has_no_tools(tmp_path):
    captured = {}

    def runner(argv, repo_path, log, timeout, stdin=None):
        captured["argv"] = argv
        report_path(argv).write_text(json.dumps({
            "status": "completed", "summary": "answered", "unresolved": []
        }))
        return {"argv": argv, "exit_code": 0, "log": str(log)}

    result = jev_execute.run_worker(
        tmp_path, task(), run_dir(), reply=True, runner=runner
    )

    assert result["failure"] is None
    assert result["worker_report"]["summary"] == "answered"
    assert "--skip-git-repo-check" in captured["argv"]
    instruction = captured["argv"][captured["argv"].index("-c") + 1:]
    assert any("Do not use tools" in value for value in instruction)


def test_failing_core_check_requires_current_review(repo):
    failing_check = [sys.executable, "-c", "raise SystemExit(4)"]

    result = jev_execute.execute(repo, task(failing_check), FakeJev(), run_dir(),
                                  runner=successful_runner)

    assert result["action"] == "current_review"
    assert "checks_failed_or_unavailable" in result["validation"]["reasons"]


def test_worker_prompt_does_not_expose_check_argv(repo):
    calls = []

    def runner(argv, repo_path, log, timeout, stdin=None):
        calls.append((argv, stdin))
        return successful_runner(argv, repo_path, log, timeout, stdin)

    check = [sys.executable, "-c", "from src.value import VALUE; assert VALUE == 2"]
    jev_execute.execute(repo, task(check), FakeJev(), run_dir(), runner=runner)

    assert calls
    argv, prompt = calls[0]
    assert "change VALUE to 2" in prompt
    assert "change VALUE to 2" not in " ".join(argv)


def test_parent_worker_retains_review_gate(repo):
    parent = run_dir()
    jev_execute.router.route(repo, task(), FakeJev(), parent)
    judge = FakeJev()
    result = jev_execute.execute(repo, task(), judge, run_dir(), parent_run=parent,
                                 runner=successful_runner)
    assert result['action'] == 'accept'
    assert result['policy']['post_model_review'] is True
    assert len(judge.calls) == 1
    assert 'architecture' not in judge.calls[0][1]


def test_disabled_parent_execution_does_not_launch_or_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(jev_execute.router, 'read_settings', lambda: {'enabled': False})
    def forbidden(*args, **kwargs):
        pytest.fail('disabled pipeline must not execute')
    monkeypatch.setattr(jev_execute.router, 'check_run', forbidden)
    result = jev_execute.execute(tmp_path, {}, None, tmp_path, parent_run=tmp_path/'missing', runner=forbidden)
    assert result['action'] == 'current'
    assert jev_execute.main(['/missing/task']) == 0
    assert json.loads(capsys.readouterr().out)['reasons'] == ['jev_disabled']
