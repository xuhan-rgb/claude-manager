"""Interactive terminal selector with arrow-key navigation."""

from __future__ import annotations

import sys
import termios
import tty

from .cli import format_time_ago, _display_width, _pad_right, _STATUS_COLOR, _RESET
from .kitty import focus_window
from .registry import TerminalInfo, list_alive_terminals


def _read_key() -> str:
    """Read a single keypress. Returns special names for arrow keys."""
    fd = sys.stdin.fileno()
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        seq = sys.stdin.read(1)
        if seq == "[":
            code = sys.stdin.read(1)
            return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(
                code, ""
            )
        return "esc"
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "q":
        return "quit"
    if ch in ("j",):
        return "down"
    if ch in ("k",):
        return "up"
    return ch


def _render(
    terminals: list[TerminalInfo],
    selected: int,
    widths: list[int],
    headers: list[str],
) -> str:
    """Render the full table as a string with the selected row highlighted."""
    _SEL_BG = "\033[48;5;24m"   # blue-ish background for selected row
    _BG_EVEN = "\033[48;5;236m"  # dark gray for even rows (zebra)
    _BG_RESET = "\033[49m"

    lines: list[str] = []

    # Header
    header_line = "  ".join(
        _pad_right(h, widths[i]) for i, h in enumerate(headers)
    )
    lines.append(f"\033[1m{header_line}\033[0m")  # bold header

    for idx, t in enumerate(terminals):
        status_colored = _STATUS_COLOR.get(t.status, "") + _pad_right(
            t.status, widths[4]
        ) + _RESET

        cells = [
            _pad_right(t.window_id, widths[0]),
            _pad_right(t.tab_title, widths[1]),
            _pad_right(t.project_name, widths[2]),
            _pad_right(t.agent_kind, widths[3]),
            status_colored,
            format_time_ago(t.idle_seconds),
        ]
        line = "  ".join(cells)

        if idx == selected:
            # Selected row: distinct background + arrow indicator
            lines.append(f"{_SEL_BG}> {line}\033[K{_BG_RESET}")
        elif idx % 2 == 0:
            lines.append(f"{_BG_EVEN}  {line}\033[K{_BG_RESET}")
        else:
            lines.append(f"  {line}\033[K")

    lines.append("")
    lines.append(
        f"  \033[90m↑↓/jk 选择  Enter 跳转  q 退出  "
        f"共 {len(terminals)} 个终端\033[0m"
    )
    return "\n".join(lines)


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


def run_interactive() -> int:
    """Run the interactive terminal selector. Returns exit code."""
    terminals = list_alive_terminals()
    if not terminals:
        print("没有活跃的终端。")
        return 0

    headers = ["ID", "TAB", "PROJECT", "AGENT", "STATUS", "IDLE"]
    widths = _compute_widths(terminals, headers)
    selected = 0
    total_lines = len(terminals) + 3  # header + rows + blank + hint

    # Save terminal state and switch to raw mode
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        tty.setraw(fd)

        # Initial render
        output = _render(terminals, selected, widths, headers)
        sys.stdout.write(output)
        sys.stdout.flush()

        while True:
            key = _read_key()

            if key == "quit" or key == "esc":
                break

            if key == "up":
                selected = (selected - 1) % len(terminals)
            elif key == "down":
                selected = (selected + 1) % len(terminals)
            elif key == "enter":
                t = terminals[selected]
                # Restore terminal before focus (so output is clean)
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                sys.stdout.write("\033[?25h")  # show cursor
                # Move to bottom and clear
                sys.stdout.write(f"\033[{total_lines}B\r\n")
                sys.stdout.flush()

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

            # Redraw: move cursor up to top, then rewrite
            sys.stdout.write(f"\033[{total_lines}A\r")
            output = _render(terminals, selected, widths, headers)
            sys.stdout.write(output)
            sys.stdout.flush()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.write(f"\r\n")
        sys.stdout.flush()

    return 0
