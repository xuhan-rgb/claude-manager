"""Kitty 终端适配器

使用 Kitty Remote Control API 实现终端操作。
"""

import json
import subprocess
import os
from typing import Optional, List

from .adapter import TerminalAdapter, WindowInfo, SplitResult


class KittyAdapter(TerminalAdapter):
    """Kitty 终端适配器

    通过 kitten @ 命令与 Kitty 终端交互。
    需要在 kitty.conf 中启用 allow_remote_control=yes
    """

    def __init__(self, socket_path: Optional[str] = None):
        """初始化

        Args:
            socket_path: Kitty socket 路径，None 表示自动检测
        """
        self._socket_path = socket_path

    @property
    def name(self) -> str:
        return "kitty"

    def _run(self, *args, timeout: float = 2.0) -> subprocess.CompletedProcess:
        """执行 kitten @ 命令"""
        cmd = ['kitten', '@']
        if self._socket_path:
            cmd.extend(['--to', f'unix:{self._socket_path}'])
        cmd.extend(args)

        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 1, '', 'timeout')
        except FileNotFoundError:
            return subprocess.CompletedProcess(cmd, 1, '', 'kitten not found')

    def is_available(self) -> tuple[bool, str]:
        """检查 Kitty Remote Control 是否可用"""
        if os.environ.get('TERM') != 'xterm-kitty':
            return False, "当前不在 Kitty 终端中运行"

        result = self._run('ls')
        if result.returncode != 0:
            if 'remote control' in result.stderr.lower():
                return False, (
                    "Kitty Remote Control 未启用。\n"
                    "请在 kitty.conf 中添加: allow_remote_control yes\n"
                    "或使用: kitty -o allow_remote_control=yes"
                )
            return False, f"kitten @ ls 失败: {result.stderr}"
        return True, "Kitty Remote Control 可用"

    # ========== 窗口操作 ==========

    def create_split(
        self,
        direction: str = "vertical",
        command: str = "bash",
        cwd: Optional[str] = None
    ) -> SplitResult:
        """创建分屏窗口"""
        # Kitty 的 location 参数：vsplit=垂直（左右），hsplit=水平（上下）
        location = "vsplit" if direction == "vertical" else "hsplit"

        args = ['launch', '--type=window', f'--location={location}']
        if cwd:
            args.extend(['--cwd', cwd])
        args.append(command)

        result = self._run(*args)
        if result.returncode != 0:
            return SplitResult(False, error=result.stderr or "创建窗口失败")

        try:
            window_id = result.stdout.strip()
            return SplitResult(True, window_id=window_id)
        except ValueError:
            return SplitResult(False, error="无法解析窗口 ID")

    def close_window(self, window_id: str) -> bool:
        """关闭窗口"""
        result = self._run('close-window', '--match', f'id:{window_id}')
        return result.returncode == 0

    def focus_window(self, window_id: str) -> bool:
        """聚焦窗口"""
        result = self._run('focus-window', '--match', f'id:{window_id}')
        return result.returncode == 0

    def resize_window(
        self,
        window_id: str,
        columns: Optional[int] = None,
        increment: Optional[int] = None,
        axis: str = "horizontal"
    ) -> bool:
        """调整窗口大小"""
        # 如果指定了目标列数，需要计算增量
        if columns is not None:
            current_info = self.get_window_info(window_id)
            if not current_info or current_info.columns == 0:
                return False
            increment = columns - current_info.columns
            if increment == 0:
                return True

        if increment is None:
            return False

        # 先聚焦到目标窗口
        self.focus_window(window_id)

        result = self._run('resize-window', f'--increment={increment}', f'--axis={axis}')
        return result.returncode == 0

    def send_text(self, text: str, window_id: Optional[str] = None) -> bool:
        """向窗口发送文本"""
        args = ['send-text']
        if window_id:
            args.extend(['--match', f'id:{window_id}'])
        args.append(text)
        result = self._run(*args)
        return result.returncode == 0

    # ========== 信息获取 ==========

    def _parse_windows_from_ls(self) -> List[WindowInfo]:
        """从 kitten @ ls 解析窗口信息"""
        result = self._run('ls')
        if result.returncode != 0:
            return []

        try:
            data = json.loads(result.stdout)
            windows = []
            for os_window in data:
                for tab_data in os_window.get('tabs', []):
                    if not tab_data.get('is_focused', False):
                        continue
                    for win_data in tab_data.get('windows', []):
                        tty = self._get_tty_from_pid(win_data.get('pid', 0))
                        windows.append(WindowInfo(
                            id=str(win_data['id']),
                            columns=win_data.get('columns', 0),
                            lines=win_data.get('lines', 0),
                            tty=tty,
                            is_focused=win_data.get('is_focused', False),
                            title=win_data.get('title', ''),
                            pid=win_data.get('pid', 0),
                            cwd=win_data.get('cwd', ''),
                        ))
            return windows
        except (json.JSONDecodeError, KeyError):
            return []

    def _get_tty_from_pid(self, pid: int) -> Optional[str]:
        """从进程 ID 获取 TTY"""
        if not pid:
            return None
        try:
            result = subprocess.run(
                ['ps', '-p', str(pid), '-o', 'tty='],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                tty = result.stdout.strip()
                if tty and tty != '?':
                    return f"/dev/{tty}"
        except Exception:
            pass
        return None

    def get_window_info(self, window_id: str) -> Optional[WindowInfo]:
        """获取窗口信息"""
        # 确保 window_id 是字符串（兼容 int 传入）
        window_id_str = str(window_id)
        for win in self._parse_windows_from_ls():
            if win.id == window_id_str:
                return win
        return None

    def get_current_window(self) -> Optional[WindowInfo]:
        """获取当前聚焦的窗口"""
        for win in self._parse_windows_from_ls():
            if win.is_focused:
                return win
        return None

    def list_windows(self) -> List[WindowInfo]:
        """列出当前 Tab 的所有窗口"""
        return self._parse_windows_from_ls()

    def get_total_columns(self) -> int:
        """获取当前 Tab 的总列数"""
        windows = self.list_windows()
        if not windows:
            return 0

        total_cols = sum(win.columns for win in windows)
        # 加上窗口间的分隔符宽度（每个分隔符约 1 列）
        if len(windows) > 1:
            total_cols += len(windows) - 1

        return total_cols

    # ========== 布局管理 ==========

    def set_layout(self, layout: str) -> bool:
        """设置布局模式"""
        result = self._run('set-layout', layout)
        return result.returncode == 0

    def lock_layout(self, layouts: List[str]) -> bool:
        """锁定可用布局"""
        args = ['set-enabled-layouts'] + layouts
        result = self._run(*args)
        return result.returncode == 0


def check_kitty_remote_control() -> tuple[bool, str]:
    """检查 Kitty Remote Control 是否可用（兼容旧接口）"""
    adapter = KittyAdapter()
    return adapter.is_available()
