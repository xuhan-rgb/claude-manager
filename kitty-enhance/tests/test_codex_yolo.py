"""Portable installation and shared-daemon launch contract."""

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def environment(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    codex = bin_dir / "codex"
    codex.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["YOLO_TEST_LOG"], "a") as log:
    log.write(json.dumps({"args": args, "window": os.getenv("KITTY_WINDOW_ID"),
                          "socket": os.getenv("KITTY_LISTEN_ON"),
                          "auth": os.getenv("YOLO_TEST_AUTH")}) + "\\n")
if "--help" in args:
    print("--remote" if not os.getenv("YOLO_TEST_OLD") else "old CLI")
elif args == ["app-server", "daemon", "start"]:
    if os.getenv("YOLO_TEST_FAIL"):
        sys.exit(7)
    print(os.getenv("YOLO_TEST_RESPONSE", '{"socketPath":"/tmp/test daemon.sock"}'))
else:
    sys.exit(int(os.getenv("YOLO_TEST_EXIT", "0")))
''')
    codex.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "SHELL": "/bin/bash",
        "YOLO_TEST_LOG": str(log),
        "KITTY_WINDOW_ID": "42",
        "KITTY_LISTEN_ON": "unix:@test",
    }
    return home, bin_dir, log, env


def launch(env, *args):
    return subprocess.run(
        ["bash", str(ROOT / "bin/codex-yolo"), *args],
        env=env, capture_output=True, text=True,
    )


@pytest.mark.parametrize("with_auth", [False, True])
def test_daemon_then_remote_with_arguments_and_exit_status(environment, with_auth):
    _, bin_dir, log, env = environment
    if with_auth:
        auth = bin_dir / "codex-auth"
        auth.write_text('#!/bin/bash\n[[ $1 == run && $2 == -- ]] || exit 99\n'
                        'shift 2\nexport YOLO_TEST_AUTH=1\nexec codex "$@"\n')
        auth.chmod(0o755)
    env["YOLO_TEST_EXIT"] = "23"
    result = launch(env, "--cd", "/tmp/a b", "hello world")
    assert result.returncode == 23, result.stderr
    daemon, tui = [json.loads(line) for line in log.read_text().splitlines()]
    assert daemon["args"] == ["app-server", "daemon", "start"]
    assert daemon["window"] is None and daemon["socket"] is None
    assert tui["window"] == "42" and tui["socket"] == "unix:@test"
    assert tui["args"] == [
        "-p", "yolo",
        "--remote", "unix:///tmp/test daemon.sock", "--cd", "/tmp/a b", "hello world",
    ]
    assert daemon["auth"] == tui["auth"] == ("1" if with_auth else None)


@pytest.mark.parametrize("response", ['{}', 'invalid json', '{"socketPath":null}', '{"socketPath":""}'])
def test_invalid_daemon_response_stops_launch(environment, response):
    _, _, log, env = environment
    env["YOLO_TEST_RESPONSE"] = response
    result = launch(env)
    assert result.returncode != 0
    assert "invalid daemon response" in result.stderr
    assert len(log.read_text().splitlines()) == 1


def test_daemon_failure_is_propagated(environment):
    _, _, log, env = environment
    env["YOLO_TEST_FAIL"] = "1"
    assert launch(env).returncode == 7
    assert len(log.read_text().splitlines()) == 1


def test_help_does_not_start_daemon(environment):
    _, _, log, env = environment
    assert launch(env, "--help").returncode == 0
    assert json.loads(log.read_text())["args"] == ["--help"]


def test_install_from_any_directory_is_repeatable_and_overrides_old_function(environment, tmp_path):
    home, _, log, env = environment
    old_rc = "alias codex-yolo='false'\nunalias codex-yolo\ncodex-yolo() { return 99; }\n"
    (home / ".bashrc").write_text(old_rc)
    (home / ".zshrc").write_text("# existing zsh config\n")
    installer = ["bash", str(ROOT / "install.sh"), "--codex-only"]
    subprocess.run(installer, env=env, cwd=tmp_path, check=True, capture_output=True)
    profile = home / ".codex/yolo.config.toml"
    config = home / ".codex/config.toml"
    assert 'approval_policy = "never"' in config.read_text()
    assert 'sandbox_mode = "danger-full-access"' in config.read_text()
    assert "approval_policy" not in profile.read_text()
    assert "sandbox_mode" not in profile.read_text()
    profile.write_text('# custom profile\nmodel = "my-model"\n')
    first_rc = (home / ".bashrc").read_text()
    subprocess.run(installer, env=env, cwd=tmp_path, check=True, capture_output=True)
    assert (home / ".bashrc").read_text() == first_rc
    assert (home / ".bashrc.before-codex-yolo").read_text() == old_rc
    assert (home / ".zshrc").read_text().count("# >>> kitty-enhance codex-yolo >>>") == 1
    assert profile.read_text() == '# custom profile\nmodel = "my-model"\n'
    assert not (home / ".config/kitty").exists()
    assert not (home / ".claude").exists()
    log.unlink()
    result = subprocess.run(
        ["bash", "-c", 'source "$HOME/.bashrc"; codex-yolo "hello world"'],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(log.read_text().splitlines()[-1])["args"][-1] == "hello world"


def test_install_rejects_cli_without_remote_before_writing(environment, tmp_path):
    home, _, _, env = environment
    env["YOLO_TEST_OLD"] = "1"
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--codex-only"],
        env=env, cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "--remote support" in result.stderr
    assert not (home / ".local/bin/codex-yolo").exists()


def test_default_directory_is_callers_cwd(environment, tmp_path):
    _, _, log, env = environment
    cwd = tmp_path / "project with spaces"
    cwd.mkdir()
    result = subprocess.run(
        ["bash", str(ROOT / "bin/codex-yolo"), "hello"],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    args = json.loads(log.read_text().splitlines()[-1])["args"]
    assert args[-3:] == ["-C", str(cwd), "hello"]


@pytest.mark.parametrize("options", [
    ["-C", "/tmp/other"], ["--cd", "/tmp/other"],
    ["--cd=/tmp/other"], ["-C/tmp/other"],
])
def test_explicit_directory_is_preserved(environment, options):
    _, _, log, env = environment
    result = launch(env, *options)
    assert result.returncode == 0, result.stderr
    args = json.loads(log.read_text().splitlines()[-1])["args"]
    assert args[4:] == options


@pytest.mark.parametrize("options", [[], ["resume"], ["resume", "--last"],
                                       ["resume", "thread-id"]])
def test_remote_resume_has_no_explicit_permission_flags(environment, options):
    _, _, log, env = environment
    result = launch(env, *options)
    assert result.returncode == 0, result.stderr
    args = json.loads(log.read_text().splitlines()[-1])["args"]
    assert args == ["-p", "yolo", "--remote", "unix:///tmp/test daemon.sock",
                    "-C", os.getcwd(), *options]


def test_install_migrates_permissions_and_preserves_other_settings(environment, tmp_path):
    home, _, _, env = environment
    codex_home = home / ".codex"
    codex_home.mkdir()
    config = codex_home / "config.toml"
    old_config = ('model = "base-model"\napproval_policy = "on-request" # approvals\n'
                  'sandbox_mode = "workspace-write"\n\n[tui]\nmouse = true\n')
    config.write_text(old_config)
    profile = codex_home / "yolo.config.toml"
    old_profile = ('# custom profile\nmodel = "my-model"\napproval_policy = "never"\n'
                   'sandbox_mode = "danger-full-access"\n\n'
                   '[sandbox_workspace_write]\nnetwork_access = true\n\n'
                   '[mcp_servers.example]\nenabled = false\n')
    profile.write_text(old_profile)
    installer = ["bash", str(ROOT / "install-codex-yolo.sh")]
    subprocess.run(installer, env=env, cwd=tmp_path, check=True, capture_output=True)
    expected_config = old_config.replace('"on-request"', '"never"').replace(
        '"workspace-write"', '"danger-full-access"')
    expected_profile = ('# custom profile\nmodel = "my-model"\n\n'
                        '[mcp_servers.example]\nenabled = false\n')
    assert config.read_text() == expected_config
    assert profile.read_text() == expected_profile
    assert config.with_name("config.toml.before-codex-yolo").read_text() == old_config
    assert profile.with_name("yolo.config.toml.before-codex-yolo").read_text() == old_profile
    subprocess.run(installer, env=env, cwd=tmp_path, check=True, capture_output=True)
    assert config.read_text() == expected_config
    assert profile.read_text() == expected_profile
    assert config.with_name("config.toml.before-codex-yolo").read_text() == old_config
    assert profile.with_name("yolo.config.toml.before-codex-yolo").read_text() == old_profile


@pytest.mark.parametrize("permission", [
    'approvals_reviewer = "user"\n',
    'default_permissions = "custom"\n',
    '"sandbox_mode" = "danger-full-access"\n',
    'network.enabled = true\n',
    '[permissions.custom]\nallow = true\n',
    '["network"]\nenabled = true\n',
    '[sandbox_workspace_write]\nnetwork_access = true\n',
])
def test_install_removes_all_resume_permission_override_keys(environment, permission):
    home, _, _, env = environment
    codex_home = home / ".codex"
    codex_home.mkdir()
    profile = codex_home / "yolo.config.toml"
    profile.write_text('model = "my-model"\n' + permission + '[tui]\nmouse = true\n')
    subprocess.run(["bash", str(ROOT / "install-codex-yolo.sh")], env=env,
                   check=True, capture_output=True)
    assert profile.read_text() == 'model = "my-model"\n[tui]\nmouse = true\n'
