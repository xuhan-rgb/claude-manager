"""
Claude Manager - 终端分屏 + tmux session 任务管理器

支持的终端：
- Kitty (推荐，需启用 allow_remote_control)
- 纯 tmux 模式（在任何终端内运行）

架构：
- 左侧窗口：TUI 面板
- 右侧窗口：tmux 客户端
- 每个任务 = 一个 tmux session（可包含多个 window）
- 切换任务 = 切换 tmux session
"""

__version__ = "0.3.0"
__author__ = "User"

# 终端适配器（新接口）
from .terminal import (
    TerminalAdapter,
    KittyAdapter,
    TmuxSplitAdapter,
    get_adapter,
    check_environment,
)

# 向后兼容：KittyController 仍然可用
from .terminal.kitty_adapter import KittyAdapter as KittyController

# tmux 会话管理
from .tmux_control import TmuxController

# 数据模型
from .models import Task, Terminal, Layout

# 启动函数
from .launcher import launch_tui_with_split, launch_split_layout

__all__ = [
    # 终端适配器
    "TerminalAdapter",
    "KittyAdapter",
    "TmuxSplitAdapter",
    "get_adapter",
    "check_environment",
    # 向后兼容
    "KittyController",
    # tmux
    "TmuxController",
    # 数据模型
    "Task",
    "Terminal",
    "Layout",
    # 启动函数
    "launch_tui_with_split",
    "launch_split_layout",
]
