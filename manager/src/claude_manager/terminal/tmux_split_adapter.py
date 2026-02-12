"""纯 tmux 分屏适配器

使用 tmux 自身的分屏功能实现终端操作，可在任何终端上工作。
这是一个兜底方案，当 Kitty/iTerm2 不可用时使用。
"""

import subprocess
import os
from typing import Optional, List

from .adapter import TerminalAdapter, WindowInfo, SplitResult


class TmuxSplitAdapter(TerminalAdapter):
    """纯 tmux 分屏适配器

    使用 tmux split-window 实现分屏，适用于任何终端。

    工作原理：
    - 在当前 tmux 会话中创建分屏（pane）
    - 每个 pane 可以运行不同的命令
    - 通过 pane ID 进行管理
    """

    def __init__(self):
        """初始化"""
        self._manager_session = "cm-manager"  # 管理器所在的 tmux 会话名

    @property
    def name(self) -> str:
        return "tmux"

    def _run(self, *args, timeout: float = 2.0) -> subprocess.CompletedProcess:
        """执行 tmux 命令"""
        cmd = ['tmux'] + list(args)
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 1, '', 'timeout')
        except FileNotFoundError:
            return subprocess.CompletedProcess(cmd, 1, '', 'tmux not found')

    def is_available(self) -> tuple[bool, str]:
        """检查 tmux 是否可用"""
        # 检查 tmux 是否安装
        result = self._run('-V')
        if result.returncode != 0:
            return False, "未找到 tmux，请安装: sudo apt install tmux"

        version = result.stdout.strip()

        # 检查是否在 tmux 会话中
        if not os.environ.get('TMUX'):
            return False, f"tmux 已安装 ({version})，但当前不在 tmux 会话中"

        return True, f"tmux 可用 ({version})"

    def _get_current_pane(self) -> Optional[str]:
        """获取当前 pane ID"""
        result = self._run('display-message', '-p', '#{pane_id}')
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    # ========== 窗口操作 ==========

    def create_split(
        self,
        direction: str = "vertical",
        command: str = "bash",
        cwd: Optional[str] = None
    ) -> SplitResult:
        """创建分屏窗口

        tmux 的分屏方向与通常定义相反：
        - -h: horizontal split（水平分割线 → 左右排列）
        - -v: vertical split（垂直分割线 → 上下排列）
        """
        # 构建命令参数
        args = ['split-window']

        # tmux 的 -h 是水平分割（左右排列），对应我们的 vertical
        if direction == "vertical":
            args.append('-h')
        else:
            args.append('-v')

        if cwd:
            args.extend(['-c', cwd])

        # 添加 -P -F 获取新 pane 的 ID
        args.extend(['-P', '-F', '#{pane_id}'])

        # 添加命令
        args.append(command)

        result = self._run(*args)
        if result.returncode != 0:
            return SplitResult(False, error=result.stderr or "创建分屏失败")

        pane_id = result.stdout.strip()
        return SplitResult(True, window_id=pane_id)

    def close_window(self, window_id: str) -> bool:
        """关闭窗口（pane）"""
        result = self._run('kill-pane', '-t', window_id)
        return result.returncode == 0

    def focus_window(self, window_id: str) -> bool:
        """聚焦窗口（pane）"""
        result = self._run('select-pane', '-t', window_id)
        return result.returncode == 0

    def resize_window(
        self,
        window_id: str,
        columns: Optional[int] = None,
        increment: Optional[int] = None,
        axis: str = "horizontal"
    ) -> bool:
        """调整窗口大小"""
        if columns is not None:
            # 获取当前宽度
            current_info = self.get_window_info(window_id)
            if not current_info:
                return False
            increment = columns - current_info.columns
            if increment == 0:
                return True

        if increment is None:
            return False

        # tmux resize-pane 参数
        # -L: 向左调整（减少宽度）
        # -R: 向右调整（增加宽度）
        # -U: 向上调整
        # -D: 向下调整
        if axis == "horizontal":
            direction = '-R' if increment > 0 else '-L'
        else:
            direction = '-D' if increment > 0 else '-U'

        result = self._run('resize-pane', '-t', window_id, direction, str(abs(increment)))
        return result.returncode == 0

    def send_text(self, text: str, window_id: Optional[str] = None) -> bool:
        """向窗口发送文本"""
        args = ['send-keys']
        if window_id:
            args.extend(['-t', window_id])
        args.append(text)
        result = self._run(*args)
        return result.returncode == 0

    # ========== 信息获取 ==========

    def get_window_info(self, window_id: str) -> Optional[WindowInfo]:
        """获取窗口（pane）信息"""
        # 获取 pane 信息
        format_str = '#{pane_id}:#{pane_width}:#{pane_height}:#{pane_tty}:#{pane_active}:#{pane_title}:#{pane_pid}:#{pane_current_path}'
        result = self._run('list-panes', '-F', format_str)
        if result.returncode != 0:
            return None

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split(':')
            if len(parts) >= 8 and parts[0] == window_id:
                return WindowInfo(
                    id=parts[0],
                    columns=int(parts[1]) if parts[1].isdigit() else 0,
                    lines=int(parts[2]) if parts[2].isdigit() else 0,
                    tty=parts[3] if parts[3] else None,
                    is_focused=(parts[4] == '1'),
                    title=parts[5],
                    pid=int(parts[6]) if parts[6].isdigit() else 0,
                    cwd=parts[7],
                )
        return None

    def get_current_window(self) -> Optional[WindowInfo]:
        """获取当前聚焦的窗口"""
        pane_id = self._get_current_pane()
        if pane_id:
            return self.get_window_info(pane_id)
        return None

    def list_windows(self) -> List[WindowInfo]:
        """列出当前窗口中的所有 pane"""
        format_str = '#{pane_id}:#{pane_width}:#{pane_height}:#{pane_tty}:#{pane_active}:#{pane_title}:#{pane_pid}:#{pane_current_path}'
        result = self._run('list-panes', '-F', format_str)
        if result.returncode != 0:
            return []

        windows = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split(':')
            if len(parts) >= 8:
                windows.append(WindowInfo(
                    id=parts[0],
                    columns=int(parts[1]) if parts[1].isdigit() else 0,
                    lines=int(parts[2]) if parts[2].isdigit() else 0,
                    tty=parts[3] if parts[3] else None,
                    is_focused=(parts[4] == '1'),
                    title=parts[5],
                    pid=int(parts[6]) if parts[6].isdigit() else 0,
                    cwd=parts[7],
                ))
        return windows

    def get_total_columns(self) -> int:
        """获取当前窗口的总列数"""
        # tmux 中获取窗口总宽度
        result = self._run('display-message', '-p', '#{window_width}')
        if result.returncode == 0:
            try:
                return int(result.stdout.strip())
            except ValueError:
                pass
        return 0

    # ========== 布局管理 ==========

    def set_layout(self, layout: str) -> bool:
        """设置布局模式

        tmux 支持的布局：
        - even-horizontal: 所有 pane 等宽水平排列
        - even-vertical: 所有 pane 等高垂直排列
        - main-horizontal: 主 pane 在上，其他在下
        - main-vertical: 主 pane 在左，其他在右
        - tiled: 平铺
        """
        # 将通用布局名映射到 tmux 布局
        layout_map = {
            'splits': 'main-vertical',
            'stack': 'even-vertical',
            'tall': 'main-horizontal',
            'even-horizontal': 'even-horizontal',
            'even-vertical': 'even-vertical',
            'main-horizontal': 'main-horizontal',
            'main-vertical': 'main-vertical',
            'tiled': 'tiled',
        }
        tmux_layout = layout_map.get(layout, layout)

        result = self._run('select-layout', tmux_layout)
        return result.returncode == 0

    def lock_layout(self, layouts: List[str]) -> bool:
        """锁定可用布局

        tmux 不支持锁定布局，总是返回 True
        """
        return True


def check_tmux() -> tuple[bool, str]:
    """检查 tmux 是否可用（兼容旧接口）"""
    try:
        result = subprocess.run(['tmux', '-V'], capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "tmux 命令执行失败"
    except FileNotFoundError:
        return False, "未找到 tmux，请安装: sudo apt install tmux"
