"""
飞书终端管理中心守护进程

功能：
- 监控权限弹窗，超时发飞书通知，用户回复 y/n 自动操作终端
- 终端注册表：自动发现和管理多个 Claude 终端
- 飞书指令：ls 列表、#N 详情、#N 进度、#N 指令

启动: python daemon.py
停止: python daemon.py stop
状态: python daemon.py status
"""

from __future__ import annotations

import glob
import json
from typing import List
import logging
import os
import signal
import sys
import threading
import time

import yaml

from command_handler import parse_command
from feishu_client import FeishuClient
from kitty_responder import clear_screen, get_terminal_screen, send_key, send_keystroke
from terminal_registry import (
    cleanup_all_kitty,
    get_terminal_info,
    load_registry,
    scan_all_kitty,
    scan_and_register,
    STATUS_TEXT,
)

# ── 日志配置 ──────────────────────────────────────────

STATE_DIR = "/tmp/feishu-bridge"
PID_FILE = os.path.join(STATE_DIR, "daemon.pid")
LOG_FILE = os.path.join(STATE_DIR, "daemon.log")


def setup_logging():
    os.makedirs(STATE_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    # 静默 SDK 和 HTTP 库的 DEBUG 日志
    for name in ("urllib3", "httpcore", "httpx", "websockets"):
        logging.getLogger(name).setLevel(logging.WARNING)


logger = logging.getLogger("feishu-bridge")

TEXT_INPUT_MESSAGE_HINTS = (
    "waiting for your input",
    "waiting for input",
    "需要你的输入",
    "等待你的输入",
    "需要你输入",
)

PERMISSION_MESSAGE_HINTS = (
    "permission",
    "权限",
    "allow",
    "approve",
)

# 选择弹窗特征（AskUserQuestion）
SELECTION_SCREEN_HINTS = (
    "enter to select",
    "↑/↓ to navigate",
    "to navigate",
)

TEXT_INPUT_CANCEL_WORDS = ("cancel", "取消")

# 需要额外输入文字的选项关键词
SELECTION_TEXT_INPUT_KEYWORDS = ("type something", "chat about this")


def parse_selection_screen(screen_tail: str) -> dict:
    """从终端屏幕内容解析选择弹窗的问题上下文和选项

    返回 dict:
        question: 选项上方的问题/说明文本
        options: 选项文本列表（1-based 对应）
        text_input_indices: 需要输入文字的选项序号集合（1-based）
        descriptions: {序号: 描述文本} 选项下方的缩进描述行
    """
    import re
    options = []
    text_input_indices = set()
    descriptions: dict[int, str] = {}
    question_lines = []
    first_option_line = -1
    last_option_idx = 0

    lines = screen_tail.split("\n")
    option_pattern = re.compile(r"^[〉>›»]?\s*(\d+)\.\s+(.*)")

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        m = option_pattern.match(stripped)
        if m:
            idx = int(m.group(1))
            text = m.group(2).strip()
            if first_option_line < 0:
                first_option_line = i

            # 填充缺失的选项（序号跳跃）
            while len(options) < idx - 1:
                options.append(f"选项 {len(options) + 1}")
            if len(options) < idx:
                # TUI 选中项可能无文字（kitty get-text 捕获不到高亮行的文本）
                options.append(text if text else f"选项 {idx}")

            # 检测文字输入类选项
            if any(k in text.lower() for k in SELECTION_TEXT_INPUT_KEYWORDS):
                text_input_indices.add(idx)
            last_option_idx = idx
        elif first_option_line >= 0 and last_option_idx > 0:
            # 选项下方的缩进描述行
            if stripped and not option_pattern.match(stripped):
                desc = descriptions.get(last_option_idx, "")
                descriptions[last_option_idx] = (desc + " " + stripped).strip() if desc else stripped

    # 提取选项上方的问题上下文
    if first_option_line > 0:
        question_lines = [l for l in lines[:first_option_line] if l.strip()]
    question = "\n".join(question_lines).strip()

    # 补全：用描述行替换 "选项 N" 占位符
    for idx, desc in descriptions.items():
        if idx <= len(options) and options[idx - 1].startswith("选项 "):
            options[idx - 1] = desc

    return {
        "question": question,
        "options": options,
        "text_input_indices": text_input_indices,
        "descriptions": descriptions,
    }


# ── 配置加载 ──────────────────────────────────────────

def load_config(config_path: str | None) -> dict:
    """加载配置：环境变量优先，config.yaml 兜底"""
    file_cfg = {}
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            file_cfg = yaml.safe_load(f) or {}

    feishu_file = file_cfg.get("feishu", {})
    bridge_file = file_cfg.get("bridge", {})
    kitty_file = file_cfg.get("kitty", {})
    hub_file = file_cfg.get("hub", {})

    return {
        "feishu": {
            "app_id": feishu_file.get("app_id", "") or os.environ.get("FEISHU_APP_ID", ""),
            "app_secret": feishu_file.get("app_secret", "") or os.environ.get("FEISHU_APP_SECRET", ""),
            "user_id": feishu_file.get("user_id", "") or os.environ.get("FEISHU_USER_ID", ""),
            "chat_id": feishu_file.get("chat_id", "") or os.environ.get("FEISHU_CHAT_ID", ""),
        },
        "bridge": {
            "wait_minutes": float(os.environ.get("FEISHU_WAIT_MINUTES", 0) or bridge_file.get("wait_minutes", 5)),
            "poll_interval": int(os.environ.get("FEISHU_POLL_INTERVAL", 0) or bridge_file.get("poll_interval", 2)),
            "expire_minutes": int(os.environ.get("FEISHU_EXPIRE_MINUTES", 0) or bridge_file.get("expire_minutes", 30)),
            "poll_api_interval": int(bridge_file.get("poll_api_interval", 2)),
            "max_message_age": int(bridge_file.get("max_message_age", 300)),
        },
        "kitty": {
            "socket": kitty_file.get("socket", ""),
        },
        "hub": {
            "registry_cleanup_interval": int(hub_file.get("registry_cleanup_interval", 30)),
            "max_screen_lines": int(hub_file.get("max_screen_lines", 20)),
            "command_max_length": int(hub_file.get("command_max_length", 500)),
        },
    }


# ── 守护进程主体 ──────────────────────────────────────

class FeishuBridgeDaemon:
    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        feishu_cfg = self.config["feishu"]
        self.feishu = FeishuClient(
            feishu_cfg["app_id"],
            feishu_cfg["app_secret"],
            feishu_cfg["user_id"],
        )
        bridge_cfg = self.config["bridge"]
        self.wait_seconds = bridge_cfg["wait_minutes"] * 60
        self.poll_interval = bridge_cfg["poll_interval"]
        self.expire_seconds = bridge_cfg["expire_minutes"] * 60
        self.kitty_socket = self.config["kitty"]["socket"]
        hub_cfg = self.config["hub"]
        self.cleanup_interval = hub_cfg["registry_cleanup_interval"]
        self.max_screen_lines = hub_cfg["max_screen_lines"]
        self.command_max_length = hub_cfg["command_max_length"]
        self._pending_commands = {}  # {feishu_msg_id: {"window_id", "text", "timestamp"}}
        self._running = True
        self._start_time = time.time()  # 守护进程启动时间

        # 允许接收消息的用户 open_id（只处理该用户的消息）
        self._allowed_user_id = feishu_cfg["user_id"]

        # 消息过期阈值（秒）：超过此延迟的消息直接丢弃
        self.max_message_age = int(bridge_cfg.get("max_message_age", 300))

        # API 轮询兜底（降低 WebSocket 固有延迟）
        self.poll_api_interval = int(bridge_cfg.get("poll_api_interval", 2))
        self._chat_id = feishu_cfg.get("chat_id", "")  # P2P 聊天 ID，可自动捕获
        self._seen_msgs: dict[str, float] = {}  # {message_id: timestamp} 去重
        self._seen_lock = threading.Lock()

    def run(self):
        """启动守护进程"""
        os.makedirs(STATE_DIR, exist_ok=True)
        self._write_pid()

        # 注册信号处理
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # 启动飞书 WebSocket 监听线程
        ws_thread = threading.Thread(
            target=self._ws_listener_safe, daemon=True
        )
        ws_thread.start()
        logger.info(
            "守护进程启动 (pid=%d, 等待 %d 秒后通知)",
            os.getpid(), self.wait_seconds,
        )

        # 启动时扫描所有 kitty 实例，自动注册
        count = scan_all_kitty()
        if not count:
            # 兜底：用配置/环境变量中的 socket 扫描
            socket = self._detect_socket()
            if socket:
                scan_and_register(socket)

        # 启动 API 轮询线程（兜底快速通道）
        if self.poll_api_interval > 0:
            poll_thread = threading.Thread(
                target=self._poll_loop, daemon=True
            )
            poll_thread.start()
            logger.info("API 轮询已启动 (间隔 %ds)", self.poll_api_interval)
        else:
            logger.info("API 轮询已禁用 (poll_api_interval=0)")

        # 主循环：监控 pending 文件
        self._monitor_loop()

    def _ws_listener_safe(self):
        """WebSocket 监听包装，异常后自动重试"""
        while self._running:
            try:
                self.feishu.start_ws_listener(self._handle_reply)
            except Exception:
                logger.exception("WebSocket 监听异常，5 秒后重试")
                time.sleep(5)

    # ── 消息去重 ──────────────────────────────────────────

    def _is_new_message(self, message_id: str) -> bool:
        """线程安全的消息去重，首次见到返回 True"""
        with self._seen_lock:
            if message_id in self._seen_msgs:
                return False
            self._seen_msgs[message_id] = time.time()
            return True

    def _cleanup_seen_msgs(self):
        """清理 5 分钟前的去重记录"""
        cutoff = time.time() - 300
        with self._seen_lock:
            expired = [k for k, v in self._seen_msgs.items() if v < cutoff]
            for k in expired:
                del self._seen_msgs[k]

    # ── API 轮询 ──────────────────────────────────────────

    def _poll_loop(self):
        """API 轮询主循环：定期拉取最新消息，与 WebSocket 双通道去重"""
        # 等待 chat_id（从 config 或 WebSocket 首条消息自动捕获）
        while self._running and not self._chat_id:
            time.sleep(1)
        if not self._running:
            return

        logger.info("[轮询] 启动, chat_id=%s", self._chat_id)
        # 从当前时间开始轮询（秒级时间戳）
        last_time = str(int(time.time()))

        while self._running:
            try:
                msgs = self.feishu.list_messages(self._chat_id, last_time, page_size=10)
                for m in msgs:
                    msg_id = m["message_id"]
                    if not self._is_new_message(msg_id):
                        continue
                    # 过滤发送者
                    if self._allowed_user_id and m.get("sender_id") != self._allowed_user_id:
                        continue
                    # 更新游标：用最新消息的 create_time（毫秒转秒 +1）
                    create_ts = m["create_time"]
                    if create_ts:
                        last_time = str(create_ts // 1000 + 1) if create_ts > 1e12 else str(create_ts + 1)

                    self._process_reply(m["text"], m["parent_id"], create_ts)
            except Exception:
                logger.exception("[轮询] 异常")

            time.sleep(self.poll_api_interval)

    def _monitor_loop(self):
        """主循环：扫描 pending 文件，超时发飞书通知，定期清理注册表"""
        last_cleanup = 0
        skip_files = {"daemon.pid", "registry.json"}
        while self._running:
            now = time.time()
            # 处理 pending 权限文件
            for filepath in glob.glob(os.path.join(STATE_DIR, "*.json")):
                basename = os.path.basename(filepath)
                if basename in skip_files:
                    continue
                # 跳过 _completed 后缀的文件（单独处理）
                if basename.endswith("_completed.json"):
                    continue
                try:
                    self._process_pending(filepath, now)
                except Exception:
                    logger.exception("处理 pending 文件异常: %s", filepath)

            # 处理完成通知文件（立即发送飞书通知）
            for filepath in glob.glob(os.path.join(STATE_DIR, "*_completed.json")):
                try:
                    self._process_completed(filepath)
                except Exception:
                    logger.exception("处理 completed 文件异常: %s", filepath)

            # 定期维护注册表：扫描所有 kitty 实例 + 清理已关闭终端
            if now - last_cleanup >= self.cleanup_interval:
                last_cleanup = now
                scan_all_kitty()
                removed = cleanup_all_kitty()
                if removed:
                    logger.info("注册表清理: 移除 %d 个终端", removed)
                # 清理过期的待确认指令（5 分钟）
                expired = [k for k, v in self._pending_commands.items()
                           if now - v["timestamp"] > 300]
                for k in expired:
                    del self._pending_commands[k]
                # 清理消息去重记录
                self._cleanup_seen_msgs()

            time.sleep(self.poll_interval)

    def _detect_socket(self) -> str:
        """获取 kitty socket：配置 > 注册表 > 环境变量"""
        if self.kitty_socket:
            return self.kitty_socket
        # 从注册表中取第一个有效的 socket
        registry = load_registry()
        for info in registry.values():
            s = info.get("kitty_socket", "")
            if s:
                return s
        # 兜底：环境变量
        return os.environ.get("KITTY_LISTEN_ON", "")

    def _detect_pending_mode(self, pending: dict) -> str:
        """识别 pending 类型：permission / text_input / selection"""
        mode = pending.get("reply_mode")
        if mode in ("permission", "text_input", "selection"):
            return mode

        message = str(pending.get("message", "")).strip().lower()
        screen_tail = str(pending.get("screen_tail", "")).strip().lower()

        # 选择弹窗优先检测（屏幕含 "Enter to select · ↑/↓ to navigate"）
        if any(k in screen_tail for k in SELECTION_SCREEN_HINTS):
            return "selection"

        if any(k in message for k in TEXT_INPUT_MESSAGE_HINTS):
            return "text_input"
        if any(k in message for k in PERMISSION_MESSAGE_HINTS):
            return "permission"

        # hook message 不稳定时，结合终端内容做保守兜底
        if "需要确认" in screen_tail and "回复" in screen_tail:
            return "text_input"

        return "permission"

    def _find_pending_request(self, parent_id: str = "") -> tuple[str | None, dict | None]:
        """按 parent_id 精确定位 pending；无 parent_id 时返回最新 notified 的 pending"""
        skip_files = {"daemon.pid", "registry.json"}
        pattern = os.path.join(STATE_DIR, "*.json")
        matched_file = None
        matched_pending = None
        latest_ts = 0

        for filepath in glob.glob(pattern):
            basename = os.path.basename(filepath)
            if basename in skip_files or basename.endswith("_completed.json"):
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    pending = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                continue

            if parent_id and pending.get("feishu_msg_id") == parent_id:
                return filepath, pending

            if not parent_id and pending.get("notified"):
                ts = pending.get("timestamp", 0)
                if ts > latest_ts:
                    latest_ts = ts
                    matched_file = filepath
                    matched_pending = pending

        return matched_file, matched_pending

    def _find_pending_by_window(self, window_id: str) -> tuple[str | None, dict | None]:
        """通过 window_id 精确查找已通知的 pending 文件"""
        skip_files = {"daemon.pid", "registry.json"}
        pattern = os.path.join(STATE_DIR, "*.json")
        for filepath in glob.glob(pattern):
            basename = os.path.basename(filepath)
            if basename in skip_files or basename.endswith("_completed.json"):
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    pending = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                continue
            if pending.get("window_id") == window_id and pending.get("notified"):
                return filepath, pending
        return None, None

    def _handle_parent_reply(self, text: str, parent_id: str) -> bool:
        """处理回复链中的消息（优先于普通命令解析）"""
        if not parent_id:
            return False

        # 终端指令确认（#N 文本在忙碌状态时触发）
        if parent_id in self._pending_commands:
            lower = text.lower()
            if lower in ("y", "n", "yes", "no", "是", "否"):
                self._execute_pending_command(lower, parent_id)
            else:
                self.feishu.reply_message(parent_id, "⚠️ 该确认仅支持回复 y 或 n")
            return True

        matched_file, matched_pending = self._find_pending_request(parent_id)
        if not matched_file or not matched_pending:
            return False

        mode = self._detect_pending_mode(matched_pending)

        # ── 选择弹窗：回复数字选择选项 ──
        if mode == "selection":
            return self._handle_selection_reply(
                text, parent_id, matched_file, matched_pending
            )

        # ── 文本输入 ──
        if mode == "text_input":
            if text.lower() in TEXT_INPUT_CANCEL_WORDS:
                try:
                    os.remove(matched_file)
                except FileNotFoundError:
                    pass
                self.feishu.reply_message(parent_id, "❌ 已取消本次输入")
                logger.info("取消文本输入: window=%s", matched_pending.get("window_id"))
                return True

            socket = matched_pending.get("kitty_socket") or self.kitty_socket
            wid = matched_pending["window_id"]
            send_keystroke(wid, text, socket)
            time.sleep(0.15)
            send_keystroke(wid, "\r", socket)
            try:
                os.remove(matched_file)
            except FileNotFoundError:
                pass
            self.feishu.reply_message(parent_id, "✅ 已发送文本到终端")
            logger.info(
                "文本输入完成: window=%s, text=%s",
                matched_pending["window_id"],
                text[:60],
            )
            return True

        # ── 权限确认 y/n ──
        lower = text.lower()
        if lower in ("y", "n", "yes", "no", "是", "否"):
            self._handle_permission_reply(lower, parent_id)
        else:
            self.feishu.reply_message(parent_id, "⚠️ 该请求是权限确认，请回复 y 或 n")
        return True

    def _process_pending(self, filepath: str, now: float):
        """处理单个 pending 文件"""
        with open(filepath, "r", encoding="utf-8") as f:
            pending = json.load(f)

        age = now - pending.get("timestamp", now)

        # 超过过期时间 → 清理
        if age >= self.expire_seconds:
            logger.info(
                "pending 已过期 (%d 秒)，清理: %s",
                int(age), filepath,
            )
            os.remove(filepath)
            return

        # 超过等待时间且未通知 → 发飞书
        if age >= self.wait_seconds and not pending.get("notified"):
            pending["reply_mode"] = self._detect_pending_mode(pending)

            # 选择弹窗：解析选项列表 + 问题上下文
            if pending["reply_mode"] == "selection":
                screen = pending.get("screen_tail", "")
                parsed = parse_selection_screen(screen)
                pending["options"] = parsed["options"]
                pending["option_count"] = len(parsed["options"])
                pending["text_input_options"] = list(parsed["text_input_indices"])
                pending["question"] = parsed["question"]
                pending["descriptions"] = parsed["descriptions"]

            logger.info(
                "超过等待时间 (%d 秒)，发送飞书通知: window=%s, mode=%s",
                int(age), pending.get("window_id"),
                pending["reply_mode"],
            )
            msg_id = self.feishu.send_permission_message(pending)
            if msg_id:
                pending["feishu_msg_id"] = msg_id
                pending["notified"] = True
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(pending, f, ensure_ascii=False, indent=2)

    def _process_completed(self, filepath: str):
        """处理完成通知文件：发送飞书通知后删除文件"""
        with open(filepath, "r", encoding="utf-8") as f:
            completed = json.load(f)

        window_id = completed.get("window_id", "?")
        tab_title = completed.get("tab_title", "")
        screen_tail = completed.get("screen_tail", "")
        last_agent_message = completed.get("last_agent_message", "")
        agent_name = completed.get("agent_name", "Claude")

        # 发送完成通知（带对话内容）
        header = f"✅ {agent_name} 完成响应 | 终端 #{window_id}"
        if tab_title:
            header += f" | {tab_title}"

        if last_agent_message:
            content = last_agent_message
            lines = [l for l in last_agent_message.strip().split("\n") if l.strip()]
        else:
            lines = [l for l in screen_tail.strip().split("\n") if l.strip()]
            content = "\n".join(lines[-30:]) if lines else "(无内容)"

        # 飞书卡片发送
        card = json.dumps({
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "green",
                "title": {"tag": "plain_text", "content": header},
            },
            "elements": [
                {"tag": "markdown", "content": f"```\n{content}\n```"},
                {"tag": "hr"},
                {"tag": "markdown", "content": "回复 **#N <指令>** 继续对话"},
            ],
        }, ensure_ascii=False)

        self.feishu._send_card(card)
        logger.info("发送完成通知: window=%s, lines=%d", window_id, len(lines))

        # 删除完成通知文件
        os.remove(filepath)

    def _handle_reply(self, data):
        """飞书消息回调：立即派发到线程，不阻塞 asyncio 事件循环

        Lark SDK 在 asyncio 事件循环中同步调用此回调，回调返回后才发 ACK。
        如果回调阻塞（文件 I/O、HTTP），会延迟 ACK → 服务端流控 → 下一条消息推送延迟。
        """
        try:
            msg = data.event.message
            if msg.message_type != "text":
                return

            # 过滤发送者：只处理配置的用户消息，忽略其他人
            sender = data.event.sender
            sender_id = sender.sender_id.open_id if sender and sender.sender_id else ""
            if self._allowed_user_id and sender_id != self._allowed_user_id:
                return

            content = json.loads(msg.content) if msg.content else {}
            text = content.get("text", "").strip()
            if not text:
                return

            # 自动捕获 chat_id（用于轮询）
            if not self._chat_id and msg.chat_id:
                self._chat_id = msg.chat_id
                logger.info("自动捕获 chat_id=%s", self._chat_id)

            # 去重：轮询可能已经处理过
            message_id = msg.message_id
            if not self._is_new_message(message_id):
                logger.debug("[WebSocket] 跳过已处理消息: %s", message_id)
                return

            # 轻量提取后立即派发，让 SDK 尽快发 ACK
            parent_id = msg.parent_id
            create_time = int(msg.create_time or 0)
            threading.Thread(
                target=self._process_reply,
                args=(text, parent_id, create_time),
                daemon=True,
            ).start()
        except Exception:
            logger.exception("消息回调预处理异常")

    def _process_reply(self, text: str, parent_id: str, create_time: int):
        """在独立线程中处理飞书消息（不阻塞 asyncio 事件循环）"""
        try:
            now = time.time()
            # 计算端到端延迟（消息创建 → 实际处理）
            if create_time:
                # create_time 为毫秒级时间戳
                create_ts_sec = create_time / 1000 if create_time > 1e12 else float(create_time)
                delay = now - create_ts_sec
                # 丢弃过期消息（daemon 离线期间积压的 WebSocket 队列）
                if delay > self.max_message_age:
                    logger.warning(
                        "丢弃过期消息: text=%s, 延迟=%.0fs (阈值=%ds)",
                        text[:50], delay, self.max_message_age,
                    )
                    return
                logger.info("收到飞书消息: text=%s, parent_id=%s, 延迟=%.1fs", text, parent_id, delay)
            else:
                logger.info("收到飞书消息: text=%s, parent_id=%s", text, parent_id)

            # 先处理回复链消息
            if parent_id and self._handle_parent_reply(text, parent_id):
                return

            cmd = parse_command(text)
            cmd_type = cmd["type"]

            if cmd_type == "ignore":
                return
            elif cmd_type == "list_terminals":
                self._handle_list_terminals(cmd.get("detail", False))
            elif cmd_type == "permission_reply":
                # 安全规则：standalone y/n 必须回复卡片或用 #N 前缀
                self.feishu.send_text_message(
                    "⚠️ 请**回复对应卡片**或指定终端 **#N y** / **#N n**"
                )
            elif cmd_type == "help":
                self.feishu.send_text_message(
                    "📖 **指令速查**\n\n"
                    "**查看**\n"
                    "　**ls**　终端列表　|　**ls -l**　含屏幕预览\n"
                    "　**#N**　终端详情　|　**#N 进度**　屏幕内容\n\n"
                    "**操作**（↩️ 回复卡片 或 #N 指定终端）\n"
                    "　**#N y / n**　权限确认\n"
                    "　**#N 1 / 2 / 3**　选择选项\n"
                    "　**#N 4 文字**　输入型选项\n"
                    "　**#N 文本**　发送指令到终端\n\n"
                    "**控制**\n"
                    "　**#N esc**　发送 Esc　|　**#N ctrl+c**　中断\n"
                    "　**#N clear**　清屏　|　**?**　本帮助"
                )
            elif cmd_type == "terminal_detail":
                self._handle_terminal_detail(cmd["window_id"])
            elif cmd_type == "terminal_screen":
                self._handle_terminal_screen(cmd["window_id"])
            elif cmd_type == "terminal_key":
                self._handle_terminal_key(cmd["window_id"], cmd["key"])
            elif cmd_type == "terminal_clear":
                self._handle_terminal_clear(cmd["window_id"])
            elif cmd_type == "terminal_command":
                self._handle_terminal_command(cmd["window_id"], cmd["text"])
        except Exception:
            logger.exception("处理飞书消息异常")

    # ── 指令处理方法 ──────────────────────────────────

    def _reply_or_send(self, parent_id: str, text: str):
        """有 parent_id 时回复消息，否则发送新消息"""
        if parent_id:
            self.feishu.reply_message(parent_id, text)
        else:
            self.feishu.send_text_message(text)

    def _handle_selection_reply(
        self, text: str, parent_id: str, matched_file: str, matched_pending: dict
    ) -> bool:
        """处理选择弹窗的回复

        来源：
        - 回复卡片（parent_id 非空）
        - #N 前缀（parent_id 为空）

        格式：
        - "1"         → 直接 Enter（已在第 1 项）
        - "3"         → 2×Down + Enter
        - "4 自定义文本" → 3×Down + Enter + 输入文本 + Enter
        - "esc"       → 取消选择
        """
        text = text.strip()

        # 支持 Esc 取消
        if text.lower() in ("esc", "取消", "cancel"):
            socket = matched_pending.get("kitty_socket") or self.kitty_socket
            send_key(matched_pending["window_id"], "escape", socket)
            try:
                os.remove(matched_file)
            except FileNotFoundError:
                pass
            self._reply_or_send(parent_id, "❌ 已取消选择")
            logger.info("取消选择: window=%s", matched_pending.get("window_id"))
            return True

        # 解析 "N" 或 "N 文本"
        import re
        m = re.match(r"^(\d+)\s*(.*)", text)
        if not m:
            option_count = matched_pending.get("option_count", 0)
            hint = f"1-{option_count}" if option_count else "1、2、3..."
            self._reply_or_send(
                parent_id, f"⚠️ 这是选择题，请回复数字（{hint}）或 esc 取消"
            )
            return True

        choice = int(m.group(1))
        extra_text = m.group(2).strip()

        if choice < 1:
            self._reply_or_send(parent_id, "⚠️ 选项编号从 1 开始")
            return True

        option_count = matched_pending.get("option_count", 0)
        if option_count and choice > option_count:
            self._reply_or_send(
                parent_id, f"⚠️ 只有 {option_count} 个选项，请回复 1-{option_count}"
            )
            return True

        text_input_options = set(matched_pending.get("text_input_options", []))
        socket = matched_pending.get("kitty_socket") or self.kitty_socket
        wid = matched_pending["window_id"]

        # 选项 1 已选中（光标默认在第一项），直接 Enter
        # 选项 N → 发送 (N-1) 个 Down 箭头
        for _ in range(choice - 1):
            send_key(wid, "down", socket)
            time.sleep(0.05)

        if choice in text_input_options:
            if extra_text:
                # 一步完成：导航到位 → 直接输入文字 → Enter
                time.sleep(0.1)
                send_keystroke(wid, extra_text, socket)
                time.sleep(0.1)
                send_key(wid, "enter", socket)
            else:
                # 两步交互：先导航到位，转为 text_input 等下一条消息
                time.sleep(0.1)
                matched_pending["reply_mode"] = "text_input"
                matched_pending["notified"] = True
                with open(matched_file, "w", encoding="utf-8") as f:
                    json.dump(matched_pending, f, ensure_ascii=False, indent=2)
                options = matched_pending.get("options", [])
                opt_name = options[choice - 1] if choice <= len(options) else f"选项 {choice}"
                self._reply_or_send(
                    parent_id,
                    f"📝 已选择「{opt_name}」，请直接回复文字内容"
                )
                logger.info("选择文字输入选项: window=%s, choice=%d, 等待输入", wid, choice)
                return True
        else:
            send_key(wid, "enter", socket)

        try:
            os.remove(matched_file)
        except FileNotFoundError:
            pass

        # 获取选项文本
        options = matched_pending.get("options", [])
        if extra_text:
            action = f"✅ 已选择选项 {choice} 并输入: {extra_text}"
        elif choice <= len(options):
            action = f"✅ 已选择: {options[choice - 1]}"
        else:
            action = f"✅ 已选择选项 {choice}"
        self._reply_or_send(parent_id, action)
        logger.info("选择完成: window=%s, choice=%d, extra=%s", wid, choice, extra_text or "(无)")
        return True

    def _handle_permission_reply(self, answer: str, parent_id: str):
        """处理权限 y/n 回复（保持向后兼容）"""
        matched_file, matched_pending = self._find_pending_request(parent_id)
        if not matched_file or not matched_pending:
            logger.warning("未找到匹配的 pending 请求")
            return

        mode = self._detect_pending_mode(matched_pending)
        socket = matched_pending.get("kitty_socket") or self.kitty_socket

        if mode == "text_input":
            wid = matched_pending["window_id"]
            send_keystroke(wid, answer, socket)
            time.sleep(0.15)
            send_keystroke(wid, "\r", socket)
            action = "✅ 已发送文本"
        else:
            is_allow = answer in ("y", "yes", "是")
            keystroke = "\r" if is_allow else "\x1b"
            send_keystroke(matched_pending["window_id"], keystroke, socket)
            action = "✅ 已允许" if is_allow else "❌ 已拒绝"

        try:
            os.remove(matched_file)
        except FileNotFoundError:
            pass

        reply_to = parent_id or matched_pending.get("feishu_msg_id", "")
        if reply_to:
            self.feishu.reply_message(reply_to, action)

        logger.info(
            "pending 回复完成: window=%s, mode=%s, action=%s",
            matched_pending["window_id"], mode, action,
        )

    def _handle_list_terminals(self, detail: bool = False):
        """处理终端列表查询"""
        # 先用注册表现有数据快速响应
        registry = load_registry()
        terminals = sorted(registry.values(), key=lambda t: int(t.get("window_id", 0)))

        if detail:
            # ls -l: 先发"正在抓取"，后台异步抓取每个终端内容
            self.feishu.send_text_message(f"⏳ 正在抓取 {len(terminals)} 个终端内容...")
            threading.Thread(
                target=self._send_terminal_list_detail,
                args=(terminals,),
                daemon=True,
            ).start()
        else:
            self.feishu.send_terminal_list(terminals)
            logger.info("发送终端列表: %d 个终端", len(terminals))

        # 后台刷新注册表
        threading.Thread(target=self._refresh_registry, daemon=True).start()

    def _send_terminal_list_detail(self, terminals: List):
        """后台抓取每个终端内容并发送详细列表"""
        import re
        results = []
        for t in terminals:
            wid = t.get("window_id")
            socket = t.get("kitty_socket") or self._detect_socket()
            if not socket:
                continue
            # 抓取最后 5 行
            screen = get_terminal_screen(wid, socket, 5)
            # 清理控制字符，只保留可见字符
            screen = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", screen)
            lines = [l for l in screen.strip().split("\n") if l.strip()][-5:]
            preview = "\n".join(lines) if lines else "(无内容)"
            results.append({"window_id": wid, "preview": preview})

        # 发送详细列表
        registry = load_registry()
        lines = []
        claude_only = all((t.get("agent_kind") or "claude") == "claude" for t in terminals)
        for t in terminals:
            wid = t.get("window_id")
            icon = "🟢" if t.get("status") == "working" else "🔴" if t.get("status") == "completed" else "⚪"
            title = t.get("tab_title") or t.get("cwd", "").split("/")[-1] or "?"
            agent_name = t.get("agent_name") or "Claude"
            agent_prefix = "" if agent_name == "Claude" else f"[{agent_name}] "
            # 找 preview
            preview = ""
            for r in results:
                if r["window_id"] == wid:
                    preview = r["preview"]
                    break
            lines.append(f"{icon} **#{wid}** {agent_prefix}{title}")
            if preview:
                lines.append(f"```\n{preview}\n```")

        body = "\n".join(lines)
        card = json.dumps({
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": f"📋 {'Claude' if claude_only else 'AI'} 终端列表（{len(terminals)} 个）",
                },
            },
            "elements": [
                {"tag": "markdown", "content": body},
            ],
        }, ensure_ascii=False)
        self.feishu._send_card(card)
        logger.info("发送详细终端列表: %d 个终端", len(terminals))

    def _refresh_registry(self):
        """后台刷新注册表"""
        try:
            scan_all_kitty()
            cleanup_all_kitty()
        except Exception:
            logger.debug("后台刷新注册表异常")

    def _handle_terminal_detail(self, window_id: str):
        """处理终端详情查询（异步）"""
        info = get_terminal_info(window_id)
        if not info:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=(f"❌ 终端 #{window_id} 不存在或已关闭",),
                daemon=True,
            ).start()
            return

        def do_send():
            self.feishu.send_terminal_detail(info)
            logger.info("发送终端详情: window=%s", window_id)
        threading.Thread(target=do_send, daemon=True).start()

    def _handle_terminal_screen(self, window_id: str):
        """处理终端进度/屏幕查看（异步）"""
        info = get_terminal_info(window_id)
        if not info:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=(f"❌ 终端 #{window_id} 不存在或已关闭",),
                daemon=True,
            ).start()
            return

        socket = info.get("kitty_socket") or self._detect_socket()
        if not socket:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=("❌ 无法连接 kitty 终端",),
                daemon=True,
            ).start()
            return

        def do_send():
            screen = get_terminal_screen(window_id, socket, self.max_screen_lines)
            self.feishu.send_terminal_screen(window_id, screen)
            logger.info("发送终端屏幕: window=%s", window_id)
        threading.Thread(target=do_send, daemon=True).start()

    def _handle_terminal_key(self, window_id: str, key: str):
        """处理向终端发送键盘事件"""
        info = get_terminal_info(window_id)
        if not info:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=(f"❌ 终端 #{window_id} 不存在或已关闭",),
                daemon=True,
            ).start()
            return

        socket = info.get("kitty_socket") or self._detect_socket()
        if not socket:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=("❌ 无法连接 kitty 终端",),
                daemon=True,
            ).start()
            return

        send_key(window_id, key, socket)
        logger.info("发送键盘事件: window=%s, key=%s", window_id, key)
        threading.Thread(
            target=self.feishu.send_text_message,
            args=(f"✅ 已发送 {key} 到终端 #{window_id}",),
            daemon=True,
        ).start()

    def _handle_terminal_clear(self, window_id: str):
        """处理清屏指令"""
        info = get_terminal_info(window_id)
        if not info:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=(f"❌ 终端 #{window_id} 不存在或已关闭",),
                daemon=True,
            ).start()
            return

        socket = info.get("kitty_socket") or self._detect_socket()
        if not socket:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=("❌ 无法连接 kitty 终端",),
                daemon=True,
            ).start()
            return

        clear_screen(window_id, socket)
        logger.info("清屏: window=%s", window_id)
        threading.Thread(
            target=self.feishu.send_text_message,
            args=(f"✅ 已清空终端 #{window_id} 屏幕",),
            daemon=True,
        ).start()

    def _handle_terminal_command(self, window_id: str, text: str):
        """处理向终端发送指令

        安全规则：如果该终端有活跃的 pending 请求，优先作为 pending 回复处理，
        而非直接发送到终端（避免干扰权限弹窗/选择弹窗）。
        """
        # ── 优先检查：该终端是否有活跃 pending ──
        pending_file, pending_data = self._find_pending_by_window(window_id)
        if pending_file and pending_data:
            mode = self._detect_pending_mode(pending_data)
            if mode == "selection":
                return self._handle_selection_reply(
                    text, "", pending_file, pending_data
                )
            elif mode == "text_input":
                if text.lower() in TEXT_INPUT_CANCEL_WORDS:
                    try:
                        os.remove(pending_file)
                    except FileNotFoundError:
                        pass
                    self.feishu.send_text_message(f"❌ 已取消终端 #{window_id} 的输入")
                    return
                socket = pending_data.get("kitty_socket") or self.kitty_socket
                send_keystroke(window_id, text, socket)
                time.sleep(0.15)
                send_keystroke(window_id, "\r", socket)
                try:
                    os.remove(pending_file)
                except FileNotFoundError:
                    pass
                self.feishu.send_text_message(f"✅ 已发送文本到终端 #{window_id}")
                logger.info("文本输入（#N）: window=%s, text=%s", window_id, text[:60])
                return
            elif mode == "permission":
                lower = text.lower()
                if lower in ("y", "n", "yes", "no", "是", "否"):
                    is_allow = lower in ("y", "yes", "是")
                    socket = pending_data.get("kitty_socket") or self.kitty_socket
                    keystroke = "\r" if is_allow else "\x1b"
                    send_keystroke(window_id, keystroke, socket)
                    action = "✅ 已允许" if is_allow else "❌ 已拒绝"
                    try:
                        os.remove(pending_file)
                    except FileNotFoundError:
                        pass
                    self.feishu.send_text_message(f"{action} 终端 #{window_id}")
                    logger.info("权限回复（#N）: window=%s, action=%s", window_id, action)
                    return
                else:
                    self.feishu.send_text_message(
                        f"⚠️ 终端 #{window_id} 等待权限确认，请发送 **#{window_id} y** 或 **#{window_id} n**"
                    )
                    return

        # ── 正常终端指令流程 ──
        info = get_terminal_info(window_id)
        if not info:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=(f"❌ 终端 #{window_id} 不存在或已关闭",),
                daemon=True,
            ).start()
            logger.warning("终端不存在: window=%s", window_id)
            return

        if len(text) > self.command_max_length:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=(f"⚠️ 指令过长（最大 {self.command_max_length} 字符）",),
                daemon=True,
            ).start()
            logger.warning("指令过长: window=%s, len=%d", window_id, len(text))
            return

        # 忙碌状态 → 发确认消息（异步），暂存指令
        status = info.get("status", "idle")
        if status in ("working", "waiting"):
            status_cn = STATUS_TEXT.get(status, status)
            warning = "⚠️ 有权限弹窗，发送可能干扰确认" if status == "waiting" else ""
            msg_text = (
                f"⚠️ 终端 #{window_id} 正在{status_cn}\n"
                f"待发指令: {text[:100]}\n"
                f"{warning}\n"
                f"回复 **y** 强制发送 | 回复 **n** 取消"
            )
            # 异步发送，不阻塞回调线程
            def do_send():
                msg_id = self.feishu.send_text_message(msg_text)
                if msg_id:
                    self._pending_commands[msg_id] = {
                        "window_id": window_id,
                        "text": text,
                        "timestamp": time.time(),
                    }
                    logger.info("指令待确认: window=%s, status=%s", window_id, status)
                else:
                    logger.error("发送确认消息失败: window=%s", window_id)
            threading.Thread(target=do_send, daemon=True).start()
            return

        self._send_command_to_terminal(window_id, text, info)

    def _execute_pending_command(self, answer: str, parent_id: str):
        """用户确认后执行暂存的终端指令"""
        pending = self._pending_commands.pop(parent_id, None)
        if not pending:
            logger.warning("待确认指令已过期: msg_id=%s", parent_id)
            return

        is_confirm = answer in ("y", "yes", "是")
        if not is_confirm:
            self.feishu.reply_message(parent_id, "❌ 已取消发送")
            logger.info("用户取消指令: window=%s", pending["window_id"])
            return

        info = get_terminal_info(pending["window_id"])
        if not info:
            self.feishu.reply_message(parent_id, f"❌ 终端 #{pending['window_id']} 已关闭")
            return

        self._send_command_to_terminal(pending["window_id"], pending["text"], info)
        self.feishu.reply_message(parent_id, "✅ 已强制发送")

    def _send_command_to_terminal(self, window_id: str, text: str, info: dict):
        """实际发送指令到终端"""
        socket = info.get("kitty_socket") or self._detect_socket()
        if not socket:
            threading.Thread(
                target=self.feishu.send_text_message,
                args=("❌ 无法连接 kitty 终端",),
                daemon=True,
            ).start()
            logger.error("无可用 socket: window=%s", window_id)
            return

        send_keystroke(window_id, text, socket)
        time.sleep(0.15)
        send_keystroke(window_id, "\r", socket)
        logger.info("发送指令到终端: window=%s, text=%s", window_id, text[:50])
        # 飞书确认异步发送，不阻塞
        threading.Thread(
            target=self.feishu.send_text_message,
            args=(f"✅ 已发送到终端 #{window_id}",),
            daemon=True,
        ).start()

    def _write_pid(self):
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

    def _handle_signal(self, signum, frame):
        logger.info("收到信号 %d，正在停止...", signum)
        self._running = False
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        try:
            os.remove(PID_FILE)
        except FileNotFoundError:
            pass


# ── CLI 入口 ──────────────────────────────────────────

def get_running_pid() -> int | None:
    """获取正在运行的守护进程 PID，不存在返回 None"""
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # 检查进程是否存在
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        os.remove(PID_FILE)
        return None


def cmd_stop():
    pid = get_running_pid()
    if pid is None:
        print("守护进程未运行")
        return
    os.kill(pid, signal.SIGTERM)
    print(f"已发送停止信号 (pid={pid})")


def cmd_status():
    pid = get_running_pid()
    if pid is None:
        print("守护进程未运行")
    else:
        print(f"守护进程运行中 (pid={pid})")

    # 显示注册表
    registry = load_registry()
    if registry:
        from terminal_registry import STATUS_TEXT, format_time_ago
        print(f"\n在线终端: {len(registry)} 个")
        for wid, info in sorted(registry.items(), key=lambda x: int(x[0])):
            status = STATUS_TEXT.get(info.get("status", "idle"), "未知")
            title = info.get("tab_title") or "未知"
            ago = format_time_ago(info.get("last_activity", 0))
            agent_name = info.get("agent_name") or "Claude"
            agent_prefix = "" if agent_name == "Claude" else f"[{agent_name}] "
            print(f"  #{wid}  {agent_prefix}{title}  [{status}]  {ago}")
    else:
        print("\n无在线终端")

    # 显示 pending 文件
    skip = {"daemon.pid", "registry.json"}
    pattern = os.path.join(STATE_DIR, "*.json")
    files = [f for f in glob.glob(pattern) if os.path.basename(f) not in skip]
    if files:
        print(f"\npending 请求: {len(files)} 个")
        for fp in files:
            try:
                with open(fp) as f:
                    p = json.load(f)
                age = time.time() - p.get("timestamp", 0)
                notified = "已通知" if p.get("notified") else "等待中"
                print(f"  - window={p.get('window_id')} age={int(age)}s {notified}")
            except Exception:
                print(f"  - {fp} (读取失败)")
    else:
        print("\n无 pending 请求")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "stop":
            cmd_stop()
            return
        if cmd == "status":
            cmd_status()
            return
        if cmd not in ("start", "run"):
            print(f"用法: python {sys.argv[0]} [start|stop|status]")
            return

    # 检查是否已在运行
    pid = get_running_pid()
    if pid is not None:
        print(f"守护进程已在运行 (pid={pid})，请先 stop")
        sys.exit(1)

    # 查找配置文件（可选，环境变量优先）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.yaml")
    if not os.path.exists(config_path):
        config_path = None

    # 验证配置（环境变量 + config.yaml 合并后检查）
    config = load_config(config_path)
    feishu_cfg = config.get("feishu", {})
    if not feishu_cfg.get("app_id") or not feishu_cfg.get("app_secret"):
        print("❌ 缺少飞书凭据，请设置环境变量或 config.yaml：")
        print("   export FEISHU_APP_ID=cli_xxx")
        print("   export FEISHU_APP_SECRET=xxx")
        sys.exit(1)
    if not feishu_cfg.get("user_id"):
        print("❌ 缺少用户 ID，请选择以下任一方式配置：")
        print("   方式一：设置环境变量")
        print("     export FEISHU_USER_ID=ou_xxx")
        print("   方式二：在 config.yaml 中配置")
        print("     feishu:")
        print("       user_id: \"ou_xxx\"")
        sys.exit(1)

    setup_logging()
    daemon = FeishuBridgeDaemon(config_path)
    daemon.run()


if __name__ == "__main__":
    main()
