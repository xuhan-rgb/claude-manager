"""Kitty Remote Control API 封装 - Tab 和 Window 管理

每个任务对应一个 Kitty Tab，Tab 内可有多个 window。
"""

import json
import subprocess
from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class KittyWindow:
    """Kitty 窗口信息"""
    id: int
    title: str
    pid: int
    cwd: str
    is_focused: bool
    columns: int = 0  # 窗口列数
    lines: int = 0    # 窗口行数
    at_prompt: bool = False  # 是否在提示符处（等待输入）


@dataclass
class KittyTab:
    """Kitty Tab 信息"""
    id: int
    title: str
    is_focused: bool
    windows: list[KittyWindow]


class KittyController:
    """Kitty 终端控制器

    使用 Kitty Tab 管理任务：
    - 每个任务对应一个 Tab（标题：Task:{task_id}）
    - 每个 Tab 默认有一个运行 claude 的 window
    - 可以在 Tab 内添加更多 window
    """

    TASK_TAB_PREFIX = "Task:"

    def __init__(self, socket_path: Optional[str] = None):
        self.socket_path = socket_path

    def _run(self, *args, timeout: float = 2.0) -> subprocess.CompletedProcess:
        """执行 kitten @ 命令"""
        cmd = ['kitten', '@']
        if self.socket_path:
            cmd.extend(['--to', f'unix:{self.socket_path}'])
        cmd.extend(args)

        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 1, '', 'timeout')
        except FileNotFoundError:
            return subprocess.CompletedProcess(cmd, 1, '', 'kitten not found')

    def is_available(self) -> bool:
        """检查 Kitty Remote Control 是否可用"""
        return self._run('ls').returncode == 0

    # ========== Tab 管理 ==========

    def list_tabs(self) -> list[KittyTab]:
        """列出所有 Tab"""
        result = self._run('ls')
        if result.returncode != 0:
            return []

        try:
            data = json.loads(result.stdout)
            tabs = []
            for os_window in data:
                for tab_data in os_window.get('tabs', []):
                    windows = []
                    for win_data in tab_data.get('windows', []):
                        windows.append(KittyWindow(
                            id=win_data['id'],
                            columns=win_data.get('columns', 0),
                            lines=win_data.get('lines', 0),
                            at_prompt=win_data.get('at_prompt', False),
                            title=win_data.get('title', ''),
                            pid=win_data.get('pid', 0),
                            cwd=win_data.get('cwd', ''),
                            is_focused=win_data.get('is_focused', False),
                        ))
                    tabs.append(KittyTab(
                        id=tab_data['id'],
                        title=tab_data.get('title', ''),
                        is_focused=tab_data.get('is_focused', False),
                        windows=windows,
                    ))
            return tabs
        except (json.JSONDecodeError, KeyError):
            return []

    def create_tab(self, title: str, cwd: str = None, command: str = "claude") -> Optional[int]:
        """创建新 Tab

        Args:
            title: Tab 标题
            cwd: 工作目录
            command: 要执行的命令

        Returns:
            新 Tab 中第一个 window 的 ID
        """
        args = ['launch', '--type=tab', '--tab-title', title]
        if cwd:
            args.extend(['--cwd', cwd])
        args.append(command)

        result = self._run(*args)
        if result.returncode != 0:
            return None

        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def focus_tab(self, tab_id: int) -> bool:
        """切换到指定 Tab（通过 Tab ID）"""
        result = self._run('focus-tab', '--match', f'id:{tab_id}')
        return result.returncode == 0

    def focus_tab_by_title(self, title: str) -> bool:
        """通过标题切换 Tab"""
        # Kitty 的 match 语法支持 title:pattern
        result = self._run('focus-tab', '--match', f'title:^{title}$')
        return result.returncode == 0

    def close_tab(self, tab_id: int) -> bool:
        """关闭 Tab"""
        result = self._run('close-tab', '--match', f'id:{tab_id}')
        return result.returncode == 0

    def get_tab_by_title(self, title: str) -> Optional[KittyTab]:
        """通过标题获取 Tab"""
        for tab in self.list_tabs():
            if tab.title == title:
                return tab
        return None

    def set_tab_title(self, title: str, tab_id: int = None) -> bool:
        """设置 Tab 标题"""
        args = ['set-tab-title']
        if tab_id:
            args.extend(['--match', f'id:{tab_id}'])
        args.append(title)
        result = self._run(*args)
        return result.returncode == 0

    # ========== 任务 Tab 管理 ==========

    def get_task_tab_title(self, task_id: str) -> str:
        """获取任务 Tab 标题"""
        return f"{self.TASK_TAB_PREFIX}{task_id}"

    def create_task_tab(self, task_id: str, cwd: str, command: str = "claude") -> Optional[int]:
        """创建任务 Tab

        Args:
            task_id: 任务 ID
            cwd: 工作目录
            command: 启动命令

        Returns:
            Window ID
        """
        title = self.get_task_tab_title(task_id)
        return self.create_tab(title, cwd, command)

    def focus_task_tab(self, task_id: str) -> bool:
        """切换到任务 Tab"""
        title = self.get_task_tab_title(task_id)
        tab = self.get_tab_by_title(title)
        if tab:
            return self.focus_tab(tab.id)
        return False

    def close_task_tab(self, task_id: str) -> bool:
        """关闭任务 Tab"""
        title = self.get_task_tab_title(task_id)
        tab = self.get_tab_by_title(title)
        if tab:
            return self.close_tab(tab.id)
        return False

    def task_tab_exists(self, task_id: str) -> bool:
        """检查任务 Tab 是否存在"""
        title = self.get_task_tab_title(task_id)
        return self.get_tab_by_title(title) is not None

    def list_task_tabs(self) -> list[KittyTab]:
        """列出所有任务 Tab"""
        return [tab for tab in self.list_tabs()
                if tab.title.startswith(self.TASK_TAB_PREFIX)]

    def get_task_id_from_tab(self, tab: KittyTab) -> Optional[str]:
        """从 Tab 提取任务 ID"""
        if tab.title.startswith(self.TASK_TAB_PREFIX):
            return tab.title[len(self.TASK_TAB_PREFIX):]
        return None

    # ========== Window 管理 ==========

    def create_window_in_current_tab(self, cwd: str = None, command: str = "bash",
                                      location: str = "vsplit") -> Optional[int]:
        """在当前 Tab 中创建新 window

        Args:
            cwd: 工作目录
            command: 命令
            location: 位置 (vsplit, hsplit, after, before)

        Returns:
            Window ID
        """
        args = ['launch', '--type=window', f'--location={location}']
        if cwd:
            args.extend(['--cwd', cwd])
        args.append(command)

        result = self._run(*args)
        if result.returncode != 0:
            return None

        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def focus_window(self, window_id: int) -> bool:
        """聚焦到指定 window"""
        result = self._run('focus-window', '--match', f'id:{window_id}')
        return result.returncode == 0

    def close_window(self, window_id: int) -> bool:
        """关闭 window"""
        result = self._run('close-window', '--match', f'id:{window_id}')
        return result.returncode == 0

    def resize_window(self, increment: int = 5, axis: str = 'horizontal') -> bool:
        """调整当前 window 大小（相对增量）"""
        result = self._run('resize-window', f'--increment={increment}', f'--axis={axis}')
        return result.returncode == 0

    def set_window_columns(self, target_columns: int, window_id: int = None) -> bool:
        """设置窗口到固定列数

        Args:
            target_columns: 目标列数
            window_id: 窗口 ID，None 表示当前窗口

        Returns:
            是否成功
        """
        # 获取当前窗口信息
        if window_id:
            window = None
            for tab in self.list_tabs():
                for win in tab.windows:
                    if win.id == window_id:
                        window = win
                        break
                if window:
                    break
        else:
            window = self.get_current_window()

        if not window or window.columns == 0:
            return False

        # 计算需要调整的增量
        increment = target_columns - window.columns

        if increment == 0:
            return True  # 已经是目标大小

        # 调整窗口大小
        return self.resize_window(increment=increment, axis='horizontal')

    def send_text(self, text: str, window_id: int = None) -> bool:
        """向 window 发送文本"""
        args = ['send-text']
        if window_id:
            args.extend(['--match', f'id:{window_id}'])
        args.append(text)
        result = self._run(*args)
        return result.returncode == 0

    def get_window_pid(self, window_id: int) -> Optional[int]:
        """获取 window 的 shell PID"""
        for tab in self.list_tabs():
            for window in tab.windows:
                if window.id == window_id:
                    return window.pid
        return None

    def get_window_tty(self, window_id: int) -> Optional[str]:
        """获取 window 的 TTY 设备路径"""
        pid = self.get_window_pid(window_id)
        if not pid:
            return None

        import subprocess
        try:
            # 读取进程的 tty
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

    # ========== 辅助方法 ==========

    def get_current_tab(self) -> Optional[KittyTab]:
        """获取当前聚焦的 Tab"""
        for tab in self.list_tabs():
            if tab.is_focused:
                return tab
        return None

    def set_tab_layout(self, layout: str) -> bool:
        """设置当前 Tab 的布局"""
        result = self._run('set-layout', layout)
        return result.returncode == 0

    def set_enabled_layouts(self, layouts: list[str], configured: bool = False) -> bool:
        """设置当前 Tab 可用的布局列表"""
        args = ['set-enabled-layouts']
        if configured:
            args.append('--configured')
        args.extend(layouts)
        result = self._run(*args)
        return result.returncode == 0

    def get_current_window(self) -> Optional[KittyWindow]:
        """获取当前聚焦的 window"""
        for tab in self.list_tabs():
            for window in tab.windows:
                if window.is_focused:
                    return window
        return None

    def get_total_tab_columns(self) -> int:
        """获取当前 Tab 的总列数（所有窗口的列数之和）"""
        current_tab = self.get_current_tab()
        if not current_tab:
            return 0

        total_cols = sum(win.columns for win in current_tab.windows)
        # 加上窗口间的分隔符宽度（每个分隔符约 1 列）
        if len(current_tab.windows) > 1:
            total_cols += len(current_tab.windows) - 1

        return total_cols

    def get_window_at_prompt(self, window_id: int) -> bool:
        """检查窗口是否在提示符处（等待输入）

        Args:
            window_id: Kitty 窗口 ID

        Returns:
            是否在提示符处
        """
        for tab in self.list_tabs():
            for window in tab.windows:
                if window.id == window_id:
                    return window.at_prompt
        return False


def check_kitty_remote_control() -> tuple[bool, str]:
    """检查 Kitty Remote Control 是否可用"""
    if os.environ.get('TERM') != 'xterm-kitty':
        return False, "当前不在 Kitty 终端中运行"

    try:
        result = subprocess.run(['kitten', '@', 'ls'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            if 'remote control' in result.stderr.lower():
                return False, (
                    "Kitty Remote Control 未启用。\n"
                    "请在 kitty.conf 中添加: allow_remote_control yes\n"
                    "或使用: kitty -o allow_remote_control=yes"
                )
            return False, f"kitten @ ls 失败: {result.stderr}"
        return True, ""
    except FileNotFoundError:
        return False, "未找到 kitten 命令"
    except subprocess.TimeoutExpired:
        return False, "检查超时"
