"""
飞书 API 封装

功能：
- 发送卡片消息到指定用户
- WebSocket 长连接接收消息回复
- 回复确认消息
"""

import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    P2ImMessageReceiveV1,
)

logger = logging.getLogger("feishu-bridge")


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str, user_id: str):
        """
        参数:
            app_id: 飞书自建应用 App ID
            app_secret: 飞书自建应用 App Secret
            user_id: 接收消息的用户 open_id
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.user_id = user_id
        self.client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

    def send_permission_message(self, pending: dict) -> str:
        """发送权限确认卡片消息，返回 message_id"""
        # 计算等待时长
        import time

        age = time.time() - pending.get("timestamp", time.time())
        minutes = int(age // 60)
        seconds = int(age % 60)
        wait_str = f"{minutes} 分 {seconds} 秒" if minutes > 0 else f"{seconds} 秒"

        # 从 pending 提取信息
        tab_title = pending.get("tab_title", "")
        screen_tail = pending.get("screen_tail", "")
        message = pending.get("message", "")

        # 构造详情内容
        detail_lines = []
        if tab_title:
            detail_lines.append(f"**任务**: {tab_title}")
        if message:
            detail_lines.append(f"**类型**: {message}")
        detail_lines.append(f"**等待**: {wait_str}")

        # 终端屏幕截取（展示实际的权限弹窗内容）
        if screen_tail:
            # 截取关键部分，去掉太长的内容
            screen_preview = screen_tail[-500:] if len(screen_tail) > 500 else screen_tail
            detail_lines.append(f"\n**终端内容**:\n```\n{screen_preview}\n```")

        detail_content = "\n".join(detail_lines)

        # 构造卡片
        card = json.dumps(
            {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "yellow",
                    "title": {
                        "tag": "plain_text",
                        "content": f"🟡 Claude Code 权限确认 [窗口 {pending.get('window_id', '?')}]",
                    },
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": detail_content,
                    },
                    {"tag": "hr"},
                    {
                        "tag": "markdown",
                        "content": "回复 **y** 允许 | 回复 **n** 拒绝",
                    },
                ],
            },
            ensure_ascii=False,
        )

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self.user_id)
                .msg_type("interactive")
                .content(card)
                .build()
            )
            .build()
        )

        resp: CreateMessageResponse = self.client.im.v1.message.create(request)
        if not resp.success():
            logger.error(
                "飞书消息发送失败: code=%s, msg=%s", resp.code, resp.msg
            )
            return ""

        msg_id = resp.data.message_id
        logger.info("飞书消息发送成功: message_id=%s", msg_id)
        return msg_id

    def reply_message(self, msg_id: str, text: str):
        """回复一条文本消息"""
        content = json.dumps({"text": text}, ensure_ascii=False)
        request = (
            ReplyMessageRequest.builder()
            .message_id(msg_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("text")
                .content(content)
                .build()
            )
            .build()
        )

        resp = self.client.im.v1.message.reply(request)
        if not resp.success():
            logger.error(
                "飞书回复失败: code=%s, msg=%s", resp.code, resp.msg
            )

    def start_ws_listener(self, on_reply_callback):
        """
        启动 WebSocket 长连接监听消息回复

        参数:
            on_reply_callback: 回调函数，签名 (data: P2ImMessageReceiveV1) -> None
        """
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_reply_callback)
            .build()
        )

        ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
        )

        logger.info("飞书 WebSocket 监听启动...")
        ws_client.start()  # 阻塞运行，自动重连
