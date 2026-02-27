"""
Kitty 按键发送模块

通过 kitty @ send-text 向指定窗口发送按键，
用于自动回答 Claude Code 权限弹窗。
"""

import logging
import subprocess

logger = logging.getLogger("feishu-bridge")


def send_keystroke(window_id: str, text: str, socket: str = "unix:@mykitty"):
    """
    向指定 kitty 窗口发送按键

    参数:
        window_id: kitty 窗口 ID
        text: 要发送的文本（如 "y\\n"）
        socket: kitty remote control socket 地址
    """
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
