"""CLI for claude-manager tabs subcommand."""

from __future__ import annotations

import argparse
import json
import sys

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

    # Zebra stripe: alternating row background for readability.
    _BG_EVEN = "\033[48;5;236m"  # dark gray background
    _BG_ODD = ""                 # terminal default
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
            print(f"{_BG_EVEN}{line}{_BG_RESET}")
        else:
            print(line)
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

    p_focus = sub.add_parser("focus", help="切换到指定 window_id 对应的 kitty 窗口")
    p_focus.add_argument("window_id", help="kitty window_id")
    p_focus.set_defaults(func=cmd_focus)

    return parser


def run(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
