#!/usr/bin/env python3
"""Periodic Kitty snapshots using a user systemd timer."""

from __future__ import annotations

import argparse
import contextlib
import io
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

UNIT = "kitty-tab-backup"
SPEC = importlib.util.spec_from_file_location("session_snapshot", Path(__file__).with_name("session-snapshot.py"))
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


def kitty_windows(socket: str) -> list[dict]:
    result = subprocess.run(
        ["kitty", "@", "--to", socket, "ls"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return json.loads(result.stdout)


def select_window(windows: list[dict], window_id: str) -> dict:
    for window in windows:
        if any(str(pane.get("id")) == window_id for tab in window.get("tabs", []) for pane in tab.get("windows", [])):
            return window
    raise ValueError("找不到当前 Kitty 窗口，请在需要备份的 Kitty 终端中运行")


def atomic_write(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_backup(window: dict, directory: Path, name: str, automatic: bool = True) -> Path:
    if not re.fullmatch(r"[\w.-]+", name) or name in {".", ".."}:
        raise ValueError("保存名称只能包含字母、数字、下划线、点或连字符")
    if not window.get("tabs"):
        raise ValueError("Kitty 窗口没有 Tab，未写入备份")
    diagnostics = io.StringIO()
    with contextlib.redirect_stderr(diagnostics):
        content = snapshot.generate_session([window], name=name)
    print(diagnostics.getvalue(), end="", file=sys.stderr)
    warnings = [
        line.strip() for line in diagnostics.getvalue().splitlines()
        if "no session-id" in line or "no jsonl" in line
    ]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.session"
    atomic_write(path, content)
    meta = {
        "name": name, "saved_at": datetime.now().isoformat(timespec="seconds"),
        "tabs": len(window["tabs"]),
        "windows": sum(len(tab.get("windows", [])) for tab in window["tabs"]),
        "automatic": automatic,
    }
    atomic_write(directory / f"{name}.meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    if warnings:
        print(f"提示：{len(warnings)} 个 AI 窗口未保存可恢复的对话 ID，恢复时可能启动新对话：")
        for warning in warnings:
            print(f"  {warning}")
    return path


def process_start(pid: str) -> str:
    # Protect against a later Kitty process reusing the same PID/window IDs.
    fields = (Path("/proc") / pid / "stat").read_text().rsplit(")", 1)[1].split()
    return fields[19]


def start_backup(args, directory: Path) -> None:
    if not re.fullmatch(r"[1-9]\d*(?:s|m|h)", args.interval):
        raise ValueError("备份周期格式为正整数加 s/m/h，例如 30s、10m、1h")
    window_id = os.environ.get("KITTY_WINDOW_ID", "")
    pid = os.environ.get("KITTY_PID", "")
    if not window_id or (not pid and not args.once):
        raise ValueError("请在需要备份的 Kitty 终端中运行 tab-save")
    socket = os.environ.get("KITTY_LISTEN_ON", "unix:@mykitty")
    window = select_window(kitty_windows(socket), window_id)
    if args.once:
        print(f"已保存：{save_backup(window, directory, args.name, automatic=False)}")
        return
    identity = process_start(pid)
    command = [
        "systemd-run", "--user", f"--unit={UNIT}", "--collect",
        f"--on-active={args.interval}", f"--on-unit-active={args.interval}",
        "--timer-property=AccuracySec=1s",
    ]
    for key in ("HOME", "PATH", "CODEX_HOME", "CLAUDE_DEFAULT_FLAGS"):
        if key in os.environ:
            command.append(f"--setenv={key}={os.environ[key]}")
    command += [
        sys.executable, str(Path(__file__).resolve()), "run",
        "--socket", socket, "--os-window-id", str(window["id"]),
        "--kitty-pid", pid, "--kitty-start", identity,
        "--directory", str(directory), "--name", args.name,
    ]
    # Write the first snapshot before enabling the timer; failed snapshots
    # leave an existing backup schedule untouched.
    path = save_backup(window, directory, args.name)
    # Reconfiguring start replaces this user's previous backup timer.
    subprocess.run(["systemctl", "--user", "stop", f"{UNIT}.timer", f"{UNIT}.service"], capture_output=True)
    subprocess.run(command, check=True)
    print(
        f"已保存：{args.name}（{len(window['tabs'])} tabs）\n"
        f"周期保存已开启：每 {args.interval} 更新，仅覆盖最后一份\n"
        "  执行方式：后台执行，不占用当前终端\n"
        f"  文件：{path}\n"
        f"  状态：tab-backup status\n"
        f"  恢复：tab-restore {args.name}\n"
        "  停止：tab-backup stop"
    )


def restore_session(path: Path) -> None:
    needs_daemon = False
    for line in path.read_text().splitlines():
        if not line.lstrip().startswith("launch "):
            continue
        args = shlex.split(line)
        if not args or args[0] != "launch":
            continue
        for index, arg in enumerate(args[1:], 1):
            if not snapshot.is_codex([arg]):
                continue
            options = args[index + 1:]
            if any(
                option.startswith("--remote=unix://") or (
                    option == "--remote" and i + 1 < len(options)
                    and options[i + 1].startswith("unix://")
                ) for i, option in enumerate(options)
            ):
                needs_daemon = True
                break
    if needs_daemon:
        print("正在启动 Codex app-server daemon…", flush=True)
        env = os.environ.copy()
        # Daemon management must not start this window's Kitty monitors.
        env.pop("KITTY_WINDOW_ID", None)
        env.pop("KITTY_LISTEN_ON", None)
        subprocess.run(
            ["codex", "app-server", "daemon", "start"],
            env=env, stdout=subprocess.DEVNULL, check=True,
        )
        print("Codex daemon 已就绪，开始恢复终端", flush=True)
    subprocess.run(["kitty", "--session", str(path), "--detach"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="配置 Kitty 当前窗口的定时备份；每个用户一个任务")
    commands = parser.add_subparsers(dest="command", required=True)
    default_directory = os.environ.get("KITTY_ENHANCE_SESSION_DIR", str(Path.home() / ".config/kitty-enhance/sessions"))
    for name in ("start", "run", "restore"):
        sub = commands.add_parser(name)
        sub.add_argument("--directory", type=Path, default=Path(default_directory))
        if name == "restore":
            sub.add_argument("--session-file", type=Path)
        if name == "start":
            sub.add_argument("name", nargs="?", default="auto")
            sub.add_argument("--once", action="store_true")
        if name == "run":
            sub.add_argument("--name", required=True)
        if name == "start":
            sub.add_argument("--interval", default="10m")
        if name == "run":
            for option in ("socket", "os-window-id", "kitty-pid", "kitty-start"):
                sub.add_argument("--" + option, required=True)
    commands.add_parser("status")
    commands.add_parser("stop")
    args = parser.parse_args()
    try:
        if args.command == "start":
            start_backup(args, args.directory.expanduser().resolve())
        elif args.command == "run":
            try:
                alive = process_start(args.kitty_pid) == args.kitty_start
            except FileNotFoundError:
                alive = False
            if not alive:
                print("目标 Kitty 已关闭，本轮跳过保存；后台定时任务保留")
                return 0
            windows = kitty_windows(args.socket)
            window = next((window for window in windows if str(window.get("id")) == args.os_window_id), None)
            if window is None:
                print("目标 Kitty 窗口已关闭，本轮跳过保存；后台定时任务保留")
                return 0
            print(f"已备份：{save_backup(window, args.directory, args.name)}")
        elif args.command == "restore":
            if args.session_file is not None:
                path = args.session_file
            else:
                backups = []
                for meta_path in args.directory.glob("*.meta.json"):
                    try:
                        meta = json.loads(meta_path.read_text())
                        path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".session")
                        if meta.get("automatic") is True and path.is_file():
                            backups.append((meta["saved_at"], path))
                    except (OSError, ValueError, KeyError):
                        continue
                if not backups:
                    raise ValueError("没有周期备份；可用 tab-list 查看手动保存的快照")
                path = max(backups, key=lambda backup: backup[0])[1]
            restore_session(path)
            print(f"已恢复：{path.stem}（新 Kitty 窗口）")
        elif args.command == "stop":
            subprocess.run(["systemctl", "--user", "stop", f"{UNIT}.timer", f"{UNIT}.service"], check=True)
            print("已停止自动备份，已有快照保留")
        else:
            subprocess.run(["systemctl", "--user", "list-timers", "--all", f"{UNIT}.timer"], check=True)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"错误：{error}", file=sys.stderr)
        if args.command == "start" and not args.once:
            print("周期保存未成功启用；可用 tab-save <name> --once 仅保存一次。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
