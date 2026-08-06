"""Interactive work status selector with arrow-key navigation."""

from __future__ import annotations

import os
import subprocess
import sys
import termios
import tty
from typing import Optional

from .work_status import OSWindowStatus, TabStatus, scan_all_windows


def _read_key(fd: int) -> str:
    """Read a single keypress from raw fd. Returns action name."""
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        seq = os.read(fd, 1)
        if seq == b"[":
            code = os.read(fd, 1)
            return {b"A": "up", b"B": "down"}.get(code, "")
        return "esc"
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"q":
        return "quit"
    if ch == b"j":
        return "down"
    if ch == b"k":
        return "up"
    return ""


def _write(s: str) -> None:
    """Write string to stdout and flush."""
    sys.stdout.write(s)
    sys.stdout.flush()


def _truncate(text: str, max_len: int) -> str:
    """截断文本到指定长度"""
    if len(text) <= max_len:
        return text
    return text[:max_len-3] + "..."


def _render_item(
    os_win: OSWindowStatus,
    tab: TabStatus,
    idx: int,
    selected: int,
    term_width: int,
) -> list[str]:
    """渲染一个 tab 项（可能包含多个 AI 进程）"""
    _SEL_BG = "\033[48;5;24m"
    _BG_EVEN = "\033[48;5;236m"
    _BG_RESET = "\033[0m"

    lines = []

    # Tab 标题行
    focus_mark = " [聚焦]" if tab.is_focused else ""
    title = f"Tab {tab.tab_id}: {tab.title}{focus_mark}"
    title = _truncate(title, term_width - 8)

    if idx == selected:
        lines.append(f"{_SEL_BG}\033[1m> {title}\033[K{_BG_RESET}")
    elif idx % 2 == 0:
        lines.append(f"{_BG_EVEN}  {title}\033[K{_BG_RESET}")
    else:
        lines.append(f"  {title}\033[K")

    # AI 进程列表（缩进显示）
    if tab.ai_processes:
        for proc in tab.ai_processes:
            ai_line = f"    ● {proc.display_name} → {proc.short_cwd}"
            ai_line = _truncate(ai_line, term_width - 4)

            if idx == selected:
                lines.append(f"{_SEL_BG}  {ai_line}\033[K{_BG_RESET}")
            elif idx % 2 == 0:
                lines.append(f"{_BG_EVEN}  {ai_line}\033[K{_BG_RESET}")
            else:
                lines.append(f"  {ai_line}\033[K")
    else:
        ai_line = "    (无 AI 助手运行)"
        if idx == selected:
            lines.append(f"{_SEL_BG}  {ai_line}\033[K{_BG_RESET}")
        elif idx % 2 == 0:
            lines.append(f"{_BG_EVEN}  {ai_line}\033[K{_BG_RESET}")
        else:
            lines.append(f"  {ai_line}\033[K")

    return lines


def _render_screen(
    windows: list[OSWindowStatus],
    flat_items: list[tuple[OSWindowStatus, TabStatus]],
    selected: int,
) -> None:
    """渲染整个屏幕"""
    # 清屏并移动到左上角
    _write("\033[2J\033[H")

    # 获取终端宽度
    term_width = os.get_terminal_size().columns

    # 标题
    _write("\033[1m所有 Kitty 窗口的工作进度\033[0m\n\n")

    # 渲染所有项
    current_window = None
    for idx, (os_win, tab) in enumerate(flat_items):
        # 如果是新的 OS Window，显示分隔符
        if os_win != current_window:
            current_window = os_win
            focus_mark = " (当前)" if os_win.is_focused else ""
            separator = f"━━━ OS Window {os_win.window_id}: {os_win.socket_label}{focus_mark} ━━━"
            _write(f"\n\033[36m{separator}\033[0m\n\n")

        # 渲染 tab 和 AI 进程
        for line in _render_item(os_win, tab, idx, selected, term_width):
            _write(line + "\n")
        _write("\n")

    # 底部提示
    total_tabs = len(flat_items)
    total_ai = sum(len(tab.ai_processes) for _, tab in flat_items)
    _write("\n" + "━" * min(60, term_width) + "\n")
    _write(f"总计: {len(windows)} 个窗口, {total_tabs} 个 tab, {total_ai} 个活跃 AI 助手\n\n")
    _write("\033[90m↑↓/jk: 选择  Enter: 跳转  q/Esc: 退出\033[0m\n")


def _jump_to_tab(os_win: OSWindowStatus, tab: TabStatus) -> bool:
    """跳转到指定 tab"""
    try:
        # 聚焦 tab
        subprocess.run(
            ['kitty', '@', '--to', os_win.socket, 'focus-tab', '--match', f'id:{tab.tab_id}'],
            capture_output=True,
            timeout=3,
            check=True
        )
        return True
    except Exception as e:
        _write(f"\n\033[31m错误: 跳转失败 - {e}\033[0m\n")
        return False


def run_interactive_work_status() -> int:
    """运行交互式 work-status 选择器"""
    if not sys.stdout.isatty():
        print("错误: 交互模式需要在终端中运行", file=sys.stderr)
        return 1

    # 扫描所有窗口
    windows = scan_all_windows()
    if not windows:
        print("未找到任何 Kitty 窗口", file=sys.stderr)
        return 1

    # 展平为 (os_win, tab) 列表
    flat_items: list[tuple[OSWindowStatus, TabStatus]] = []
    for os_win in windows:
        for tab in os_win.tabs:
            flat_items.append((os_win, tab))

    if not flat_items:
        print("未找到任何 tab", file=sys.stderr)
        return 1

    selected = 0

    # 设置终端为 raw 模式
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)

        while True:
            _render_screen(windows, flat_items, selected)

            action = _read_key(fd)

            if action == "up":
                selected = max(0, selected - 1)
            elif action == "down":
                selected = min(len(flat_items) - 1, selected + 1)
            elif action == "enter":
                # 恢复终端设置
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

                # 跳转
                os_win, tab = flat_items[selected]
                if _jump_to_tab(os_win, tab):
                    print(f"\n✓ 已跳转到 Tab {tab.tab_id}: {tab.title}")
                    return 0
                else:
                    return 1
            elif action in ("quit", "esc"):
                # 恢复终端设置
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                _write("\n")
                return 0

    except KeyboardInterrupt:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        _write("\n")
        return 0
    except Exception as e:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        print(f"\n错误: {e}", file=sys.stderr)
        return 1
