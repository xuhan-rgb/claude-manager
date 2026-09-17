"""Read the latest local user task for a Claude or Codex terminal."""

from __future__ import annotations

import json
import os
from pathlib import Path


MAX_SUMMARY_LENGTH = 72


def clean_task_summary(value: str | None) -> str:
    """Return a short, single-line task label without prompt scaffolding."""
    if not value:
        return ""

    for raw_line in str(value).splitlines():
        line = " ".join(raw_line.strip().split())
        if not line or line in {"No prompt", "[Request interrupted by user]"}:
            continue
        if line.startswith(("<permissions instructions>", "# AGENTS.md instructions")):
            continue
        if len(line) > MAX_SUMMARY_LENGTH:
            return line[: MAX_SUMMARY_LENGTH - 3].rstrip() + "..."
        return line
    return ""


def _normalized_path(value: str) -> str:
    """Normalize a local path without requiring it to exist."""
    return os.path.normpath(os.path.realpath(os.path.expanduser(value)))


def _project_specificity(path: str, project: str) -> int:
    """Return the matched project depth, or -1 when it is unrelated."""
    try:
        cwd = _normalized_path(path)
        root = _normalized_path(project)
    except (TypeError, ValueError):
        return -1
    if cwd != root and not cwd.startswith(root + os.sep):
        return -1
    return len(Path(root).parts)


def _same_path(left: str, right: str) -> bool:
    try:
        return _normalized_path(left) == _normalized_path(right)
    except (TypeError, ValueError):
        return False


def _claude_task(cwd: str) -> str:
    candidates: list[tuple[int, str, str, str]] = []
    root = Path.home() / ".claude" / "projects"
    if not root.exists():
        return ""

    for index_path in root.glob("*/sessions-index.json"):
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in data.get("entries", []):
            if not isinstance(entry, dict):
                continue
            specificity = _project_specificity(cwd, entry.get("projectPath", ""))
            if specificity < 0:
                continue
            summary = clean_task_summary(entry.get("summary"))
            first_prompt = clean_task_summary(entry.get("firstPrompt"))
            if summary or first_prompt:
                modified = str(entry.get("modified", entry.get("fileMtime", "")))
                candidates.append((specificity, modified, summary, first_prompt))

    if not candidates:
        return ""
    _, _, summary, first_prompt = max(candidates, key=lambda item: item[:2])
    return summary or first_prompt


def _codex_task(cwd: str) -> str:
    root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser() / "sessions"
    if not root.exists():
        return ""

    candidates: list[tuple[float, Path]] = []
    for session_path in root.rglob("*.jsonl"):
        try:
            stat = session_path.stat()
            with session_path.open(encoding="utf-8", errors="replace") as handle:
                first_line = handle.readline()
            meta = json.loads(first_line)
        except (OSError, json.JSONDecodeError):
            continue
        payload = meta.get("payload") or {}
        if meta.get("type") == "session_meta" and _same_path(cwd, payload.get("cwd", "")):
            candidates.append((stat.st_mtime, session_path))

    for _, session_path in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            with session_path.open(encoding="utf-8", errors="replace") as handle:
                messages = []
                for line in handle:
                    event = json.loads(line)
                    payload = event.get("payload") or {}
                    if event.get("type") == "event_msg" and payload.get("type") == "user_message":
                        messages.append(payload.get("message", ""))
        except (OSError, json.JSONDecodeError):
            continue
        for message in reversed(messages):
            summary = clean_task_summary(message)
            if summary:
                return summary
    return ""


def task_summary_for(cwd: str, agent_kind: str, fallback: str = "") -> str:
    """Find a task label locally, falling back to a meaningful Tab title."""
    if agent_kind.lower() == "claude":
        summary = _claude_task(cwd)
    elif agent_kind.lower() == "codex":
        summary = _codex_task(cwd)
    else:
        summary = ""
    return summary or clean_task_summary(fallback) or "未记录任务"
