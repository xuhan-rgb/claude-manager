"""CLI for standalone Claude/Codex terminal management."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

from .kitty import focus_window
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


# ANSI color codes for status column (skipped when stdout is not a tty).
_STATUS_COLOR = {
    "working": "\033[32m",    # green
    "waiting": "\033[33m",    # yellow
    "completed": "\033[31m",  # red
    "idle": "\033[90m",       # gray
}
_FG_RESET = "\033[39m"  # reset foreground only, preserve background


def _colorize(text: str, status: str, use_color: bool) -> str:
    if not use_color:
        return text
    color = _STATUS_COLOR.get(status, "")
    # Use _FG_RESET (not _RESET) to preserve row background through IDLE column.
    return f"{color}{text}{_FG_RESET}" if color else text


def _display_width(s: str) -> int:
    """Return the visual width of a string, treating CJK characters as width 2."""
    width = 0
    for ch in s:
        code = ord(ch)
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
        print("  - 确认 kitty hook 已经安装（在 kitty tab 里运行 claude/codex 后会自动注册）")
        print("  - 注册数据位于 /tmp/feishu-bridge/registry.json")
        return

    headers = ["ID", "TAB", "PROJECT", "AGENT", "STATUS", "IDLE"]
    rows = [
        [
            t.terminal_id,
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

    # Zebra stripe: alternating row background for readability.
    _BG_EVEN = "\033[48;5;236m"  # dark gray background
    _BG_RESET = "\033[49m"       # reset background only

    print(format_row(headers))
    for idx, (row, t) in enumerate(zip(rows, terminals)):
        # Colorize the status cell after padding.
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
        line = "  ".join(cells)
        if use_color and idx % 2 == 0:
            # \033[K clears to end of line WITH current background color
            print(f"{_BG_EVEN}{line}\033[K{_BG_RESET}")
        else:
            print(line)
    print()
    print(f"共 {len(terminals)} 个活跃终端")



def _print_json(terminals: list[TerminalInfo]) -> None:
    payload = [
        {
            "terminal_id": t.terminal_id,
            "window_id": t.window_id,
            "socket": t.socket,
            "socket_label": t.socket_label,
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


def _format_terminal_line(terminals: Iterable[TerminalInfo]) -> list[str]:
    return [f"  {t.terminal_id}  {t.tab_title}" for t in terminals]


def _resolve_focus_target(selector: str) -> tuple[TerminalInfo | None, list[TerminalInfo]]:
    terminals = list_alive_terminals()
    exact = [t for t in terminals if t.terminal_id == selector]
    if exact:
        return exact[0], []

    matches = [t for t in terminals if t.window_id == selector]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, matches

    return None, []


def cmd_list(args: argparse.Namespace) -> int:
    terminals = list_alive_terminals()
    if args.active:
        terminals = [t for t in terminals if t.status in ("working", "waiting")]
    if args.json:
        _print_json(terminals)
    else:
        _print_table(terminals, use_color=sys.stdout.isatty())
    return 0


def cmd_focus(args: argparse.Namespace) -> int:
    target, ambiguous = _resolve_focus_target(args.terminal_id)
    if ambiguous:
        print(
            f"错误: 终端 ID {args.terminal_id} 不唯一，请使用完整 terminal_id。",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print("可选目标:", file=sys.stderr)
        for line in _format_terminal_line(ambiguous):
            print(line, file=sys.stderr)
        return 1

    if not target:
        raw = load_registry()
        if args.terminal_id in raw:
            print(
                f"错误: 终端 {args.terminal_id} 已存在于注册表，但当前不在线。",
                file=sys.stderr,
            )
        else:
            print(
                f"错误: 未找到 terminal_id={args.terminal_id} 的终端。",
                file=sys.stderr,
            )
        alive = list_alive_terminals()
        if alive:
            print("", file=sys.stderr)
            print("当前活跃的终端:", file=sys.stderr)
            for line in _format_terminal_line(alive):
                print(line, file=sys.stderr)
        return 1

    ok, err = focus_window(target.socket, target.window_id)
    if not ok:
        print(f"错误: {err}", file=sys.stderr)
        return 1

    print(
        f'切换到 "{target.tab_title}"'
        f"（terminal_id={target.terminal_id}, socket={target.socket}）"
    )
    return 0


def _build_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="管理正在运行 Claude/Codex 的 kitty 终端",
    )
    sub = parser.add_subparsers(dest="command")

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

    p_focus = sub.add_parser("focus", help="切换到指定 terminal_id 对应的 kitty 窗口")
    p_focus.add_argument("terminal_id", help="terminal_id，或在唯一时使用裸 window_id")
    p_focus.set_defaults(func=cmd_focus)

    p_select = sub.add_parser("select", help="交互式选择并跳转终端 (↑↓/jk 选择, Enter 跳转)")
    p_select.set_defaults(func=lambda args: _cmd_select())

    return parser


def _cmd_select() -> int:
    from .interactive import run_interactive
    return run_interactive()


def run(argv: list[str], prog: str = "agent-terminals") -> int:
    parser = _build_parser(prog=prog)
    args = parser.parse_args(argv)
    # No subcommand → default to interactive select (if tty) or list
    if args.command is None:
        if sys.stdout.isatty() and sys.stdin.isatty():
            return _cmd_select()
        return cmd_list(argparse.Namespace(active=False, json=False))
    return args.func(args)


def main() -> int:
    return run(sys.argv[1:], prog="agent-terminals")
