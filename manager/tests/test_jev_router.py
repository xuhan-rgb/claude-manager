import importlib.util
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


ROUTER_PATH = Path(__file__).parents[2] / "tools" / "jev_router.py"
SPEC = importlib.util.spec_from_file_location("jev_router", ROUTER_PATH)
jev_router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jev_router)


def command(*code):
    return [sys.executable, "-c", " ".join(code)]


def args(**overrides):
    values = {"timeout": 10}
    values.update(overrides)
    return SimpleNamespace(**values)


def task(checks=None, allowed_paths=None):
    return {"task": "make the bounded change", "context": "test context",
            "acceptance_criteria": ["the check passes"],
            "allowed_paths": allowed_paths or ["src"],
            "checks": checks or [command("pass")]}


def run_dir():
    return Path(tempfile.mkdtemp(prefix="jev-test-run-"))


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "item.txt").write_text("before\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "initial"], check=True)
    return tmp_path


class FakeJev:
    def __init__(self, route=None, verify=None):
        self.route = route or {key: 0 for key in jev_router.ROUTE_QUESTIONS}
        self.verify = verify or {key: 0 for key in jev_router.VERIFY_QUESTIONS}

    def assess(self, state, questions):
        if "architecture" in questions:
            return {key: self.route.get(key, 0) for key in questions}
        return {key: self.verify.get(key, 0) for key in questions}

    def close(self):
        pass


def completed_report():
    return {"status": "completed", "summary": "done", "unresolved": []}


def routed(repo, task_value=None, jev=None):
    directory = run_dir()
    result = jev_router.route(repo, task_value or task(), jev or FakeJev(), directory)
    return directory, result


def test_gate_rejects_missing_nan_inf_and_bool_values():
    for value in ({}, {"architecture": math.nan}, {"architecture": math.inf}, {"architecture": True}):
        assert jev_router.gate(value, {"architecture": 0.2}) == ["architecture:missing_or_invalid"]


@pytest.mark.parametrize("mutate, message", [
    (lambda value: value.update(checks=["echo unsafe"]), "argv array"),
    (lambda value: value.update(allowed_paths=["../outside"]), "bounded"),
    (lambda value: value.update(allowed_paths=["/absolute"]), "bounded"),
])
def test_load_task_rejects_shell_commands_and_path_escapes(tmp_path, mutate, message):
    value = task()
    mutate(value)
    path = tmp_path / "task.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match=message):
        jev_router.load_task(path)


def test_validate_reports_failing_command(repo):
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    evidence = jev_router.validate(args(), repo, task([command("sys.exit(3)")]), base, run_dir(), "worker")
    assert "checks_failed_or_unavailable" in evidence["reasons"]


def test_validate_reports_scope_violation(repo):
    (repo / "outside.txt").write_text("changed\n")
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    evidence = jev_router.validate(args(), repo, task(), base, run_dir(), "worker")
    assert "out_of_scope_changes" in evidence["reasons"]


def test_validate_reports_check_induced_edits(repo):
    edit = command("from pathlib import Path; Path('src/item.txt').write_text('changed')")
    base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    evidence = jev_router.validate(args(), repo, task([edit]), base, run_dir(), "worker")
    assert "checks_changed_worktree" in evidence["reasons"]


@pytest.mark.parametrize("risk, action", [(False, "luna_worker"), (True, "current")])
def test_route_selects_current_or_luna_worker(repo, risk, action):
    signals = {key: 0 for key in jev_router.ROUTE_QUESTIONS}
    if risk:
        signals["broad_context"] = 1
    _, result = routed(repo, jev=FakeJev(route=signals))
    assert result["action"] == action
    assert result["initially_dirty"] is False


def test_route_never_launches_model(repo, monkeypatch):
    monkeypatch.setattr(jev_router, "run_command", pytest.fail)
    _, result = routed(repo)
    assert result["action"] == "luna_worker"


def test_parent_route_skips_jev_and_records_parent(repo, monkeypatch):
    parent_dir, _ = routed(repo)
    child = task(allowed_paths=["src/item.txt"])
    monkeypatch.setattr(jev_router, "assess", pytest.fail)
    result = jev_router.route(repo, child, None, run_dir(), parent_run=parent_dir)
    assert result["routing"]["source"] == "current_session_decomposition"
    assert result["parent_run"] == str(parent_dir.resolve())


def test_parent_route_rejects_wrong_repo_and_scope(repo, tmp_path):
    parent_dir, _ = routed(repo)
    manifest = json.loads((parent_dir / "result.json").read_text())
    manifest["repo"] = str(tmp_path / "different-repo")
    (parent_dir / "result.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="same repository"):
        jev_router.route(repo, task(), None, run_dir(), parent_run=parent_dir)

    parent_dir, _ = routed(repo, task(allowed_paths=["src/item.txt"]))
    with pytest.raises(ValueError, match="parent task scope"):
        jev_router.route(repo, task(allowed_paths=["src"]), None, run_dir(), parent_run=parent_dir)


def test_check_records_real_passing_checks(repo):
    directory, result = routed(repo)
    checked = jev_router.check_run(args(), directory, completed_report())
    assert checked["validation"]["checks"][0]["exit_code"] == 0
    assert checked["validation"]["reasons"] == []
    assert json.loads((directory / "result.json").read_text())["worker_report"] == completed_report()


def test_verify_accepts_safe_completed_worker(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())
    result = jev_router.verify_run(directory, FakeJev())
    assert result["action"] == "accept"
    assert result["review_reasons"] == []


def test_verification_questions_cover_each_criterion_with_explicit_criteria():
    value = task()
    value["acceptance_criteria"] = ["first behavior", "second behavior"]
    questions = jev_router.verification_questions(value)
    assert set(questions) == {
        "criterion_0::violation", "criterion_0::unverified",
        "criterion_1::violation", "criterion_1::unverified",
        "unnecessary_change",
    }
    for spec in questions.values():
        assert spec["instructions"]
        assert set(spec["criteria"]) == {"true", "false"}
        assert spec["criteria"]["true"] and spec["criteria"]["false"]


def test_verification_gate_does_not_average_away_one_error():
    questions = jev_router.verification_questions(task())
    signals = {key: 0 for key in questions}
    signals["criterion_0::violation"] = 0.8
    assert jev_router.verification_gate(signals, questions, 0.3, 0.7) == [
        "criterion_0::violation:error_flag"
    ]


def test_verification_gate_distinguishes_uncertainty_and_invalid_values():
    questions = jev_router.verification_questions(task())
    signals = {key: 0 for key in questions}
    signals["criterion_0::violation"] = 0.5
    assert jev_router.verification_gate(signals, questions, 0.3, 0.7) == [
        "criterion_0::violation:uncertain"
    ]
    signals["criterion_0::violation"] = math.nan
    assert jev_router.verification_gate(signals, questions, 0.3, 0.7) == [
        "criterion_0::violation:missing_or_invalid"
    ]


def test_old_manifest_uses_conservative_verification_fallback(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())
    manifest = json.loads((directory / "result.json").read_text())
    manifest["policy"].pop("verify_accept_max")
    manifest["policy"].pop("verify_flag_above")
    (directory / "result.json").write_text(json.dumps(manifest))
    result = jev_router.verify_run(directory, FakeJev())
    assert result["action"] == "accept"


@pytest.mark.parametrize("setup, reason", [(lambda repo, directory: None, "validation_missing")])
def test_verify_missing_or_failed_check_requires_current_review(repo, setup, reason):
    directory, _ = routed(repo)
    setup(repo, directory)
    result = jev_router.verify_run(directory, FakeJev())
    assert result["action"] == "current_review"
    assert reason in result["review_reasons"]


def test_verify_failed_check_requires_current_review(repo):
    directory, _ = routed(repo, task([command("sys.exit(3)")]))
    jev_router.check_run(args(), directory, completed_report())
    result = jev_router.verify_run(directory, FakeJev())
    assert result["action"] == "current_review"
    assert "checks_failed_or_unavailable" in result["review_reasons"]


def test_verify_stale_check_requires_current_review(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())
    (repo / "src" / "item.txt").write_text("changed\n")
    result = jev_router.verify_run(directory, FakeJev())
    assert result["action"] == "current_review"
    assert "evidence_stale" in result["review_reasons"]


def test_verify_rechecks_freshness_after_prior_accept(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())
    assert jev_router.verify_run(directory, FakeJev())["action"] == "accept"
    (repo / "src" / "item.txt").write_text("changed after accept\n")
    result = jev_router.verify_run(directory, FakeJev())
    assert result["action"] == "current_review"
    assert "evidence_stale" in result["review_reasons"]


def test_verify_detects_change_during_jev_callback(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())

    class EditingJev(FakeJev):
        def assess(self, state, questions):
            (repo / "src" / "item.txt").write_text("changed during review\n")
            return super().assess(state, questions)

    result = jev_router.verify_run(directory, EditingJev())
    assert result["action"] == "current_review"
    assert "evidence_stale" in result["review_reasons"]


def test_verify_missing_jev_requires_current_review(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())
    result = jev_router.verify_run(directory, None)
    assert result["action"] == "current_review"
    assert any(reason.startswith("jev_unavailable:") for reason in result["review_reasons"])


def test_verify_dirty_baseline_requires_current_review(repo):
    (repo / "src" / "item.txt").write_text("dirty\n")
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())
    result = jev_router.verify_run(directory, FakeJev())
    assert "preexisting_changes_require_review" in result["review_reasons"]


def test_verify_worker_incomplete_requires_current_review(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory,
                         {"status": "needs_help", "summary": "blocked", "unresolved": ["x"]})
    result = jev_router.verify_run(directory, FakeJev())
    assert "worker_incomplete" in result["review_reasons"]


def test_verify_require_review_forces_current_review(repo):
    directory, _ = routed(repo)
    jev_router.check_run(args(), directory, completed_report())
    result = jev_router.verify_run(directory, FakeJev(), require_review=True)
    assert result["action"] == "current_review"
    assert "shadow_mode_requires_review" in result["review_reasons"]


def test_main_fake_jev_route_check_verify_roundtrip(repo, monkeypatch, capsys):
    task_path = Path(tempfile.mkdtemp(prefix="jev-task-")) / "task.json"
    task_path.write_text(json.dumps(task()))
    monkeypatch.setattr(jev_router, "Jev", lambda model: FakeJev())
    assert jev_router.main(["route", str(task_path), "--repo", str(repo)]) == 0
    captured = capsys.readouterr()
    routed_output = json.loads(captured.out)
    assert jev_router.ROUTE_QUESTIONS["architecture"] in captured.err
    assert "结果: P(是)=0.000" in captured.err
    assert "test context" not in captured.err
    assert "make the bounded change" not in captured.err
    assert "委派原生 Luna 子代理" in captured.err
    directory = Path(routed_output["run_dir"])
    report_path = task_path.parent / "worker-report.json"
    report_path.write_text(json.dumps(completed_report()))
    assert jev_router.main(["check", str(directory), "--report", str(report_path)]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "current_review"
    assert jev_router.main(["verify", str(directory)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["action"] == "accept"
    assert "criterion_0::violation" not in captured.err
    assert "Does the actual diff or check output contradict" in captured.err
    assert "test context" not in captured.err
    assert "接受结果，跳过额外模型审核" in captured.err


def test_main_parent_route_skips_jev_and_validates_parent_scope(repo, monkeypatch, capsys):
    parent_dir, _ = routed(repo, task(allowed_paths=["src/item.txt"]))
    task_path = Path(tempfile.mkdtemp(prefix="jev-task-")) / "task.json"
    task_path.write_text(json.dumps(task(allowed_paths=["src/item.txt"])))
    monkeypatch.setattr(jev_router, "Jev", pytest.fail)
    assert jev_router.main([
        "route", str(task_path), "--repo", str(repo), "--parent-run", str(parent_dir)
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "luna_worker"

    wrong_task = task(allowed_paths=["src"])
    task_path.write_text(json.dumps(wrong_task))
    assert jev_router.main([
        "route", str(task_path), "--repo", str(repo), "--parent-run", str(parent_dir)
    ]) == 2
    assert json.loads(capsys.readouterr().out)["action"] == "current"


def test_live_switches_preserve_delegated_review(repo, monkeypatch):
    settings = {"enabled": True, "entry": False, "print": True}
    monkeypatch.setattr(jev_router, 'read_settings', lambda: settings)
    class CountingJev(FakeJev):
        calls = 0
        def assess(self, state, questions):
            self.calls += 1
            return super().assess(state, questions)
    judge = CountingJev()
    assert jev_router.route(repo, task(), judge, run_dir())['action'] == 'current'
    assert judge.calls == 0
    directory = run_dir()
    assert jev_router.route(repo, task(), judge, directory, delegated=True)['action'] == 'luna_worker'
    assert judge.calls == 0
    jev_router.check_run(args(), directory, completed_report())
    assert jev_router.verify_run(directory, judge)['action'] == 'accept'
    assert judge.calls == 1
    settings['enabled'] = False
    result = jev_router.verify_run(directory, judge)
    assert result['action'] == 'current_review'
    assert 'jev_disabled' in result['review_reasons']
    assert judge.calls == 1


def test_register_cli_never_constructs_jev(repo, monkeypatch, capsys):
    manifest = run_dir() / 'task.json'
    manifest.write_text(json.dumps(task()))
    monkeypatch.setattr(jev_router, 'Jev', pytest.fail)
    assert jev_router.main(['register', str(manifest), '--repo', str(repo)]) == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'luna_worker'


def test_existing_client_obeys_master_off(monkeypatch):
    monkeypatch.setattr(jev_router, 'read_settings', lambda: {'enabled': False})
    judge = object.__new__(jev_router.Jev)
    judge.client = SimpleNamespace(system_one=lambda **kw: pytest.fail('must not call SDK'))
    with pytest.raises(RuntimeError, match='jev_disabled'):
        judge.assess({}, {})


def test_router_script_cli_entrypoint():
    result = subprocess.run([sys.executable, str(ROUTER_PATH), '--help'],
                            capture_output=True, text=True, check=True)
    assert 'register' in result.stdout
    assert 'verify' in result.stdout


@pytest.mark.parametrize('command,extra', [('route', []), ('register', []), ('check', ['--report', '/missing/report']), ('verify', [])])
def test_disabled_cli_bypasses_entire_pipeline(monkeypatch, capsys, command, extra):
    monkeypatch.setattr(jev_router, 'read_settings', lambda: {'enabled': False})
    monkeypatch.setattr(jev_router, 'Jev', pytest.fail)
    assert jev_router.main([command, '/missing/input'] + extra) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['reasons'] == ['jev_disabled']
    assert result['action'] in ('current', 'current_review')
