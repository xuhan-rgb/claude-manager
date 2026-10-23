import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
from jev_dispatch import dispatch
import jev_state as states


def ready(tmp_path, mode="reply"):
    path = tmp_path / "state.json"
    states.save(path, {"state": "luna_ready", "mode": mode, "cwd": str(tmp_path),
                       "prompt": "hello", "reason": ""})
    return path


def worker(*args, **kwargs):
    return {"failure": None, "execution": {"exit_code": 0},
            "worker_report": {"status": "completed", "summary": "Hello!", "unresolved": []}}


def test_non_git_reply_runs_once_without_reviewer(tmp_path):
    path = ready(tmp_path)
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs)
        return worker()
    first = dispatch(path, sandbox="workspace-write", worker=run)
    second = dispatch(path, worker=run)
    assert first == second
    assert len(calls) == 1
    assert calls[0]["sandbox"] == "read-only"
    assert calls[0]["reply"] is True
    assert first["state"] == "done"
    assert first["post_model_review"] is False


@pytest.mark.parametrize("exit_code,expected", [(0, "done"), (4, "failed")])
def test_code_check_is_executed_in_non_git_directory(tmp_path, exit_code, expected):
    path = ready(tmp_path, "task")
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"task": "bounded request", "context": "fixture",
        "acceptance_criteria": ["check passes"], "allowed_paths": ["value.py"],
        "checks": [[sys.executable, "-c", f"raise SystemExit({exit_code})"]]}))
    result = dispatch(path, task, worker=worker)
    assert result["state"] == expected
    assert result["checks"][0]["exit_code"] == exit_code


def test_running_lock_and_saved_running_state_prevent_duplicate(tmp_path):
    path = ready(tmp_path)
    with states.locked(path):
        with pytest.raises(BlockingIOError):
            dispatch(path, worker=worker)
    state = states.read(path)
    state["state"] = "luna_running"
    states.save(path, state)
    with pytest.raises(RuntimeError):
        dispatch(path, worker=worker)


def test_failure_never_returns_success_and_is_not_retried(tmp_path):
    path = ready(tmp_path)
    def fail(*args, **kwargs):
        return {"failure": "worker_failed"}
    result = dispatch(path, worker=fail)
    assert result["state"] == "failed"
    assert dispatch(path, worker=lambda *a, **k: pytest.fail("must not retry")) == result


def test_master_off_returns_pending_work_to_current(tmp_path, monkeypatch):
    import jev_router
    monkeypatch.setattr(jev_router, 'read_settings', lambda: {'enabled': False})
    path = ready(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('disabled dispatcher must not launch Luna')
    result = dispatch(path, worker=forbidden)
    assert result['state'] == 'current_required'
    assert result['reason'] == 'jev_disabled'
