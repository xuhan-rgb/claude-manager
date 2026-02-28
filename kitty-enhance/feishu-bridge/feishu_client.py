"""
飞书 API 封装

功能：
- 发送卡片消息到指定用户
- WebSocket 长连接接收消息回复
- 回复确认消息
"""

from __future__ import annotations

import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ListMessageRequest,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
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
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    def send_permission_message(self, pending: dict) -> str:
        """发送待确认卡片消息（权限/文本输入/选择），返回 message_id"""
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
        reply_mode = pending.get("reply_mode", "permission")

        # 构造详情内容
        detail_lines = []
        if tab_title:
            detail_lines.append(f"**任务**: {tab_title}")
        if message:
            detail_lines.append(f"**类型**: {message}")
        detail_lines.append(f"**等待**: {wait_str}")

        wid = pending.get("window_id", "?")

        if reply_mode == "selection":
            header_text = f"🔵 Claude Code 等待选择 [窗口 {wid}]"
            options = pending.get("options", [])
            text_input_options = set(pending.get("text_input_options", []))
            descriptions = pending.get("descriptions", {})
            question = pending.get("question", "")

            # 显示问题上下文（选项上方的说明文本）
            if question:
                # 截断过长的上下文，保留核心内容
                if len(question) > 800:
                    question = question[-800:]
                detail_lines.append(f"\n```\n{question}\n```")

            # 显示选项列表
            if options:
                detail_lines.append("")
                for i, opt in enumerate(options, 1):
                    marker = "📝" if i in text_input_options else f"**{i}.**"
                    detail_lines.append(f"{marker} {opt}")
                    # 显示选项描述（如有，且与选项文本不同）
                    desc = descriptions.get(i, "")
                    if desc and desc != opt:
                        detail_lines.append(f"　　{desc}")
            else:
                if screen_tail:
                    screen_preview = screen_tail[-500:] if len(screen_tail) > 500 else screen_tail
                    detail_lines.append(f"\n**终端内容**:\n```\n{screen_preview}\n```")

            # 构造回复提示
            hint_parts = [f"↩️ 回复本卡片 **1** ~ **{len(options)}**　或　发送 **#{wid} 数字**"]
            if text_input_options:
                ti = min(text_input_options)
                hint_parts.append(f"📝 选项需附文字：**{ti} 你的内容**　或　**#{wid} {ti} 你的内容**")
            hint_parts.append(f"❌ 取消：**esc**　或　**#{wid} esc**")
            reply_hint = "\n".join(hint_parts)
            card_template = "blue"

        elif reply_mode == "text_input":
            header_text = f"🟡 Claude Code 等待输入 [窗口 {wid}]"
            reply_hint = (
                f"↩️ 回复本卡片输入文字　或　发送 **#{wid} 你的文本**\n"
                f"❌ 回复 **取消**　或　**#{wid} 取消**"
            )
            card_template = "yellow"
            if screen_tail:
                screen_preview = screen_tail[-500:] if len(screen_tail) > 500 else screen_tail
                detail_lines.append(f"\n**终端内容**:\n```\n{screen_preview}\n```")

        else:
            header_text = f"🟡 Claude Code 权限确认 [窗口 {wid}]"
            reply_hint = (
                f"↩️ 回复本卡片 **y** 允许 / **n** 拒绝\n"
                f"📌 或发送 **#{wid} y** / **#{wid} n**"
            )
            card_template = "yellow"
            if screen_tail:
                screen_preview = screen_tail[-500:] if len(screen_tail) > 500 else screen_tail
                detail_lines.append(f"\n**终端内容**:\n```\n{screen_preview}\n```")

        detail_content = "\n".join(detail_lines)

        # 构造卡片
        card = json.dumps(
            {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": card_template,
                    "title": {
                        "tag": "plain_text",
                        "content": header_text,
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
                        "content": reply_hint,
                    },
                ],
            },
            ensure_ascii=False,
        )

        msg_id = self._send_card(card)
        if msg_id:
            logger.info("飞书消息发送成功: message_id=%s", msg_id)
        return msg_id

    def send_text_message(self, text: str) -> str:
        """发送纯文本消息，返回 message_id"""
        content = json.dumps({"text": text}, ensure_ascii=False)
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self.user_id)
                .msg_type("text")
                .content(content)
                .build()
            )
            .build()
        )
        resp = self.client.im.v1.message.create(request)
        if not resp.success():
            logger.error("飞书文本发送失败: code=%s, msg=%s", resp.code, resp.msg)
            return ""
        return resp.data.message_id

    def send_terminal_list(self, terminals: list[dict]) -> str:
        """发送终端列表卡片"""
        from terminal_registry import STATUS_ICON, STATUS_TEXT, format_time_ago

        if not terminals:
            return self.send_text_message("📋 当前没有在线的 Claude 终端")

        lines = []
        for t in terminals:
            icon = STATUS_ICON.get(t.get("status", "idle"), "⚪")
            status = STATUS_TEXT.get(t.get("status", "idle"), "未知")
            title = t.get("tab_title") or t.get("cwd", "").split("/")[-1] or "未知"
            ago = format_time_ago(t.get("last_activity", 0))
            lines.append(f"{icon} **#{t['window_id']}**  {title}　　{status}　{ago}")

        body = "\n".join(lines)
        card = json.dumps({
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": f"📋 Claude 终端列表（共 {len(terminals)} 个）",
                },
            },
            "elements": [
                {"tag": "markdown", "content": body},
                {"tag": "hr"},
                {"tag": "markdown", "content": "**#N** 详情　|　**#N 进度** 屏幕　|　**#N y/n** 权限　|　**ls -l** 预览"},
            ],
        }, ensure_ascii=False)

        return self._send_card(card)

    def send_terminal_detail(self, terminal: dict) -> str:
        """发送终端详情卡片"""
        from terminal_registry import STATUS_ICON, STATUS_TEXT, format_time_ago

        wid = terminal.get("window_id", "?")
        icon = STATUS_ICON.get(terminal.get("status", "idle"), "⚪")
        status = STATUS_TEXT.get(terminal.get("status", "idle"), "未知")
        title = terminal.get("tab_title") or "未知"
        cwd = terminal.get("cwd") or "未知"
        activity_ago = format_time_ago(terminal.get("last_activity", 0))
        reg_ago = format_time_ago(terminal.get("registered_at", 0))

        body = (
            f"📁 **项目**: {title}\n"
            f"📂 **路径**: {cwd}\n"
            f"{icon} **状态**: {status}\n"
            f"⏱️ **活跃**: {activity_ago}\n"
            f"📅 **注册**: {reg_ago}"
        )
        card = json.dumps({
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "turquoise",
                "title": {
                    "tag": "plain_text",
                    "content": f"📺 终端 #{wid} 详情",
                },
            },
            "elements": [
                {"tag": "markdown", "content": body},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**#{wid} 进度** 屏幕　|　**#{wid} y/n** 权限　|　**#{wid} 文本** 发指令"},
            ],
        }, ensure_ascii=False)

        return self._send_card(card)

    def send_terminal_screen(self, window_id: str, screen_text: str) -> str:
        """发送终端屏幕内容"""
        import time as _time

        now_str = _time.strftime("%H:%M:%S")
        if not screen_text:
            return self.send_text_message(f"📺 终端 #{window_id} 屏幕为空或无法抓取")

        # 截断过长内容
        if len(screen_text) > 1500:
            screen_text = screen_text[-1500:]

        body = f"```\n{screen_text}\n```\n\n最后 20 行 | 抓取于 {now_str}"
        card = json.dumps({
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "purple",
                "title": {
                    "tag": "plain_text",
                    "content": f"📺 终端 #{window_id} 屏幕内容",
                },
            },
            "elements": [
                {"tag": "markdown", "content": body},
            ],
        }, ensure_ascii=False)

        return self._send_card(card)

    def _send_card(self, card_json: str) -> str:
        """通用卡片发送"""
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self.user_id)
                .msg_type("interactive")
                .content(card_json)
                .build()
            )
            .build()
        )
        resp = self.client.im.v1.message.create(request)
        if not resp.success():
            logger.error("飞书卡片发送失败: code=%s, msg=%s", resp.code, resp.msg)
            return ""
        return resp.data.message_id

    def list_messages(self, chat_id: str, start_time: int, page_size: int = 5) -> list[dict]:
        """拉取指定聊天的最新消息（用于轮询兜底）

        参数:
            chat_id: 聊天 ID（P2P 或群聊）
            start_time: 起始时间戳（秒级），只返回此时间之后的消息
            page_size: 每页条数
        返回:
            [{message_id, text, parent_id, sender_id, sender_type, create_time}]
        """
        request = (
            ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(chat_id)
            .start_time(str(start_time))
            .sort_type("ByCreateTimeAsc")
            .page_size(page_size)
            .build()
        )
        resp = self.client.im.v1.message.list(request)
        if not resp.success():
            logger.debug("拉取消息失败: code=%s, msg=%s", resp.code, resp.msg)
            return []

        results = []
        items = resp.data.items if resp.data and resp.data.items else []
        for msg in items:
            if msg.msg_type != "text":
                continue
            # 解析消息内容
            try:
                body_content = msg.body.content if msg.body else ""
                content = json.loads(body_content) if body_content else {}
                text = content.get("text", "").strip()
            except (json.JSONDecodeError, AttributeError):
                continue
            if not text:
                continue

            sender_type = msg.sender.sender_type if msg.sender else ""
            # 跳过机器人自己发的消息
            if sender_type != "user":
                continue

            results.append({
                "message_id": msg.message_id,
                "text": text,
                "parent_id": getattr(msg, "parent_id", "") or "",
                "sender_id": msg.sender.id if msg.sender else "",
                "create_time": int(msg.create_time) if msg.create_time else 0,
            })
        return results

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
            log_level=lark.LogLevel.INFO,
        )

        logger.info("飞书 WebSocket 监听启动...")
        ws_client.start()  # 阻塞运行，自动重连
