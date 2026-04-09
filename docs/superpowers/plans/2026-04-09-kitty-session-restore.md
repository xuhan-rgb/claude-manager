# Kitty Session Save/Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `session-save`/`session-restore` shell commands to kitty-enhance that snapshot and restore Kitty terminal state (tabs, splits, CWDs, commands).

**Architecture:** `session-save` calls `kitty @ ls` and pipes the JSON into a Python script (`session-snapshot.py`) that generates a Kitty-native session file. `session-restore` launches a new Kitty instance with `kitty --session <file>`. Shell functions in `shell-functions.sh` wire everything together.

**Tech Stack:** Bash (shell functions), Python 3.10+ (JSON parsing / session file generation), Kitty Remote Control API.

---

## File Structure

| Action | File                                          | Responsibility                                    |
|--------|-----------------------------------------------|---------------------------------------------------|
| Create | `kitty-enhance/scripts/session-snapshot.py`   | Parse `kitty @ ls` JSON → emit Kitty session file |
| Modify | `kitty-enhance/shell-functions.sh` (line 233) | Add session-save/restore/list/delete + aliases     |
| Create | `kitty-enhance/tests/test_session_snapshot.py`| Unit tests for the Python snapshot script          |

---

### Task 1: Python snapshot script — core parsing

**Files:**
- Create: `kitty-enhance/tests/test_session_snapshot.py`
- Create: `kitty-enhance/scripts/session-snapshot.py`

- [ ] **Step 1: Write failing tests for session file generation**

Create `kitty-enhance/tests/test_session_snapshot.py`:

```python
"""Tests for session-snapshot.py"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "session-snapshot.py")


def run_snapshot(kitty_ls_json: str) -> str:
    """Run session-snapshot.py with given JSON on stdin, return stdout."""
    result = subprocess.run(
        [sys.executable, SCRIPT],
        input=kitty_ls_json,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    return result.stdout


def make_window(cwd: str, cmdline: list[str]) -> dict:
    """Helper to create a minimal kitty window dict."""
    return {
        "cwd": cwd,
        "foreground_processes": [{"cmdline": cmdline}],
    }


def make_tab(title: str, layout: str, windows: list[dict]) -> dict:
    return {"title": title, "layout": layout, "windows": windows}


def make_kitty_ls(tabs: list[dict]) -> str:
    return json.dumps([{"tabs": tabs}])


class TestSingleTab:
    def test_shell_only_tab(self):
        """A tab with one bash window should produce new_tab + layout + cd."""
        ls_json = make_kitty_ls([
            make_tab("myterm", "stack", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab myterm" in output
        assert "layout stack" in output
        assert "cd /home/user" in output
        # Shell windows should NOT have an explicit launch command
        assert "launch" not in output

    def test_claude_tab(self):
        """A tab running claude should produce launch claude."""
        ls_json = make_kitty_ls([
            make_tab("Claude Code", "tall", [
                make_window("/mnt/data/project", ["claude", "--dangerously-skip-permissions"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab Claude Code" in output
        assert "cd /mnt/data/project" in output
        assert "launch claude" in output
        # Should NOT preserve flags
        assert "--dangerously-skip-permissions" not in output


class TestMultiWindow:
    def test_tab_with_claude_and_shells(self):
        """A tab with claude + 2 shells: first window implicit, extra windows use launch --type=window."""
        ls_json = make_kitty_ls([
            make_tab("work", "tall", [
                make_window("/mnt/data/proj", ["claude"]),
                make_window("/mnt/data", ["/bin/bash"]),
                make_window("/home/user", ["/bin/zsh"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        lines = output.strip().split("\n")
        # First window: cd + launch claude
        assert "cd /mnt/data/proj" in output
        assert "launch claude" in output
        # Extra shell windows use launch --type=window
        type_window_lines = [l for l in lines if "launch --type=window" in l]
        assert len(type_window_lines) == 2

    def test_non_shell_command(self):
        """A window running a non-shell, non-claude command should preserve full cmdline."""
        ls_json = make_kitty_ls([
            make_tab("files", "stack", [
                make_window("/home/user", ["nautilus", "/home/user/Documents"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "launch nautilus /home/user/Documents" in output


class TestMultipleTabs:
    def test_two_tabs(self):
        """Multiple tabs each produce a new_tab block."""
        ls_json = make_kitty_ls([
            make_tab("tab1", "tall", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
            make_tab("tab2", "stack", [
                make_window("/mnt/data", ["claude"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert output.count("new_tab") == 2
        assert "new_tab tab1" in output
        assert "new_tab tab2" in output


class TestEdgeCases:
    def test_empty_foreground_processes(self):
        """Window with no foreground_processes should be treated as shell."""
        ls_json = make_kitty_ls([
            make_tab("empty", "stack", [
                {"cwd": "/tmp", "foreground_processes": []},
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "cd /tmp" in output
        assert "launch" not in output

    def test_unicode_tab_title(self):
        """Unicode in tab title should be preserved."""
        ls_json = make_kitty_ls([
            make_tab("✳ 调试面板", "tall", [
                make_window("/home/user", ["/bin/bash"]),
            ]),
        ])
        output = run_snapshot(ls_json)
        assert "new_tab ✳ 调试面板" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/data/claude-manager && python3 -m pytest kitty-enhance/tests/test_session_snapshot.py -v`
Expected: FAIL — `session-snapshot.py` does not exist yet.

- [ ] **Step 3: Implement session-snapshot.py**

Create `kitty-enhance/scripts/session-snapshot.py`:

```python
#!/usr/bin/env python3
"""Parse `kitty @ ls` JSON and generate a Kitty session file.

Usage: kitty @ ls | python3 session-snapshot.py > output.session
"""

import json
import sys
from datetime import datetime

SHELLS = {"bash", "zsh", "sh", "fish", "dash", "ksh", "csh", "tcsh"}


def is_shell(cmdline: list[str]) -> bool:
    """Check if cmdline represents a shell process."""
    if not cmdline:
        return True
    basename = cmdline[0].rsplit("/", 1)[-1]
    # Handle bash --posix, zsh -i, etc.
    return basename in SHELLS


def is_claude(cmdline: list[str]) -> bool:
    """Check if cmdline is a claude process."""
    if not cmdline:
        return False
    basename = cmdline[0].rsplit("/", 1)[-1]
    return basename == "claude"


def get_launch_command(cmdline: list[str]) -> str | None:
    """Determine the launch command for a window.

    Returns None for shell windows (session file default).
    Returns 'claude' for claude (strips flags).
    Returns full cmdline string for other commands.
    """
    if is_shell(cmdline):
        return None
    if is_claude(cmdline):
        return "claude"
    return " ".join(cmdline)


def generate_session(kitty_ls: list[dict]) -> str:
    """Generate Kitty session file content from kitty @ ls output."""
    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    os_window = kitty_ls[0]
    tabs = os_window["tabs"]

    lines.append(f"# Saved: {now} | Tabs: {len(tabs)}")
    lines.append("")

    for tab in tabs:
        title = tab.get("title", "")
        layout = tab.get("layout", "stack")
        windows = tab.get("windows", [])

        lines.append(f"new_tab {title}")
        lines.append(f"layout {layout}")

        for i, window in enumerate(windows):
            cwd = window.get("cwd", "")
            fg = window.get("foreground_processes", [])
            cmdline = fg[0].get("cmdline", []) if fg else []

            launch_cmd = get_launch_command(cmdline)

            if i == 0:
                # First window: use cd + optional launch
                lines.append(f"cd {cwd}")
                if launch_cmd:
                    lines.append(f"launch {launch_cmd}")
            else:
                # Additional windows: launch --type=window
                lines.append(f"cd {cwd}")
                if launch_cmd:
                    lines.append(f"launch --type=window {launch_cmd}")
                else:
                    lines.append("launch --type=window")

        lines.append("")

    return "\n".join(lines)


def main():
    data = json.load(sys.stdin)
    print(generate_session(data))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/data/claude-manager && python3 -m pytest kitty-enhance/tests/test_session_snapshot.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add kitty-enhance/scripts/session-snapshot.py kitty-enhance/tests/test_session_snapshot.py
git commit -m "feat: add session-snapshot.py — parse kitty @ ls into session file"
```

---

### Task 2: Shell functions — session-save, session-restore, session-list, session-delete

**Files:**
- Modify: `kitty-enhance/shell-functions.sh` (append after line 232)

- [ ] **Step 1: Add session functions to shell-functions.sh**

Append the following after line 232 (after the last alias `td`):

```bash
# ========================================
# Kitty Session 保存与恢复
# ========================================

_session_dir() {
    echo "$HOME/.config/kitty-enhance/sessions"
}

_session_snapshot_script() {
    echo "$HOME/.config/kitty/scripts/session-snapshot.py"
}

# 保存当前 Kitty 会话
session-save() {
    local name="${1:-}"
    if [ -z "$name" ]; then
        echo "用法: session-save <name>"
        echo "示例: session-save work"
        return 1
    fi

    # 检查 Kitty 环境
    if [ -z "${KITTY_WINDOW_ID:-}" ]; then
        echo "错误: 不在 Kitty 终端中"
        return 1
    fi

    local dir
    dir="$(_session_dir)"
    mkdir -p "$dir"

    local session_file="$dir/${name}.session"
    local meta_file="$dir/${name}.meta.json"
    local snapshot_script
    snapshot_script="$(_session_snapshot_script)"

    if [ ! -f "$snapshot_script" ]; then
        echo "错误: 找不到 session-snapshot.py: $snapshot_script"
        return 1
    fi

    # 获取 kitty 状态并生成 session 文件
    local kitty_json
    kitty_json=$(kitty @ --to "$(_kitty_socket)" ls 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$kitty_json" ]; then
        echo "错误: kitty @ ls 失败（需要 allow_remote_control yes）"
        return 1
    fi

    local overwrite=""
    if [ -f "$session_file" ]; then
        overwrite=" (覆盖)"
    fi

    echo "$kitty_json" | python3 "$snapshot_script" > "$session_file"
    if [ $? -ne 0 ]; then
        echo "错误: 生成 session 文件失败"
        rm -f "$session_file"
        return 1
    fi

    # 生成元数据
    echo "$kitty_json" | python3 -c "
import json, sys
from datetime import datetime
data = json.load(sys.stdin)
tabs = data[0]['tabs']
windows = sum(len(t['windows']) for t in tabs)
meta = {
    'name': '$name',
    'saved_at': datetime.now().isoformat(timespec='seconds'),
    'tabs': len(tabs),
    'windows': windows,
}
json.dump(meta, sys.stdout, ensure_ascii=False, indent=2)
print()
" > "$meta_file"

    echo "已保存${overwrite}: $name ($(grep -c 'new_tab' "$session_file") tabs)"
    echo "  文件: $session_file"
}

# 恢复 Kitty 会话
session-restore() {
    local name="${1:-}"
    if [ -z "$name" ]; then
        echo "用法: session-restore <name>"
        session-list
        return 1
    fi

    local session_file
    session_file="$(_session_dir)/${name}.session"

    if [ ! -f "$session_file" ]; then
        echo "错误: session '$name' 不存在"
        session-list
        return 1
    fi

    kitty --session "$session_file" --detach
    echo "已恢复: $name (新 Kitty 窗口)"
}

# 列出所有已保存的 session
session-list() {
    local dir
    dir="$(_session_dir)"

    if [ ! -d "$dir" ] || [ -z "$(ls -A "$dir"/*.meta.json 2>/dev/null)" ]; then
        echo "没有已保存的 session"
        return 0
    fi

    echo "已保存的 session:"
    echo ""
    for meta in "$dir"/*.meta.json; do
        python3 -c "
import json, sys
with open('$meta') as f:
    m = json.load(f)
print(f\"  {m['name']:<16} {m['tabs']} tabs, {m['windows']} windows  ({m['saved_at']})\")
" 2>/dev/null
    done
}

# 删除指定 session
session-delete() {
    local name="${1:-}"
    if [ -z "$name" ]; then
        echo "用法: session-delete <name>"
        session-list
        return 1
    fi

    local dir
    dir="$(_session_dir)"
    local session_file="$dir/${name}.session"
    local meta_file="$dir/${name}.meta.json"

    if [ ! -f "$session_file" ]; then
        echo "错误: session '$name' 不存在"
        return 1
    fi

    rm -f "$session_file" "$meta_file"
    echo "已删除: $name"
}

# Session 别名
alias ss='session-save'
alias sr='session-restore'
alias sl='session-list'
alias sd='session-delete'
```

- [ ] **Step 2: Verify shell syntax**

Run: `bash -n /mnt/data/claude-manager/kitty-enhance/shell-functions.sh`
Expected: No output (no syntax errors).

- [ ] **Step 3: Commit**

```bash
git add kitty-enhance/shell-functions.sh
git commit -m "feat: add session-save/restore/list/delete shell functions"
```

---

### Task 3: Install script — include session-snapshot.py

**Files:**
- Modify: `kitty-enhance/install.sh` (inside `install_kitty_scripts` function)

The existing `install_kitty_scripts` function copies everything from `scripts/` to `~/.config/kitty/scripts/`. Since `session-snapshot.py` lives in `scripts/`, it will be copied automatically by the existing loop:

```bash
for script in scripts/*; do
    [ -f "$script" ] || continue
    local name=$(basename "$script")
    rm -f "$scripts_dir/$name"
    cp "$script" "$scripts_dir/"
done
```

- [ ] **Step 1: Verify install.sh copies Python scripts too**

Run: `grep -A5 'for script in scripts' /mnt/data/claude-manager/kitty-enhance/install.sh`
Expected: The loop copies all files from `scripts/` without file extension filter — `session-snapshot.py` will be included.

- [ ] **Step 2: Verify chmod applies to .py files**

The existing `chmod +x "$scripts_dir"/* 2>/dev/null || true` will make it executable. No changes needed.

- [ ] **Step 3: Test end-to-end manually**

Run in Kitty terminal:
```bash
source /mnt/data/claude-manager/kitty-enhance/shell-functions.sh
session-save test-run
cat ~/.config/kitty-enhance/sessions/test-run.session
session-list
session-restore test-run
session-delete test-run
```

Expected: A new Kitty window opens with all current tabs restored.

- [ ] **Step 4: Commit (if any install.sh changes were needed)**

No commit expected for this task — install.sh already handles the file correctly.
