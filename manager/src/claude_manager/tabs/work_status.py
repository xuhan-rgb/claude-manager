#!/usr/bin/env python3
"""Work status - 监控所有 Kitty 窗口中的 Claude/Codex 工作进度"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .registry import load_registry


@dataclass
class AIProcess:
    """AI 助手进程信息"""
    name: str  # claude / codex
    cwd: str
    cmdline: list[str]
    pid: int

    @property
    def display_name(self) -> str:
        """显示名称"""
        if 'claude' in self.name.lower():
            return 'Claude Code'
        elif 'codex' in self.name.lower():
            return 'Codex'
        return self.name

    @property
    def short_cwd(self) -> str:
        """缩短的工作目录"""
        home = Path.home()
        cwd_path = Path(self.cwd)
        try:
            rel = cwd_path.relative_to(home)
            return f"~/{rel}"
        except ValueError:
            # 不在 home 下，返回完整路径
            return str(cwd_path)


@dataclass
class TabStatus:
    """Tab 状态"""
    tab_id: int
    title: str
    is_focused: bool
    window_count: int
    ai_processes: list[AIProcess]

    @property
    def has_ai(self) -> bool:
        """是否有 AI 助手运行"""
        return len(self.ai_processes) > 0


@dataclass
class OSWindowStatus:
    """OS Window 状态"""
    window_id: int
    socket: str
    is_focused: bool
    tabs: list[TabStatus]

    @property
    def socket_label(self) -> str:
        """Socket 标签"""
        if '@' in self.socket:
            return self.socket.split('@')[1]
        return self.socket

    @property
    def has_ai(self) -> bool:
        """是否有 AI 助手运行"""
        return any(tab.has_ai for tab in self.tabs)


def _extract_ai_processes(windows: list[dict]) -> list[AIProcess]:
    """从窗口列表中提取 AI 进程"""
    processes = []

    for window in windows:
        fg_procs = window.get('foreground_processes', [])
        for proc in fg_procs:
            cmdline = proc.get('cmdline', [])
            if not cmdline:
                continue

            # 检查第一个参数（可执行文件名）
            cmd_name = cmdline[0].lower()
            base_name = cmd_name.split('/')[-1]  # 提取文件名部分

            # 严格匹配：只有可执行文件名是 claude 或 codex 才算
            if base_name in ('claude', 'codex'):
                processes.append(AIProcess(
                    name=cmdline[0],
                    cwd=proc.get('cwd', ''),
                    cmdline=cmdline,
                    pid=proc.get('pid', 0)
                ))

    return processes


def _get_kitty_ls(socket: str) -> Optional[list[dict]]:
    """获取 kitty @ ls 输出"""
    try:
        result = subprocess.run(
            ['kitty', '@', '--to', socket, 'ls'],
            capture_output=True,
            text=True,
            timeout=3
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def _find_all_kitty_sockets() -> list[str]:
    """查找所有 Kitty socket"""
    import os
    sockets = set()

    # 方法 1: 当前环境变量
    current_socket = os.environ.get('KITTY_LISTEN_ON', '')
    if current_socket:
        sockets.add(current_socket)

    # 方法 2: 从 registry 获取
    try:
        registry = load_registry()
        for term in registry:
            socket = term.get('kitty_socket', '')
            if socket:
                sockets.add(socket)
    except Exception:
        pass

    # 方法 3: 默认 socket（如果前面都没找到）
    if not sockets:
        sockets.add('unix:@mykitty')

    return list(sockets)


def scan_all_windows() -> list[OSWindowStatus]:
    """扫描所有 Kitty 窗口"""
    windows = []
    sockets = _find_all_kitty_sockets()

    for socket in sockets:
        os_windows_data = _get_kitty_ls(socket)
        if not os_windows_data:
            continue

        for os_win in os_windows_data:
            tabs = []

            for tab_data in os_win.get('tabs', []):
                ai_processes = _extract_ai_processes(tab_data.get('windows', []))

                tabs.append(TabStatus(
                    tab_id=tab_data.get('id', 0),
                    title=tab_data.get('title', ''),
                    is_focused=tab_data.get('is_focused', False),
                    window_count=len(tab_data.get('windows', [])),
                    ai_processes=ai_processes
                ))

            windows.append(OSWindowStatus(
                window_id=os_win.get('id', 0),
                socket=socket,
                is_focused=os_win.get('is_focused', False),
                tabs=tabs
            ))

    return windows


def format_work_status(windows: list[OSWindowStatus], active_only: bool = False) -> str:
    """格式化工作状态输出"""
    lines = []
    lines.append("所有 Kitty 实例的工作进度：")
    lines.append("")

    total_windows = 0
    total_tabs = 0
    total_ai = 0
    item_index = 1

    for os_win in windows:
        if active_only and not os_win.has_ai:
            continue

        total_windows += 1

        # OS Window 标题
        focus_mark = " (当前)" if os_win.is_focused else ""
        lines.append(f"━━━ OS Window {os_win.window_id}: {os_win.socket_label}{focus_mark} ━━━")
        lines.append("")

        for tab in os_win.tabs:
            if active_only and not tab.has_ai:
                continue

            total_tabs += 1

            # Tab 标题
            focus_mark = " [聚焦]" if tab.is_focused else ""
            lines.append(f"  [{item_index}] Tab {tab.tab_id}: {tab.title}{focus_mark}")

            # AI 进程
            if tab.ai_processes:
                for proc in tab.ai_processes:
                    total_ai += 1
                    lines.append(f"      ● {proc.display_name} → {proc.short_cwd}")
            else:
                lines.append(f"      (无 AI 助手运行)")

            lines.append("")
            item_index += 1

    lines.append("━" * 60)
    lines.append(f"总计: {total_windows} 个窗口, {total_tabs} 个 tab, {total_ai} 个活跃 AI 助手")
    lines.append("")
    lines.append("提示: 输入编号跳转到对应 tab")

    return "\n".join(lines)


def format_work_status_json(windows: list[OSWindowStatus]) -> str:
    """格式化为 JSON 输出"""
    data = []
    item_index = 1

    for os_win in windows:
        for tab in os_win.tabs:
            data.append({
                "index": item_index,
                "window_id": os_win.window_id,
                "socket": os_win.socket,
                "tab_id": tab.tab_id,
                "title": tab.title,
                "is_focused": tab.is_focused,
                "ai_processes": [
                    {
                        "name": proc.display_name,
                        "cwd": proc.cwd,
                        "pid": proc.pid
                    }
                    for proc in tab.ai_processes
                ]
            })
            item_index += 1

    return json.dumps(data, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    windows = scan_all_windows()
    print(format_work_status(windows))
