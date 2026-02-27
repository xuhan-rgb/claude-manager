"""
Kitty 终端交互模块

- send_keystroke: 向窗口发送按键（权限回复、指令输入）
- get_terminal_screen: 抓取窗口屏幕内容（进度查看）
"""

import json
import logging
import subprocess

logger = logging.getLogger("feishu-bridge")


def focus_window(window_id: str, socket: str = "unix:@mykitty"):
    """
    聚焦指定的 kitty 窗口

    参数:
        window_id: kitty 窗口 ID
        socket: kitty remote control socket 地址
    """
    cmd = [
        "kitty", "@", "--to", socket,
        "focus-window", "--match", f"id:{window_id}",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            logger.debug("窗口已聚焦: window=%s", window_id)
        else:
            logger.warning("窗口聚焦失败: window=%s, stderr=%s", window_id, result.stderr.strip())
    except subprocess.TimeoutExpired:
        logger.error("窗口聚焦超时: window=%s", window_id)
    except FileNotFoundError:
        logger.error("kitty 命令未找到")


def send_keystroke(window_id: str, text: str, socket: str = "unix:@mykitty"):
    """
    向指定 kitty 窗口发送按键

    参数:
        window_id: kitty 窗口 ID
        text: 要发送的文本（如 "y\\r"）
        socket: kitty remote control socket 地址
    """
    # 先聚焦窗口，确保按键能发送到未选中的窗口
    focus_window(window_id, socket)

    cmd = [
        "kitty", "@", "--to", socket,
        "send-text", "--match", f"id:{window_id}", text,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            logger.info("按键已发送: window=%s, text=%r", window_id, text)
        else:
            logger.error(
                "按键发送失败: window=%s, stderr=%s",
                window_id, result.stderr.strip(),
            )
    except subprocess.TimeoutExpired:
        logger.error("按键发送超时: window=%s", window_id)
    except FileNotFoundError:
        logger.error("kitty 命令未找到，请确认 kitty 已安装")


def send_key(window_id: str, key_name: str, socket: str = "unix:@mykitty"):
    """
    向指定 kitty 窗口发送键盘事件（非文本字符）

    参数:
        window_id: kitty 窗口 ID
        key_name: 键名，如 "enter", "escape", "tab"
        socket: kitty remote control socket 地址
    """
    # 先聚焦窗口，确保按键能发送到未选中的窗口
    focus_window(window_id, socket)

    cmd = [
        "kitty", "@", "--to", socket,
        "send-key", "--match", f"id:{window_id}", key_name,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            logger.info("键盘事件已发送: window=%s, key=%s", window_id, key_name)
        else:
            logger.error(
                "键盘事件发送失败: window=%s, stderr=%s",
                window_id, result.stderr.strip(),
            )
    except subprocess.TimeoutExpired:
        logger.error("键盘事件发送超时: window=%s", window_id)
    except FileNotFoundError:
        logger.error("kitty 命令未找到，请确认 kitty 已安装")


def clear_screen(window_id: str, socket: str = "unix:@mykitty"):
    """清空指定窗口的屏幕"""
    cmd = [
        "kitty", "@", "--to", socket,
        "clear-screen", "--match", f"id:{window_id}",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            logger.info("屏幕已清空: window=%s", window_id)
        else:
            logger.error("清屏失败: window=%s, stderr=%s", window_id, result.stderr.strip())
    except subprocess.TimeoutExpired:
        logger.error("清屏超时: window=%s", window_id)
    except FileNotFoundError:
        logger.error("kitty 命令未找到")


def get_terminal_screen(
    window_id: str, socket: str = "unix:@mykitty", lines: int = 20
) -> str:
    """抓取终端屏幕内容，返回最后 N 行非空行"""
    cmd = [
        "kitty", "@", "--to", socket,
        "get-text", "--match", f"id:{window_id}", "--extent=screen",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return ""
        all_lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        return "\n".join(all_lines[-lines:])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
