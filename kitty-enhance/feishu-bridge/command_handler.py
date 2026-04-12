"""
飞书指令解析

将飞书消息文本解析为结构化指令，支持：
- 权限回复: y/n/yes/no/是/否
- 终端列表: ls/列表/list/终端
- 终端详情: #ID 或 @ID
- 终端进度: #ID 进度/屏幕/screen
- 终端指令: #ID <任意文本>

ID 支持：
- 兼容旧格式: #12
- 新格式: #12@mykitty-1827907
"""

import re


def parse_command(text: str) -> dict:
    """解析飞书消息为结构化指令"""
    text = text.strip()
    if not text:
        return {"type": "unknown"}

    lower = text.lower()

    # 权限回复（最高优先级，兼容现有功能）
    if lower in ("y", "n", "yes", "no", "是", "否"):
        return {"type": "permission_reply", "answer": lower}

    # 帮助
    if lower in ("help", "?", "？", "帮助"):
        return {"type": "help"}

    # 终端列表（ls -l 详细模式）- 先检查长格式
    if lower == "ls -l":
        return {"type": "list_terminals", "detail": True}
    if lower in ("ls", "列表", "list", "终端"):
        return {"type": "list_terminals", "detail": False}

    # #ID / @ID / ＃ID 开头的指令（不再匹配纯数字，避免误触）
    # 兼容全角 ＃（飞书输入法可能产生）
    match = re.match(r"[#@＃]([^\s]+)\s*(.*)", text)
    if match:
        selector = match.group(1)
        rest = match.group(2).strip()
        if not rest:
            return {"type": "terminal_detail", "window_id": selector}
        if rest in ("进度", "屏幕", "screen", "progress", "log"):
            return {"type": "terminal_screen", "window_id": selector}
        # 特殊按键指令
        if rest.lower() == "esc":
            return {"type": "terminal_key", "window_id": selector, "key": "esc"}
        if rest.lower() == "ctrl+c":
            return {"type": "terminal_key", "window_id": selector, "key": "ctrl-c"}
        if rest.lower() == "clear":
            return {"type": "terminal_clear", "window_id": selector}
        return {"type": "terminal_command", "window_id": selector, "text": rest}

    # 不匹配任何指令 → 静默忽略
    return {"type": "ignore"}
