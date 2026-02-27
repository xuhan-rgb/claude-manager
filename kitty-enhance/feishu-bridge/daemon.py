"""
飞书权限桥接守护进程

监控 Claude Code 的权限弹窗，超时后通过飞书通知用户，
用户在飞书回复 y/n，守护进程自动发送按键到终端。

启动: python daemon.py
停止: python daemon.py stop
状态: python daemon.py status
"""

import glob
import json
import logging
import os
import signal
import sys
import threading
import time

import yaml

from feishu_client import FeishuClient
from kitty_responder import send_keystroke

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


logger = logging.getLogger("feishu-bridge")


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

    return {
        "feishu": {
            "app_id": feishu_file.get("app_id", "") or os.environ.get("FEISHU_APP_ID", ""),
            "app_secret": feishu_file.get("app_secret", "") or os.environ.get("FEISHU_APP_SECRET", ""),
            "user_id": feishu_file.get("user_id", "") or os.environ.get("FEISHU_USER_ID", ""),
        },
        "bridge": {
            "wait_minutes": float(os.environ.get("FEISHU_WAIT_MINUTES", 0) or bridge_file.get("wait_minutes", 5)),
            "poll_interval": int(os.environ.get("FEISHU_POLL_INTERVAL", 0) or bridge_file.get("poll_interval", 2)),
            "expire_minutes": int(os.environ.get("FEISHU_EXPIRE_MINUTES", 0) or bridge_file.get("expire_minutes", 30)),
        },
        "kitty": {
            "socket": kitty_file.get("socket", ""),
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
        self._running = True

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

    def _monitor_loop(self):
        """主循环：扫描 pending 文件，超时发飞书通知"""
        while self._running:
            now = time.time()
            pattern = os.path.join(STATE_DIR, "*.json")
            for filepath in glob.glob(pattern):
                # 跳过非 pending 文件
                basename = os.path.basename(filepath)
                if basename in ("daemon.pid",):
                    continue
                try:
                    self._process_pending(filepath, now)
                except Exception:
                    logger.exception("处理 pending 文件异常: %s", filepath)
            time.sleep(self.poll_interval)

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
            logger.info(
                "超过等待时间 (%d 秒)，发送飞书通知: window=%s",
                int(age), pending.get("window_id"),
            )
            msg_id = self.feishu.send_permission_message(pending)
            if msg_id:
                pending["feishu_msg_id"] = msg_id
                pending["notified"] = True
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(pending, f, ensure_ascii=False, indent=2)

    def _handle_reply(self, data):
        """飞书消息回调：用户回复 y/n 时触发"""
        try:
            msg = data.event.message
            sender_open_id = data.event.sender.sender_id.open_id
            parent_id = msg.parent_id
            message_type = msg.message_type

            # 只处理文本消息
            if message_type != "text":
                return

            content = json.loads(msg.content) if msg.content else {}
            text = content.get("text", "").strip().lower()

            # 只识别明确的 y/n 回复
            if text not in ("y", "n", "yes", "no", "是", "否"):
                return

            logger.info(
                "收到飞书回复: from=%s, text=%s, parent_id=%s",
                sender_open_id, text, parent_id,
            )

            # 查找匹配的 pending 文件
            # 优先匹配 parent_id（回复消息），否则匹配最近一条已通知的 pending
            pattern = os.path.join(STATE_DIR, "*.json")
            matched_file = None
            matched_pending = None
            latest_ts = 0

            for filepath in glob.glob(pattern):
                basename = os.path.basename(filepath)
                if not basename.endswith(".json") or basename == "daemon.pid":
                    continue
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        pending = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    continue

                # 精确匹配：回复了特定卡片消息
                if parent_id and pending.get("feishu_msg_id") == parent_id:
                    matched_file = filepath
                    matched_pending = pending
                    break

                # 模糊匹配：直接发 y/n，取最近一条已通知的 pending
                if not parent_id and pending.get("notified"):
                    ts = pending.get("timestamp", 0)
                    if ts > latest_ts:
                        latest_ts = ts
                        matched_file = filepath
                        matched_pending = pending

            if not matched_file:
                logger.warning("未找到匹配的 pending 请求")
                return

            # 匹配成功，发送按键（优先用 pending 里记录的 socket）
            # 权限弹窗是选择菜单：Enter=确认高亮项(Yes)，Escape=取消(No)
            is_allow = text in ("y", "yes", "是")
            answer = "\r" if is_allow else "\x1b"
            socket = matched_pending.get("kitty_socket") or self.kitty_socket
            send_keystroke(
                matched_pending["window_id"], answer, socket
            )

            # 清理 pending 文件
            try:
                os.remove(matched_file)
            except FileNotFoundError:
                pass

            # 回复飞书确认
            action = "✅ 已允许" if is_allow else "❌ 已拒绝"
            reply_to = parent_id or matched_pending.get("feishu_msg_id", "")
            if reply_to:
                self.feishu.reply_message(reply_to, action)

            logger.info(
                "权限回复完成: window=%s, action=%s",
                matched_pending["window_id"], action,
            )
        except Exception:
            logger.exception("处理飞书回复异常")

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
    # 显示 pending 文件
    pattern = os.path.join(STATE_DIR, "*.json")
    files = [
        f for f in glob.glob(pattern)
        if os.path.basename(f) != "daemon.pid"
    ]
    if files:
        print(f"当前 pending 请求: {len(files)} 个")
        for fp in files:
            try:
                with open(fp) as f:
                    p = json.load(f)
                age = time.time() - p.get("timestamp", 0)
                notified = "已通知" if p.get("notified") else "等待中"
                print(
                    f"  - window={p.get('window_id')} "
                    f"age={int(age)}s {notified}"
                )
            except Exception:
                print(f"  - {fp} (读取失败)")
    else:
        print("当前无 pending 请求")


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
