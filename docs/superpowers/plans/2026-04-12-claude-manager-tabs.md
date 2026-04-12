# claude-manager tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `claude-manager tabs list` and `claude-manager tabs focus <id>` subcommands that discover and jump to kitty terminals running Claude/Codex.

**Architecture:** Read the existing `/tmp/feishu-bridge/registry.json` (populated by current kitty hooks), cross-reference live window IDs via `kitten @ ls` for activity filtering, and drive focus via `kitten @ focus-window --match id:...`. Zero changes to hooks or feishu-bridge — both continue to work unchanged.

**Tech Stack:** Python 3.10+, argparse, subprocess, dataclasses, pytest. No new dependencies (rich is already in via textual; we render tables manually to avoid a dep).

**Spec:** `docs/superpowers/specs/2026-04-12-claude-manager-tabs-design.md`

---

## File Structure

### New files

- `manager/src/claude_manager/tabs/__init__.py` — package marker, re-exports
- `manager/src/claude_manager/tabs/registry.py` — `TerminalInfo` dataclass, `load_registry()`, `_get_alive_windows()`, `list_alive_terminals()`
- `manager/src/claude_manager/tabs/kitty.py` — `focus_window()` subprocess wrapper
- `manager/src/claude_manager/tabs/cli.py` — argparse commands, table rendering, entry point `run(argv)`
- `manager/tests/test_tabs.py` — unit tests for all three modules

### Modified files

- `manager/src/claude_manager/cli.py` — add early `tabs` subcommand dispatch (before TUI/tmux checks)

### Notes on conventions

- **Use `kitten @` not `kitty @`** — matches existing `kitty_adapter.py` convention. Both work, but `kitten @` is the newer, preferred form.
- **Socket format** — stored as full `"unix:@mykitty-12345"` string in registry.json; passed directly to `kitten @ --to <socket>`.
- **All subprocess calls need timeouts** — 5s for `kitten @ ls`, 3s for `focus-window`. Never hang the CLI.
- **Single test file** `test_tabs.py` — matches existing `test_models.py` convention.

---

## Task 1: Package skeleton + TerminalInfo dataclass

**Files:**
- Create: `manager/src/claude_manager/tabs/__init__.py`
- Create: `manager/src/claude_manager/tabs/registry.py`
- Create: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing test**

Create `manager/tests/test_tabs.py`:

```python
"""Tests for claude-manager tabs subcommand."""

import time

from claude_manager.tabs.registry import TerminalInfo


class TestTerminalInfo:
    """TerminalInfo dataclass tests."""

    def test_project_name_from_cwd(self):
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="my-tab",
            cwd="/home/user/my-project",
            status="idle",
            agent_kind="claude",
            last_activity=0.0,
            registered_at=0.0,
        )
        assert info.project_name == "my-project"

    def test_project_name_fallback_to_cwd_when_empty(self):
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="my-tab",
            cwd="",
            status="idle",
            agent_kind="claude",
            last_activity=0.0,
            registered_at=0.0,
        )
        assert info.project_name == ""

    def test_idle_seconds_computed_from_now(self):
        now = time.time()
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="my-tab",
            cwd="/",
            status="idle",
            agent_kind="claude",
            last_activity=now - 120,
            registered_at=now - 200,
        )
        assert 119 <= info.idle_seconds <= 122

    def test_frozen_dataclass_rejects_mutation(self):
        import dataclasses
        info = TerminalInfo(
            window_id="1",
            socket="unix:@mykitty-1",
            tab_title="t",
            cwd="/",
            status="idle",
            agent_kind="claude",
            last_activity=0.0,
            registered_at=0.0,
        )
        try:
            info.status = "working"
            raised = False
        except dataclasses.FrozenInstanceError:
            raised = True
        assert raised, "TerminalInfo must be frozen"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd manager && pytest tests/test_tabs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_manager.tabs'`

- [ ] **Step 3: Create the package skeleton**

Create `manager/src/claude_manager/tabs/__init__.py`:

```python
"""Terminal discovery and jump commands for Claude/Codex kitty tabs."""
```

Create `manager/src/claude_manager/tabs/registry.py`:

```python
"""Registry reader for kitty terminals running Claude/Codex.

Reads /tmp/feishu-bridge/registry.json (written by existing kitty hooks)
and exposes a typed view of currently alive terminals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TerminalInfo:
    """Read-only snapshot of a kitty terminal running an AI agent."""

    window_id: str
    socket: str
    tab_title: str
    cwd: str
    status: str          # "working" / "waiting" / "completed" / "idle"
    agent_kind: str      # "claude" / "codex"
    last_activity: float
    registered_at: float

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    @property
    def project_name(self) -> str:
        return Path(self.cwd).name or self.cwd
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd manager && pytest tests/test_tabs.py::TestTerminalInfo -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/__init__.py \
        manager/src/claude_manager/tabs/registry.py \
        manager/tests/test_tabs.py
git commit -m "feat: add TerminalInfo dataclass for tabs subcommand"
```

---

## Task 2: load_registry function

**Files:**
- Modify: `manager/src/claude_manager/tabs/registry.py`
- Modify: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing tests**

Append to `manager/tests/test_tabs.py`:

```python
import json

from claude_manager.tabs import registry as registry_module
from claude_manager.tabs.registry import load_registry


class TestLoadRegistry:
    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            registry_module, "REGISTRY_PATH", tmp_path / "nothing.json"
        )
        assert load_registry() == {}

    def test_returns_empty_when_json_corrupt(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        p.write_text("not valid json")
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        assert load_registry() == {}

    def test_returns_empty_when_top_level_not_dict(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        p.write_text("[]")
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        assert load_registry() == {}

    def test_returns_parsed_dict_when_valid(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        payload = {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "my-tab",
                "cwd": "/home/user/proj",
                "status": "working",
                "agent_kind": "claude",
                "agent_name": "Claude",
                "registered_at": 100.0,
                "last_activity": 200.0,
            }
        }
        p.write_text(json.dumps(payload))
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        data = load_registry()
        assert "42" in data
        assert data["42"]["tab_title"] == "my-tab"
        assert data["42"]["status"] == "working"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestLoadRegistry -v`
Expected: FAIL with `ImportError: cannot import name 'load_registry'`

- [ ] **Step 3: Implement load_registry**

Add to `manager/src/claude_manager/tabs/registry.py` (after the TerminalInfo dataclass):

```python
import json
import logging

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path("/tmp/feishu-bridge/registry.json")


def load_registry() -> dict[str, dict]:
    """Read raw registry dict from disk.

    Returns empty dict if the file is missing, corrupt, or not a JSON object.
    Never raises.
    """
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("failed to read %s: %s", REGISTRY_PATH, e)
        return {}
    if not isinstance(data, dict):
        logger.warning("%s is not a JSON object, ignoring", REGISTRY_PATH)
        return {}
    return data
```

Make sure the `import json` and `import logging` are added near the top with other imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestLoadRegistry -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/registry.py manager/tests/test_tabs.py
git commit -m "feat: add load_registry reader with graceful error handling"
```

---

## Task 3: _get_alive_windows helper

**Files:**
- Modify: `manager/src/claude_manager/tabs/registry.py`
- Modify: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing tests**

Append to `manager/tests/test_tabs.py`:

```python
import subprocess as sp


class TestGetAliveWindows:
    def test_parses_kitten_ls_output(self, monkeypatch):
        fake_stdout = json.dumps([
            {
                "tabs": [
                    {
                        "title": "tab-one",
                        "windows": [
                            {"id": 10, "cwd": "/home/a"},
                            {"id": 11, "cwd": "/home/b"},
                        ],
                    },
                    {
                        "title": "tab-two",
                        "windows": [
                            {"id": 20, "cwd": "/home/c"},
                        ],
                    },
                ]
            }
        ])

        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 0, fake_stdout, "")

        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        result = registry_module._get_alive_windows("unix:@mykitty-1")
        assert set(result.keys()) == {"10", "11", "20"}
        assert result["10"]["tab_title"] == "tab-one"
        assert result["20"]["tab_title"] == "tab-two"
        assert result["10"]["cwd"] == "/home/a"

    def test_returns_empty_on_nonzero_exit(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 1, "", "connection refused")
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_returns_empty_on_timeout(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd=cmd, timeout=5)
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_returns_empty_when_kitten_missing(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("kitten")
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_returns_empty_on_malformed_json(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 0, "not-json", "")
        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        assert registry_module._get_alive_windows("unix:@mykitty-1") == {}

    def test_passes_socket_to_kitten(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return sp.CompletedProcess(cmd, 0, "[]", "")

        monkeypatch.setattr(registry_module.subprocess, "run", fake_run)
        registry_module._get_alive_windows("unix:@mykitty-999")
        assert captured["cmd"] == [
            "kitten", "@", "--to", "unix:@mykitty-999", "ls"
        ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestGetAliveWindows -v`
Expected: FAIL with `AttributeError: module 'claude_manager.tabs.registry' has no attribute '_get_alive_windows'`

- [ ] **Step 3: Implement _get_alive_windows**

Add to `manager/src/claude_manager/tabs/registry.py`:

```python
import subprocess

KITTEN_LS_TIMEOUT = 5.0


def _get_alive_windows(socket: str) -> dict[str, dict]:
    """Query `kitten @ ls` for a single socket and return live windows.

    Returns dict mapping window_id (str) -> {"tab_title": str, "cwd": str}.
    On any failure (nonzero exit, timeout, missing kitten, malformed JSON)
    returns an empty dict — never raises.
    """
    try:
        result = subprocess.run(
            ["kitten", "@", "--to", socket, "ls"],
            capture_output=True,
            text=True,
            timeout=KITTEN_LS_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("kitten @ ls failed for socket %s: %s", socket, e)
        return {}

    if result.returncode != 0:
        logger.debug(
            "kitten @ ls nonzero rc=%d for %s: %s",
            result.returncode, socket, result.stderr.strip(),
        )
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("kitten @ ls returned non-JSON for %s", socket)
        return {}

    alive: dict[str, dict] = {}
    for os_window in data:
        for tab in os_window.get("tabs", []):
            tab_title = tab.get("title", "")
            for win in tab.get("windows", []):
                wid = str(win.get("id", ""))
                if not wid:
                    continue
                alive[wid] = {
                    "tab_title": tab_title,
                    "cwd": win.get("cwd", ""),
                }
    return alive
```

Make sure `import subprocess` is added at the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestGetAliveWindows -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/registry.py manager/tests/test_tabs.py
git commit -m "feat: add _get_alive_windows helper for kitten @ ls parsing"
```

---

## Task 4: list_alive_terminals function

**Files:**
- Modify: `manager/src/claude_manager/tabs/registry.py`
- Modify: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing tests**

Append to `manager/tests/test_tabs.py`:

```python
from claude_manager.tabs.registry import list_alive_terminals


def _write_registry(path, entries):
    path.write_text(json.dumps(entries))


class TestListAliveTerminals:
    def test_empty_when_registry_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            registry_module, "REGISTRY_PATH", tmp_path / "absent.json"
        )
        assert list_alive_terminals() == []

    def test_filters_out_dead_windows(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "alive-tab-stale",
                "cwd": "/home/a",
                "status": "working",
                "agent_kind": "claude",
                "registered_at": 100.0,
                "last_activity": 200.0,
            },
            "99": {
                "window_id": "99",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "dead-tab",
                "cwd": "/home/b",
                "status": "idle",
                "agent_kind": "claude",
                "registered_at": 100.0,
                "last_activity": 150.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows",
            lambda socket: {
                "42": {"tab_title": "alive-tab-fresh", "cwd": "/home/a"},
            },
        )
        result = list_alive_terminals()
        assert len(result) == 1
        assert result[0].window_id == "42"

    def test_live_tab_title_overrides_stale_registry(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "stale-name",
                "cwd": "/home/a",
                "status": "working",
                "agent_kind": "claude",
                "registered_at": 100.0,
                "last_activity": 200.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows",
            lambda socket: {
                "42": {"tab_title": "fresh-name", "cwd": "/home/a"},
            },
        )
        result = list_alive_terminals()
        assert result[0].tab_title == "fresh-name"

    def test_sorted_by_last_activity_desc(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "1": {
                "window_id": "1", "kitty_socket": "unix:@mykitty-1",
                "tab_title": "old", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 100.0,
            },
            "2": {
                "window_id": "2", "kitty_socket": "unix:@mykitty-1",
                "tab_title": "middle", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 500.0,
            },
            "3": {
                "window_id": "3", "kitty_socket": "unix:@mykitty-1",
                "tab_title": "newest", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 900.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows",
            lambda socket: {
                "1": {"tab_title": "old", "cwd": "/"},
                "2": {"tab_title": "middle", "cwd": "/"},
                "3": {"tab_title": "newest", "cwd": "/"},
            },
        )
        result = list_alive_terminals()
        assert [t.window_id for t in result] == ["3", "2", "1"]

    def test_handles_multiple_sockets(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "1": {
                "window_id": "1", "kitty_socket": "unix:@mykitty-A",
                "tab_title": "a", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 100.0,
            },
            "2": {
                "window_id": "2", "kitty_socket": "unix:@mykitty-B",
                "tab_title": "b", "cwd": "/", "status": "idle",
                "agent_kind": "codex", "registered_at": 0.0,
                "last_activity": 200.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)

        socket_calls = []
        def fake_alive(socket):
            socket_calls.append(socket)
            return {
                "unix:@mykitty-A": {"1": {"tab_title": "a", "cwd": "/"}},
                "unix:@mykitty-B": {"2": {"tab_title": "b", "cwd": "/"}},
            }[socket]

        monkeypatch.setattr(registry_module, "_get_alive_windows", fake_alive)
        result = list_alive_terminals()
        assert len(result) == 2
        assert set(socket_calls) == {"unix:@mykitty-A", "unix:@mykitty-B"}

    def test_skips_entries_without_socket(self, tmp_path, monkeypatch):
        p = tmp_path / "reg.json"
        _write_registry(p, {
            "42": {
                "window_id": "42", "kitty_socket": "",
                "tab_title": "t", "cwd": "/", "status": "idle",
                "agent_kind": "claude", "registered_at": 0.0,
                "last_activity": 100.0,
            },
        })
        monkeypatch.setattr(registry_module, "REGISTRY_PATH", p)
        monkeypatch.setattr(
            registry_module, "_get_alive_windows", lambda s: {}
        )
        assert list_alive_terminals() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestListAliveTerminals -v`
Expected: FAIL with `ImportError: cannot import name 'list_alive_terminals'`

- [ ] **Step 3: Implement list_alive_terminals**

Add to `manager/src/claude_manager/tabs/registry.py`:

```python
def list_alive_terminals() -> list[TerminalInfo]:
    """Read registry and return currently alive TerminalInfo, sorted by recency.

    Workflow:
    1. Load raw registry.
    2. Group entries by socket.
    3. For each socket, call `_get_alive_windows` once to get live window ids.
    4. Filter out entries whose window_id is not in the live set.
    5. Use live tab_title when available; fall back to registry value.
    6. Sort by last_activity descending (most recent first).
    """
    raw = load_registry()
    if not raw:
        return []

    by_socket: dict[str, list[dict]] = {}
    for entry in raw.values():
        socket = entry.get("kitty_socket", "")
        if not socket:
            continue
        by_socket.setdefault(socket, []).append(entry)

    results: list[TerminalInfo] = []
    for socket, entries in by_socket.items():
        alive = _get_alive_windows(socket)
        for entry in entries:
            wid = str(entry.get("window_id", ""))
            if wid not in alive:
                continue
            live_tab_title = alive[wid].get("tab_title") or entry.get("tab_title", "")
            results.append(
                TerminalInfo(
                    window_id=wid,
                    socket=socket,
                    tab_title=live_tab_title,
                    cwd=entry.get("cwd", ""),
                    status=entry.get("status", "idle"),
                    agent_kind=entry.get("agent_kind", "claude"),
                    last_activity=float(entry.get("last_activity", 0)),
                    registered_at=float(entry.get("registered_at", 0)),
                )
            )

    results.sort(key=lambda t: t.last_activity, reverse=True)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestListAliveTerminals -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/registry.py manager/tests/test_tabs.py
git commit -m "feat: add list_alive_terminals with activity filtering"
```

---

## Task 5: kitty.focus_window helper

**Files:**
- Create: `manager/src/claude_manager/tabs/kitty.py`
- Modify: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing tests**

Append to `manager/tests/test_tabs.py`:

```python
from claude_manager.tabs import kitty as kitty_module
from claude_manager.tabs.kitty import focus_window


class TestFocusWindow:
    def test_success_invokes_kitten_with_correct_args(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "42")
        assert ok is True
        assert err == ""
        assert captured["cmd"] == [
            "kitten", "@", "--to", "unix:@mykitty-1",
            "focus-window", "--match", "id:42",
        ]

    def test_failure_returns_stderr(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 1, "", "no matching window")
        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "99")
        assert ok is False
        assert "no matching window" in err

    def test_failure_generic_message_when_stderr_empty(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 2, "", "")
        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "99")
        assert ok is False
        assert err  # non-empty message

    def test_timeout(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd=cmd, timeout=3)
        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "42")
        assert ok is False
        assert "timed out" in err

    def test_kitten_not_found(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("kitten")
        monkeypatch.setattr(kitty_module.subprocess, "run", fake_run)
        ok, err = focus_window("unix:@mykitty-1", "42")
        assert ok is False
        assert "not found" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestFocusWindow -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_manager.tabs.kitty'`

- [ ] **Step 3: Create the kitty module**

Create `manager/src/claude_manager/tabs/kitty.py`:

```python
"""Kitty window focus helper."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

FOCUS_TIMEOUT = 3.0


def focus_window(socket: str, window_id: str) -> tuple[bool, str]:
    """Focus a kitty window by id via `kitten @ focus-window`.

    Args:
        socket: kitty socket like "unix:@mykitty-12345"
        window_id: numeric kitty window id as string

    Returns:
        (success, error_message). error_message is empty on success.
    """
    cmd = [
        "kitten", "@", "--to", socket,
        "focus-window", "--match", f"id:{window_id}",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FOCUS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "kitten @ focus-window timed out"
    except FileNotFoundError:
        return False, "kitten command not found"

    if result.returncode != 0:
        err = result.stderr.strip()
        if not err:
            err = f"kitten exited with code {result.returncode}"
        return False, err
    return True, ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestFocusWindow -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/kitty.py manager/tests/test_tabs.py
git commit -m "feat: add focus_window helper for kitten @ focus-window"
```

---

## Task 6: format_time_ago helper

**Files:**
- Create: `manager/src/claude_manager/tabs/cli.py` (partial — helper only)
- Modify: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing tests**

Append to `manager/tests/test_tabs.py`:

```python
from claude_manager.tabs.cli import format_time_ago


class TestFormatTimeAgo:
    def test_recent(self):
        assert format_time_ago(0) == "刚刚"
        assert format_time_ago(59) == "刚刚"

    def test_minutes(self):
        assert format_time_ago(60) == "1分钟前"
        assert format_time_ago(180) == "3分钟前"
        assert format_time_ago(3599) == "59分钟前"

    def test_hours(self):
        assert format_time_ago(3600) == "1小时前"
        assert format_time_ago(7200) == "2小时前"

    def test_days(self):
        assert format_time_ago(86400) == "1天前"
        assert format_time_ago(172800) == "2天前"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestFormatTimeAgo -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_manager.tabs.cli'`

- [ ] **Step 3: Create cli.py with format_time_ago**

Create `manager/src/claude_manager/tabs/cli.py`:

```python
"""CLI for claude-manager tabs subcommand."""

from __future__ import annotations


def format_time_ago(seconds: float) -> str:
    """Format a duration in seconds as '刚刚' / 'N分钟前' / 'N小时前' / 'N天前'."""
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)}分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)}小时前"
    return f"{int(seconds // 86400)}天前"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestFormatTimeAgo -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/cli.py manager/tests/test_tabs.py
git commit -m "feat: add format_time_ago helper for tabs CLI"
```

---

## Task 7: tabs list command

**Files:**
- Modify: `manager/src/claude_manager/tabs/cli.py`
- Modify: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing tests**

Append to `manager/tests/test_tabs.py`:

```python
import time

from claude_manager.tabs import cli as cli_module
from claude_manager.tabs.cli import run
from claude_manager.tabs.registry import TerminalInfo


def _make_terminal(**overrides) -> TerminalInfo:
    defaults = dict(
        window_id="42",
        socket="unix:@mykitty-1",
        tab_title="my-tab",
        cwd="/home/user/my-project",
        status="working",
        agent_kind="claude",
        last_activity=time.time() - 30,
        registered_at=time.time() - 300,
    )
    defaults.update(overrides)
    return TerminalInfo(**defaults)


class TestListCommand:
    def test_empty_list_shows_hint(self, capsys, monkeypatch):
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])
        rc = run(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "没有活跃的终端" in out
        assert "/tmp/feishu-bridge/registry.json" in out

    def test_list_shows_columns(self, capsys, monkeypatch):
        t1 = _make_terminal(window_id="42", tab_title="first-tab")
        t2 = _make_terminal(
            window_id="18", tab_title="second-tab",
            status="waiting", cwd="/home/user/other-proj",
            last_activity=time.time() - 250,
        )
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [t1, t2])
        rc = run(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "42" in out
        assert "18" in out
        assert "first-tab" in out
        assert "second-tab" in out
        assert "my-project" in out
        assert "other-proj" in out
        assert "共 2 个活跃终端" in out

    def test_list_includes_header_row(self, capsys, monkeypatch):
        monkeypatch.setattr(
            cli_module, "list_alive_terminals",
            lambda: [_make_terminal()],
        )
        rc = run(["list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ID" in out
        assert "TAB" in out
        assert "PROJECT" in out
        assert "AGENT" in out
        assert "STATUS" in out
        assert "IDLE" in out

    def test_active_flag_filters_completed_and_idle(self, capsys, monkeypatch):
        working = _make_terminal(window_id="1", status="working")
        waiting = _make_terminal(window_id="2", status="waiting")
        idle = _make_terminal(window_id="3", status="idle")
        completed = _make_terminal(window_id="4", status="completed")
        monkeypatch.setattr(
            cli_module, "list_alive_terminals",
            lambda: [working, waiting, idle, completed],
        )
        rc = run(["list", "--active"])
        assert rc == 0
        out = capsys.readouterr().out
        # Only window ids 1 and 2 should appear in the ID column output lines.
        assert "共 2 个活跃终端" in out

    def test_json_flag_emits_parseable_json(self, capsys, monkeypatch):
        t = _make_terminal(window_id="42", tab_title="hello")
        monkeypatch.setattr(
            cli_module, "list_alive_terminals", lambda: [t]
        )
        rc = run(["list", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["window_id"] == "42"
        assert data[0]["tab_title"] == "hello"
        assert data[0]["project_name"] == "my-project"
        assert "idle_seconds" in data[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestListCommand -v`
Expected: FAIL with `ImportError: cannot import name 'run' from 'claude_manager.tabs.cli'`

- [ ] **Step 3: Implement list command in cli.py**

Replace the contents of `manager/src/claude_manager/tabs/cli.py` with:

```python
"""CLI for claude-manager tabs subcommand."""

from __future__ import annotations

import argparse
import json
import sys

from .registry import TerminalInfo, list_alive_terminals, load_registry


def format_time_ago(seconds: float) -> str:
    """Format a duration in seconds as '刚刚' / 'N分钟前' / 'N小时前' / 'N天前'."""
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)}分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)}小时前"
    return f"{int(seconds // 86400)}天前"


# ANSI color codes for status column (gracefully skipped when stdout is not a tty).
_STATUS_COLOR = {
    "working": "\033[32m",    # green
    "waiting": "\033[33m",    # yellow
    "completed": "\033[31m",  # red
    "idle": "\033[90m",       # gray
}
_RESET = "\033[0m"


def _colorize(text: str, status: str, use_color: bool) -> str:
    if not use_color:
        return text
    color = _STATUS_COLOR.get(status, "")
    return f"{color}{text}{_RESET}" if color else text


def _display_width(s: str) -> int:
    """Return the visual width of a string, treating CJK characters as width 2."""
    width = 0
    for ch in s:
        code = ord(ch)
        # Rough CJK unified ideograph range + common Chinese punctuation
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3000 <= code <= 0x303F
            or 0xFF00 <= code <= 0xFFEF
        ):
            width += 2
        else:
            width += 1
    return width


def _pad_right(s: str, target_width: int) -> str:
    padding = target_width - _display_width(s)
    return s + (" " * max(0, padding))


def _print_table(terminals: list[TerminalInfo], use_color: bool) -> None:
    if not terminals:
        print("没有活跃的终端。")
        print()
        print("提示:")
        print("  - 确认 kitty hook 已经安装（在 kitty tab 里运行 claude 后会自动注册）")
        print("  - 注册数据位于 /tmp/feishu-bridge/registry.json")
        return

    headers = ["ID", "TAB", "PROJECT", "AGENT", "STATUS", "IDLE"]
    rows = [
        [
            t.window_id,
            t.tab_title,
            t.project_name,
            t.agent_kind,
            t.status,
            format_time_ago(t.idle_seconds),
        ]
        for t in terminals
    ]

    # Compute column widths by display width, not character count.
    widths = [_display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_width(cell))

    def format_row(row: list[str]) -> str:
        return "  ".join(_pad_right(cell, widths[i]) for i, cell in enumerate(row))

    print(format_row(headers))
    for row, t in zip(rows, terminals):
        # Colorize the status cell in place after padding.
        status_padded = _pad_right(t.status, widths[4])
        status_colored = _colorize(status_padded, t.status, use_color)
        cells = [
            _pad_right(row[0], widths[0]),
            _pad_right(row[1], widths[1]),
            _pad_right(row[2], widths[2]),
            _pad_right(row[3], widths[3]),
            status_colored,
            row[5],  # idle column — last, no padding needed
        ]
        print("  ".join(cells))
    print()
    print(f"共 {len(terminals)} 个活跃终端")


def _print_json(terminals: list[TerminalInfo]) -> None:
    payload = [
        {
            "window_id": t.window_id,
            "socket": t.socket,
            "tab_title": t.tab_title,
            "cwd": t.cwd,
            "project_name": t.project_name,
            "agent_kind": t.agent_kind,
            "status": t.status,
            "last_activity": t.last_activity,
            "idle_seconds": t.idle_seconds,
        }
        for t in terminals
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_list(args: argparse.Namespace) -> int:
    terminals = list_alive_terminals()
    if args.active:
        terminals = [t for t in terminals if t.status in ("working", "waiting")]
    if args.json:
        _print_json(terminals)
    else:
        _print_table(terminals, use_color=sys.stdout.isatty())
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-manager tabs",
        description="管理正在运行 Claude/Codex 的 kitty 终端",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出所有活跃的终端")
    p_list.add_argument(
        "--active", action="store_true",
        help="仅显示 working/waiting 状态",
    )
    p_list.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式",
    )
    p_list.set_defaults(func=cmd_list)

    return parser


def run(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestListCommand -v`
Expected: PASS, 5 tests

Also re-run format_time_ago tests to confirm nothing broke:
Run: `cd manager && pytest tests/test_tabs.py::TestFormatTimeAgo -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/cli.py manager/tests/test_tabs.py
git commit -m "feat: add 'tabs list' command with --active and --json flags"
```

---

## Task 8: tabs focus command

**Files:**
- Modify: `manager/src/claude_manager/tabs/cli.py`
- Modify: `manager/tests/test_tabs.py`

- [ ] **Step 1: Write the failing tests**

Append to `manager/tests/test_tabs.py`:

```python
class TestFocusCommand:
    def test_focus_success_prints_tab_title(self, capsys, monkeypatch):
        monkeypatch.setattr(cli_module, "load_registry", lambda: {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "my-tab",
            }
        })
        monkeypatch.setattr(cli_module, "focus_window", lambda s, w: (True, ""))
        rc = run(["focus", "42"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "my-tab" in out
        assert "42" in out

    def test_focus_not_in_registry_prints_error_and_alive_list(
        self, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli_module, "load_registry", lambda: {})
        monkeypatch.setattr(
            cli_module, "list_alive_terminals",
            lambda: [_make_terminal(window_id="42", tab_title="something")],
        )
        rc = run(["focus", "99"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "未找到" in err
        assert "99" in err
        assert "42" in err
        assert "something" in err

    def test_focus_not_in_registry_with_empty_alive_list(
        self, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli_module, "load_registry", lambda: {})
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])
        rc = run(["focus", "99"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "未找到" in err

    def test_focus_kitten_failure_propagates_error(self, capsys, monkeypatch):
        monkeypatch.setattr(cli_module, "load_registry", lambda: {
            "42": {
                "window_id": "42",
                "kitty_socket": "unix:@mykitty-1",
                "tab_title": "my-tab",
            }
        })
        monkeypatch.setattr(
            cli_module, "focus_window", lambda s, w: (False, "no matching window")
        )
        rc = run(["focus", "42"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "no matching window" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestFocusCommand -v`
Expected: FAIL with argparse error `invalid choice: 'focus'` (because the focus subcommand isn't registered yet)

- [ ] **Step 3: Add cmd_focus and register the subparser**

Edit `manager/src/claude_manager/tabs/cli.py`. First add the import at the top (after existing imports):

```python
from .kitty import focus_window
```

Then add `cmd_focus` after `cmd_list`:

```python
def cmd_focus(args: argparse.Namespace) -> int:
    raw = load_registry()
    entry = raw.get(args.window_id)
    if not entry:
        print(
            f"错误: 未找到 window_id={args.window_id} 的终端。",
            file=sys.stderr,
        )
        alive = list_alive_terminals()
        if alive:
            print("", file=sys.stderr)
            print("当前活跃的终端:", file=sys.stderr)
            for t in alive:
                print(f"  {t.window_id}  {t.tab_title}", file=sys.stderr)
        return 1

    socket = entry.get("kitty_socket", "")
    ok, err = focus_window(socket, args.window_id)
    if not ok:
        print(f"错误: {err}", file=sys.stderr)
        return 1

    tab_title = entry.get("tab_title", "")
    print(f'切换到 "{tab_title}"（window_id={args.window_id}, socket={socket}）')
    return 0
```

Then update `_build_parser()` to register the focus subparser. After the `p_list.set_defaults(func=cmd_list)` line, add:

```python
    p_focus = sub.add_parser("focus", help="切换到指定 window_id 对应的 kitty 窗口")
    p_focus.add_argument("window_id", help="kitty window_id")
    p_focus.set_defaults(func=cmd_focus)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestFocusCommand -v`
Expected: PASS, 4 tests

Full suite sanity check:
Run: `cd manager && pytest tests/test_tabs.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/tabs/cli.py manager/tests/test_tabs.py
git commit -m "feat: add 'tabs focus' command with error diagnostics"
```

---

## Task 9: Wire tabs subcommand into main CLI

**Files:**
- Modify: `manager/src/claude_manager/cli.py`
- Modify: `manager/tests/test_tabs.py`

The key requirement: `tabs` subcommand must be routed **before** any TUI / tmux-inside-tmux checks, because it is a pure CLI utility that must work anywhere (including inside a tmux session).

- [ ] **Step 1: Write the failing test**

Append to `manager/tests/test_tabs.py`:

```python
import sys as sys_module


class TestMainCliIntegration:
    def test_main_routes_tabs_to_subcommand(self, capsys, monkeypatch):
        """main() should dispatch 'tabs' to tabs.cli.run before TUI checks."""
        from claude_manager import cli as main_cli

        monkeypatch.setattr(sys_module, "argv", ["claude-manager", "tabs", "list"])
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])

        rc = main_cli.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "没有活跃的终端" in out

    def test_main_routes_tabs_focus(self, capsys, monkeypatch):
        from claude_manager import cli as main_cli

        monkeypatch.setattr(
            sys_module, "argv",
            ["claude-manager", "tabs", "focus", "99"],
        )
        monkeypatch.setattr(cli_module, "load_registry", lambda: {})
        monkeypatch.setattr(cli_module, "list_alive_terminals", lambda: [])

        rc = main_cli.main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "未找到" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd manager && pytest tests/test_tabs.py::TestMainCliIntegration -v`
Expected: FAIL — main() currently doesn't recognize "tabs" as a subcommand; it will either try to parse it as an argparse argument or fall through to TUI launch logic.

- [ ] **Step 3: Add tabs dispatch to main cli.py**

Edit `manager/src/claude_manager/cli.py`. At the very top of `main()`, before the `parser = argparse.ArgumentParser(...)` line, add:

```python
def main():
    """主入口"""
    # Early dispatch: 'tabs' subcommand bypasses TUI/tmux checks entirely.
    if len(sys.argv) > 1 and sys.argv[1] == "tabs":
        from .tabs.cli import run
        return run(sys.argv[2:])

    parser = argparse.ArgumentParser(
        description='Claude Manager - 终端分屏 + tmux session 管理',
        # ... rest unchanged
```

Leave the rest of `main()` exactly as it was. The early return means `argparse` never sees `tabs` and never complains about it being an unknown argument.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd manager && pytest tests/test_tabs.py::TestMainCliIntegration -v`
Expected: PASS, 2 tests

Full suite sanity check:
Run: `cd manager && pytest tests/ -v`
Expected: All tests PASS (existing `test_models.py` + new `test_tabs.py`)

- [ ] **Step 5: Commit**

```bash
git add manager/src/claude_manager/cli.py manager/tests/test_tabs.py
git commit -m "feat: wire tabs subcommand into claude-manager entry point"
```

---

## Task 10: Manual end-to-end verification

This task is purely manual — no code changes. Its purpose is to verify the feature works in the real kitty environment, not just in unit tests.

**Prerequisites:**
- Running inside kitty with `allow_remote_control yes`
- `feishu-register.sh` hook installed (already the case in this repo)
- `claude-manager` installed in dev mode: `pip install -e manager/`

- [ ] **Step 1: Help text sanity check**

Run: `claude-manager tabs --help`
Expected: Shows usage with `list` and `focus` subcommands.

Run: `claude-manager tabs list --help`
Expected: Shows `--active` and `--json` options.

- [ ] **Step 2: List when no registry exists**

If no Claude has been run recently:
Run: `claude-manager tabs list`
Expected: "没有活跃的终端" + hint text.

- [ ] **Step 3: Populate registry by running Claude in a kitty tab**

Open 2-3 fresh kitty tabs. In each, `cd` to a different project dir and run `claude`. Issue at least one tool call (e.g., ask "list files") to trigger the `on-tool-use` hook. This populates `/tmp/feishu-bridge/registry.json`.

- [ ] **Step 4: List should show the terminals**

Run: `claude-manager tabs list`
Expected: Table with one row per kitty tab, showing window_id, tab_title, project (= cwd basename), agent, status, idle time. Most recently active should be first.

Verify:
- [ ] The tab_titles shown match the current kitty tab titles (not stale)
- [ ] The `共 N 个活跃终端` count matches reality
- [ ] Colors render on status column (working/waiting green/yellow/...)

- [ ] **Step 5: Close one tab; list should reflect it**

Close one of the kitty tabs (`Ctrl+Shift+W`).
Run: `claude-manager tabs list`
Expected: Closed tab no longer appears — activity filtering via `kitten @ ls` removed it.

- [ ] **Step 6: Focus command jumps to target tab**

From a different kitty tab, pick an ID from the list output:
Run: `claude-manager tabs focus <id>`
Expected: kitty focus immediately switches to that tab/window. Confirmation message printed.

- [ ] **Step 7: Focus error path**

Run: `claude-manager tabs focus 9999`
Expected: Error message to stderr mentioning "未找到", list of currently active terminals shown, exit code 1.

Verify:
```bash
claude-manager tabs focus 9999; echo "rc=$?"
```
Expected: `rc=1`

- [ ] **Step 8: --active filter**

Run: `claude-manager tabs list --active`
Expected: Only `working` / `waiting` terminals. If no Claude is currently mid-tool-call, the list may be empty.

- [ ] **Step 9: --json output**

Run: `claude-manager tabs list --json | jq .`
Expected: Valid JSON, one object per alive terminal, all expected fields present.

- [ ] **Step 10: Works inside tmux**

Attach to an existing tmux session or run `tmux new`. Inside tmux:
Run: `claude-manager tabs list`
Expected: Works normally — not blocked by the "tmux inside tmux" launcher check (which applies only to the TUI path).

- [ ] **Step 11: Final commit**

If everything passed and no code changes were needed, no additional commit. If you had to tweak anything (polish, bugs caught during manual testing), commit with:

```bash
git add -A
git commit -m "fix: <whatever was fixed during manual verification>"
```

---

## Self-Review Checklist (author-run before handoff)

- [x] **Spec coverage:**
  - Background/motivation → Task 1 introduces the package
  - Shared-contract principle → Tasks 2-4 read existing registry.json path unchanged
  - Zero-change-to-hooks/feishu-bridge → No task touches `kitty-enhance/hooks/` or `kitty-enhance/feishu-bridge/`
  - YAGNI → Tasks only implement list+focus; no tag/rename/log/open/kill
  - Activity filtering → Task 3 + Task 4
  - Live tab_title overrides stale registry → Task 4 test `test_live_tab_title_overrides_stale_registry`
  - CLI UX (list table, --active, --json, empty hint) → Task 7
  - CLI UX (focus success + not-found + kitten failure) → Task 8
  - Error handling table (registry missing, corrupt, kitten failure, etc.) → Covered across Tasks 2, 3, 5
  - Runs inside tmux without TUI check → Task 9 step 3 (early dispatch) + Task 10 step 10
  - Testing strategy → Each task has unit tests; Task 10 is manual verification

- [x] **No placeholders:** No TBD/TODO/implement-later strings found.

- [x] **Type consistency:**
  - `TerminalInfo.window_id` is `str` everywhere (matches registry.json key format)
  - `focus_window` returns `tuple[bool, str]` consistently in Task 5 and usage in Task 8
  - `list_alive_terminals` returns `list[TerminalInfo]` in Task 4 and consumed in Task 7
  - `run(argv: list[str]) -> int` signature consistent in Task 7 and Task 9

- [x] **Each task is self-contained:** Code blocks in each task include everything needed to paste and run. No forward references to undefined symbols.
