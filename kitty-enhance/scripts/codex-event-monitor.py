#!/usr/bin/env python3
"""Monitor Codex session events and trigger Kitty notifications.

This script is launched by the shell wrapper in `shell-functions.sh`.
It only handles Codex windows and never touches Claude hooks.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SESSION_IDLE_GRACE_SECONDS = 8.0
SESSION_DISCOVERY_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.5
SUPPORTED_ORIGINATORS = {"codex-tui", "codex_exec"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--kitty-socket", required=True)
    parser.add_argument("--cwd", required=True)
    return parser.parse_args()


def parse_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


@dataclass
class SessionCandidate:
    path: Path
    meta: dict
    mtime: float


class CodexEventMonitor:
    def __init__(self, window_id: str, kitty_socket: str, cwd: str):
        self.window_id = window_id
        self.kitty_socket = kitty_socket
        self.cwd = os.path.realpath(os.path.expanduser(cwd))
        self.start_time = time.time()
        self.codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        self.sessions_root = self.codex_home / "sessions"
        self.scripts_dir = Path(__file__).resolve().parent
        self.working_script = self.scripts_dir / "codex-working.sh"
        self.completed_script = self.scripts_dir / "codex-completed.sh"
        self.session_path: Path | None = None
        self.session_offset = 0
        self.session_last_activity = self.start_time
        self.processed_events: set[tuple[str, str, str]] = set()

    def run(self) -> int:
        while True:
            if self.session_path is None:
                candidate = self._discover_session()
                if candidate is not None:
                    self.session_path = candidate.path
                    self._drain_session(initial=True)

            else:
                self._drain_session(initial=False)

            codex_running = self._window_has_codex_process()
            idle_seconds = time.time() - self.session_last_activity

            if self.session_path is None and not codex_running:
                if time.time() - self.start_time >= SESSION_DISCOVERY_TIMEOUT_SECONDS:
                    return 0

            if self.session_path is not None and not codex_running and idle_seconds >= SESSION_IDLE_GRACE_SECONDS:
                return 0

            time.sleep(POLL_INTERVAL_SECONDS)

    def _discover_session(self) -> SessionCandidate | None:
        if not self.sessions_root.exists():
            return None

        candidates: list[SessionCandidate] = []
        threshold = self.start_time - 2.0
        for path in self.sessions_root.rglob("*.jsonl"):
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < threshold:
                continue

            meta = self._read_session_meta(path)
            if not meta:
                continue

            originator = str(meta.get("originator", "")).lower()
            if originator and originator not in SUPPORTED_ORIGINATORS:
                continue

            session_cwd = meta.get("cwd", "")
            if session_cwd and os.path.realpath(os.path.expanduser(session_cwd)) != self.cwd:
                continue

            session_ts = parse_timestamp(meta.get("timestamp"))
            if session_ts and session_ts < self.start_time - 5.0:
                continue

            candidates.append(SessionCandidate(path=path, meta=meta, mtime=stat.st_mtime))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (parse_timestamp(item.meta.get("timestamp")), item.mtime), reverse=True)
        return candidates[0]

    def _read_session_meta(self, path: Path) -> dict | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                line = handle.readline()
        except OSError:
            return None

        if not line:
            return None

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None

        if obj.get("type") != "session_meta":
            return None
        return obj.get("payload") or {}

    def _drain_session(self, initial: bool) -> None:
        if self.session_path is None:
            return

        try:
            with self.session_path.open("r", encoding="utf-8") as handle:
                if not initial:
                    handle.seek(self.session_offset)
                lines = handle.readlines()
                self.session_offset = handle.tell()
        except OSError:
            return

        if lines:
            self.session_last_activity = time.time()

        for raw_line in lines:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        if event.get("type") != "event_msg":
            return

        payload = event.get("payload") or {}
        event_type = payload.get("type")
        if event_type not in {"task_started", "task_complete"}:
            return

        event_ts = parse_timestamp(event.get("timestamp"))
        if event_ts and event_ts < self.start_time - 1.0:
            return

        turn_id = str(payload.get("turn_id", ""))
        event_key = (str(self.session_path), turn_id, event_type)
        if event_key in self.processed_events:
            return
        self.processed_events.add(event_key)

        if event_type == "task_started":
            self._run_script(self.working_script)
            return

        completed_message = payload.get("last_agent_message") or ""
        extra_env = {"CM_COMPLETED_MESSAGE": completed_message}
        self._run_script(self.completed_script, extra_env=extra_env)

    def _run_script(self, script: Path, extra_env: dict[str, str] | None = None) -> None:
        if not script.exists():
            return

        env = os.environ.copy()
        env["KITTY_WINDOW_ID"] = self.window_id
        env["KITTY_LISTEN_ON"] = self.kitty_socket
        env["PWD"] = self.cwd
        if extra_env:
            env.update(extra_env)

        try:
            subprocess.run([str(script)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            return

    def _window_has_codex_process(self) -> bool:
        try:
            result = subprocess.run(
                ["kitty", "@", "--to", self.kitty_socket, "ls"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return False

        if result.returncode != 0 or not result.stdout:
            return False

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False

        for os_window in data:
            for tab in os_window.get("tabs", []):
                for window in tab.get("windows", []):
                    if str(window.get("id", "")) != self.window_id:
                        continue
                    for process in window.get("foreground_processes", []):
                        cmdline = process.get("cmdline") or []
                        for token in cmdline:
                            basename = os.path.basename(str(token)).lower()
                            if basename == "codex" or basename.startswith("codex-"):
                                return True
        return False


def main() -> int:
    args = parse_args()
    monitor = CodexEventMonitor(
        window_id=args.window_id,
        kitty_socket=args.kitty_socket,
        cwd=args.cwd,
    )
    return monitor.run()


if __name__ == "__main__":
    sys.exit(main())
