"""终端适配器模块

提供统一的终端操作接口，支持 Kitty、tmux 等终端。

使用示例：
    from claude_manager.terminal import get_adapter

    adapter = get_adapter()  # 自动检测终端类型
    # 或指定类型
    adapter = get_adapter('kitty')

    # 创建分屏
    result = adapter.create_split(direction='vertical', command='bash')
    if result.success:
        print(f"新窗口 ID: {result.window_id}")

    # 获取窗口信息
    windows = adapter.list_windows()
    for win in windows:
        print(f"{win.id}: {win.columns}x{win.lines}")
"""

from .adapter import (
    TerminalAdapter,
    WindowInfo,
    SplitResult,
    PanelConfig,
    LayoutConfig,
)
from .detector import (
    get_adapter,
    detect_terminal,
    check_environment,
)
from .kitty_adapter import KittyAdapter
from .tmux_split_adapter import TmuxSplitAdapter
from .xterm_adapter import XtermAdapter
from .terminator_adapter import TerminatorAdapter

__all__ = [
    # 抽象接口
    'TerminalAdapter',
    'WindowInfo',
    'SplitResult',
    'PanelConfig',
    'LayoutConfig',
    # 具体适配器
    'KittyAdapter',
    'TmuxSplitAdapter',
    'XtermAdapter',
    'TerminatorAdapter',
    # 工厂函数
    'get_adapter',
    'detect_terminal',
    'check_environment',
]
