#!/usr/bin/env python3
"""Keep each Kitty tab named after its most recently focused AI window."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


POLL_INTERVAL_SECONDS = 0.5
EMPTY_GRACE_POLLS = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kitty-socket", required=True)
    return parser.parse_args()


def _is_ai_name(name: str) -> bool:
    name = name.lower()
    return name in {"claude", "codex"} or name.startswith(("claude-", "codex-"))


def is_ai_window(window: dict) -> bool:
    for process in window.get("foreground_processes", []):
        for index, token in enumerate(process.get("cmdline") or []):
            token = str(token)
            if _is_ai_name(os.path.basename(token)) and (index == 0 or "/" in token):
                return True
    return False


def select_ai_window(tab: dict) -> dict | None:
    ai_windows = {
        str(window.get("id")): window
        for window in tab.get("windows", [])
        if is_ai_window(window)
    }
    if not ai_windows:
        return None

    for window in ai_windows.values():
        if window.get("is_focused"):
            return window
    for window_id in tab.get("active_window_history", []):
        selected = ai_windows.get(str(window_id))
        if selected is not None:
            return selected
    return next(iter(ai_windows.values()))


def ai_window_title(window: dict) -> str:
    live_title = str(window.get("title") or "").strip()
    if live_title:
        return live_title
    cwd = str(window.get("cwd") or "")
    if cwd:
        return Path(cwd).name or cwd
    return "AI"


@dataclass(frozen=True)
class TitleAction:
    tab_id: int
    title: str | None


class TabTitleTracker:
    def __init__(self) -> None:
        self.managed_tabs: set[int] = set()

    def plan(self, kitty_data: list[dict]) -> tuple[list[TitleAction], bool]:
        actions: list[TitleAction] = []
        existing_tabs: set[int] = set()
        has_ai = False

        for os_window in kitty_data:
            for tab in os_window.get("tabs", []):
                tab_id = int(tab["id"])
                existing_tabs.add(tab_id)
                selected = select_ai_window(tab)
                if selected is None:
                    if tab_id in self.managed_tabs:
                        actions.append(TitleAction(tab_id=tab_id, title=None))
                        self.managed_tabs.remove(tab_id)
                    continue

                has_ai = True
                self.managed_tabs.add(tab_id)
                title = ai_window_title(selected)
                if tab.get("title") != title:
                    actions.append(TitleAction(tab_id=tab_id, title=title))

        self.managed_tabs.intersection_update(existing_tabs)
        return actions, has_ai


class AiTabTitleMonitor:
    def __init__(self, kitty_socket: str):
        self.kitty_socket = kitty_socket
        socket_hash = hashlib.md5(kitty_socket.encode("utf-8")).hexdigest()[:8]
        self.lock_path = Path(f"/tmp/kitty-ai-tab-title-{socket_hash}.lock")
        self.tracker = TabTitleTracker()

    def run(self) -> int:
        with self.lock_path.open("w", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0

            empty_polls = 0
            while True:
                kitty_data = self._list_windows()
                if kitty_data is None:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                actions, has_ai = self.tracker.plan(kitty_data)
                for action in actions:
                    self._apply(action)

                empty_polls = 0 if has_ai else empty_polls + 1
                if empty_polls >= EMPTY_GRACE_POLLS:
                    return 0
                time.sleep(POLL_INTERVAL_SECONDS)

    def _list_windows(self) -> list[dict] | None:
        try:
            result = subprocess.run(
                ["kitty", "@", "--to", self.kitty_socket, "ls"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
        return None

    def _apply(self, action: TitleAction) -> None:
        command = [
            "kitty",
            "@",
            "--to",
            self.kitty_socket,
            "set-tab-title",
            "--match",
            f"id:{action.tab_id}",
        ]
        if action.title is not None:
            command.append(action.title)
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def main() -> int:
    args = parse_args()
    return AiTabTitleMonitor(args.kitty_socket).run()


if __name__ == "__main__":
    raise SystemExit(main())
