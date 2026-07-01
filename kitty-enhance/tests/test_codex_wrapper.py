"""Tests for the PATH-level Codex wrapper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path


WRAPPER_SRC = Path(__file__).resolve().parent.parent / "bin" / "codex"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _install_fake_environment(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    real_dir = tmp_path / "real"
    scripts_dir = home / ".config" / "kitty" / "scripts"
    home.mkdir()
    bin_dir.mkdir()
    real_dir.mkdir()
    scripts_dir.mkdir(parents=True)

    wrapper = bin_dir / "codex"
    shutil.copy2(WRAPPER_SRC, wrapper)
    wrapper.chmod(0o755)

    real_out = tmp_path / "real.json"
    monitor_out = tmp_path / "monitor.json"

    _write_executable(
        real_dir / "codex",
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

Path(os.environ["TMP_REAL_OUT"]).write_text(
    json.dumps({"argv": sys.argv[1:]}),
    encoding="utf-8",
)
""",
    )

    _write_executable(
        scripts_dir / "codex-event-monitor.py",
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

Path(os.environ["TMP_MONITOR_OUT"]).write_text(
    json.dumps({
        "argv": sys.argv[1:],
        "kitty_window_id": os.environ.get("KITTY_WINDOW_ID"),
        "kitty_listen_on": os.environ.get("KITTY_LISTEN_ON"),
    }),
    encoding="utf-8",
)
time.sleep(0.1)
""",
    )

    env = os.environ.copy()
    env.pop("KITTY_WINDOW_ID", None)
    env.pop("KITTY_LISTEN_ON", None)
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{real_dir}:{env['PATH']}",
            "TMP_REAL_OUT": str(real_out),
            "TMP_MONITOR_OUT": str(monitor_out),
            "PWD": str(tmp_path / "workspace"),
        }
    )
    return wrapper, env, real_out, monitor_out


def test_wrapper_executes_real_codex_and_starts_monitor(tmp_path):
    wrapper, env, real_out, monitor_out = _install_fake_environment(tmp_path)
    env["KITTY_WINDOW_ID"] = "42"
    env["KITTY_LISTEN_ON"] = "unix:@sock"

    subprocess.run([str(wrapper), "--cd", "~/demo", "--version"], check=True, env=env)
    time.sleep(0.2)

    assert json.loads(real_out.read_text(encoding="utf-8"))["argv"] == ["--cd", "~/demo", "--version"]

    monitor = json.loads(monitor_out.read_text(encoding="utf-8"))
    assert monitor["kitty_window_id"] == "42"
    assert monitor["kitty_listen_on"] == "unix:@sock"
    assert monitor["argv"] == [
        "--window-id",
        "42",
        "--kitty-socket",
        "unix:@sock",
        "--cwd",
        os.path.realpath(str(Path(env["HOME"]) / "demo")),
    ]


def test_wrapper_skips_monitor_outside_kitty(tmp_path):
    wrapper, env, real_out, monitor_out = _install_fake_environment(tmp_path)

    subprocess.run([str(wrapper), "--version"], check=True, env=env)
    time.sleep(0.2)

    assert json.loads(real_out.read_text(encoding="utf-8"))["argv"] == ["--version"]
    assert not monitor_out.exists()
