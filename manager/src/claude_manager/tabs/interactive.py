"""Interactive terminal selector with arrow-key navigation."""

from __future__ import annotations

import os
import sys
import termios
import tty

from .cli import format_time_ago, _display_width, _pad_right, _STATUS_COLOR, _RESET
from .kitty import focus_window
from .registry import TerminalInfo, list_alive_terminals


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


def _render_line(
    t: TerminalInfo,
    idx: int,
    selected: int,
    widths: list[int],
) -> str:
    """Render a single data row with appropriate background."""
    _SEL_BG = "\033[48;5;24m"
    _BG_EVEN = "\033[48;5;236m"
    _BG_RESET = "\033[0m"

    status_colored = (
        _STATUS_COLOR.get(t.status, "")
        + _pad_right(t.status, widths[4])
        + _RESET
    )

    cells = [
        _pad_right(t.window_id, widths[0]),
        _pad_right(t.tab_title, widths[1]),
        _pad_right(t.project_name, widths[2]),
        _pad_right(t.agent_kind, widths[3]),
        status_colored,
        format_time_ago(t.idle_seconds),
    ]
    content = "  ".join(cells)

    if idx == selected:
        return f"{_SEL_BG}\033[1m> {content}\033[K{_BG_RESET}"
    elif idx % 2 == 0:
        return f"{_BG_EVEN}  {content}\033[K{_BG_RESET}"
    else:
        return f"  {content}\033[K"


def _compute_widths(
    terminals: list[TerminalInfo], headers: list[str]
) -> list[int]:
    widths = [_display_width(h) for h in headers]
    for t in terminals:
        cells = [
            t.window_id,
            t.tab_title,
            t.project_name,
            t.agent_kind,
            t.status,
            format_time_ago(t.idle_seconds),
        ]
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], _display_width(cell))
    return widths


def _draw_full(
    terminals: list[TerminalInfo],
    selected: int,
    widths: list[int],
    headers: list[str],
) -> None:
    """Clear screen and draw the full table using absolute cursor positioning."""
    buf: list[str] = []

    # Clear screen, move cursor to top-left
    buf.append("\033[2J\033[H")

    # Header (bold)
    header_line = "  ".join(
        _pad_right(h, widths[i]) for i, h in enumerate(headers)
    )
    buf.append(f"  \033[1m{header_line}\033[0m")

    # Data rows
    for idx, t in enumerate(terminals):
        buf.append(_render_line(t, idx, selected, widths))

    # Footer
    buf.append("")
    buf.append(
        f"  \033[90m↑↓/jk 选择  Enter 跳转  q/Esc 退出  "
        f"共 {len(terminals)} 个终端\033[0m"
    )

    # Join with \r\n (raw mode needs explicit CR)
    _write("\r\n".join(buf))


def run_interactive() -> int:
    """Run the interactive terminal selector. Returns exit code."""
    terminals = list_alive_terminals()
    if not terminals:
        print("没有活跃的终端。")
        return 0

    headers = ["ID", "TAB", "PROJECT", "AGENT", "STATUS", "IDLE"]
    widths = _compute_widths(terminals, headers)
    selected = 0

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    # Switch to alternate screen buffer + hide cursor
    _write("\033[?1049h\033[?25l")

    try:
        tty.setraw(fd)
        _draw_full(terminals, selected, widths, headers)

        while True:
            key = _read_key(fd)

            if key in ("quit", "esc"):
                break

            if key == "up":
                selected = (selected - 1) % len(terminals)
            elif key == "down":
                selected = (selected + 1) % len(terminals)
            elif key == "enter":
                t = terminals[selected]
                # Restore terminal BEFORE focus
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                _write("\033[?25h\033[?1049l")  # show cursor, leave alt screen

                ok, err = focus_window(t.socket, t.window_id)
                if ok:
                    print(
                        f'切换到 "{t.tab_title}"'
                        f"（window_id={t.window_id}）"
                    )
                else:
                    print(f"错误: {err}", file=sys.stderr)
                return 0 if ok else 1
            else:
                continue

            _draw_full(terminals, selected, widths, headers)

    finally:
        # Always restore terminal state
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        _write("\033[?25h\033[?1049l")  # show cursor, leave alt screen

    return 0
