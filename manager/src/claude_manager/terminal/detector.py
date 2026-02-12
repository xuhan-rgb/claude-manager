"""终端类型检测

自动检测当前运行的终端类型，返回对应的适配器。
"""

import os
import logging
from typing import Optional

from .adapter import TerminalAdapter
from .kitty_adapter import KittyAdapter
from .xterm_adapter import XtermAdapter
from .terminator_adapter import TerminatorAdapter
from ..config import get_terminal_config

logger = logging.getLogger(__name__)


def detect_terminal() -> str:
    """检测当前终端类型

    检测顺序：
    1. Kitty - 通过 $TERM 环境变量
    2. iTerm2 - 通过 $TERM_PROGRAM 环境变量（macOS）
    3. tmux - 通过 $TMUX 环境变量
    4. unknown - 未知终端

    Returns:
        终端类型字符串：'kitty', 'iterm', 'tmux', 'unknown'
    """
    term = os.environ.get('TERM', '')
    term_program = os.environ.get('TERM_PROGRAM', '')
    tmux = os.environ.get('TMUX', '')

    # 在 tmux 会话中（优先）
    if tmux:
        logger.info("[检测] 检测到 tmux 会话")
        return 'tmux'

    # 配置映射（允许按 TERM 进行覆盖）
    try:
        term_map = get_terminal_config().term_map
    except Exception:
        term_map = {}
    mapped = term_map.get(term)
    if mapped:
        logger.info(f"[检测] 使用配置映射: TERM={term} -> {mapped}")
        return mapped

    if os.environ.get("TERMINATOR_UUID") or os.environ.get("TERMINATOR_DBUS_NAME"):
        logger.info("[检测] 检测到 Terminator 终端")
        return "terminator"

    # Kitty 终端
    if term == 'xterm-kitty':
        logger.info("[检测] 检测到 Kitty 终端")
        return 'kitty'

    # iTerm2 终端（macOS）
    if term_program == 'iTerm.app':
        logger.info("[检测] 检测到 iTerm2 终端")
        return 'iterm'

    # XTerm / 兼容终端
    if term.startswith('xterm'):
        logger.info("[检测] 检测到 XTerm 兼容终端")
        return 'xterm'

    logger.info(f"[检测] 未知终端类型: TERM={term}, TERM_PROGRAM={term_program}")
    return 'unknown'


def get_adapter(terminal_type: Optional[str] = None) -> TerminalAdapter:
    """获取终端适配器

    Args:
        terminal_type: 终端类型，None 表示自动检测
            - 'kitty': Kitty 终端
            - 'iterm': iTerm2 终端（未实现）
            - 'tmux': 纯 tmux 模式
            - 'auto' 或 None: 自动检测

    Returns:
        TerminalAdapter 实例

    Raises:
        ValueError: 不支持的终端类型
    """
    if os.environ.get("TMUX"):
        raise ValueError("不支持在 tmux 会话中运行，请退出 tmux 后重试")

    if terminal_type is None or terminal_type == 'auto':
        config_terminal = get_terminal_config().terminal
        if config_terminal and config_terminal != 'auto':
            terminal_type = config_terminal
        else:
            terminal_type = detect_terminal()

    logger.info(f"[适配器] 使用终端类型: {terminal_type}")

    if terminal_type == 'kitty':
        adapter = KittyAdapter()
        ok, msg = adapter.is_available()
        if ok:
            return adapter
        raise ValueError(f"Kitty 不可用: {msg}")

    if terminal_type == 'iterm':
        raise ValueError("iTerm2 适配器未实现，请使用 Kitty 或 xterm")

    if terminal_type == 'tmux':
        raise ValueError("不支持在 tmux 会话中运行，请退出 tmux 后重试")

    if terminal_type == 'xterm':
        adapter = XtermAdapter()
        ok, msg = adapter.is_available()
        if ok:
            return adapter
        raise ValueError(f"xterm 不可用: {msg}")

    if terminal_type == 'terminator':
        adapter = TerminatorAdapter(layout=get_terminal_config().terminator.get("layout"))
        ok, msg = adapter.is_available()
        if ok:
            return adapter
        raise ValueError(f"terminator 不可用: {msg}")

    if terminal_type == 'unknown':
        raise ValueError("无法识别终端类型，请在配置中设置 term_map 或使用 Kitty/xterm")

    raise ValueError(f"不支持的终端类型: {terminal_type}")


def check_environment() -> tuple[bool, str, Optional[TerminalAdapter]]:
    """检查运行环境并返回可用的适配器

    Returns:
        (是否可用, 消息, 适配器实例或 None)
    """
    try:
        adapter = get_adapter()
        ok, msg = adapter.is_available()
        if ok:
            return True, f"使用 {adapter.name} 终端", adapter
        return False, msg, None
    except ValueError as e:
        return False, str(e), None
