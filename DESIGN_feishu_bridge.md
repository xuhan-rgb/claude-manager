# 飞书权限桥接 (Feishu Permission Bridge)

> 状态：✅ 已完成（代码实现）

## 痛点

Claude Code 等待 yes/no 权限确认时，如果用户不在终端前，任务会卡住直到超时中断。需要：等待超 5 分钟 → 飞书通知 → 用户回复 y/n → 自动输入终端。

## 架构

```
Claude Code 等待权限 → Notification Hook 触发
                            ↓
              写入 pending 文件到 /tmp/feishu-bridge/
                            ↓
              守护进程监控 pending 文件
                            ↓ (5 分钟后仍未处理)
              调用飞书 API 发卡片消息给用户
                            ↓
              用户在飞书回复 y / n
                            ↓
              守护进程通过 WebSocket 收到回复
                            ↓
              kitty @ send-text 发送按键到对应终端窗口
                            ↓
              Claude Code 权限弹窗被回答，任务继续
```

## 组件清单

| # | 组件             | 文件                                | 职责                                          |
|---|------------------|-------------------------------------|-----------------------------------------------|
| 1 | Notification Hook | `hooks/on-permission-pending.sh`   | 权限弹窗出现时写 pending 文件                 |
| 2 | Stop Hook 补丁   | `hooks/on-stop.sh`（修改）          | Claude 停止时清理 pending 文件                |
| 3 | 守护进程         | `feishu-bridge/daemon.py`           | 监控 pending、发飞书、收回复、发按键          |
| 4 | 飞书客户端       | `feishu-bridge/feishu_client.py`    | 飞书 API 封装（发消息 + WebSocket 收消息）    |
| 5 | 按键发送         | `feishu-bridge/kitty_responder.py`  | `kitty @ send-text` 封装                     |
| 6 | 配置             | `feishu-bridge/config.yaml`         | 飞书凭据、超时时间等                          |
| 7 | settings.json    | `~/.claude/settings.json`           | 注册新 Hook                                  |

## 文件结构

```
/mnt/data/claude-manager/kitty-enhance/
├── hooks/
│   ├── on-notify.sh                  （现有，不修改）
│   ├── on-stop.sh                    （现有，添加 1 行清理逻辑）
│   ├── on-tool-use.sh                （现有，不修改）
│   ├── tab-color-common.sh           （现有，不修改）
│   └── on-permission-pending.sh      （新增）
├── feishu-bridge/
│   ├── daemon.py                     （新增，守护进程）
│   ├── feishu_client.py              （新增，飞书 API）
│   ├── kitty_responder.py            （新增，按键发送）
│   ├── config.yaml                   （新增，配置）
│   ├── config_example.yaml           （新增，配置模板）
│   └── requirements.txt              （新增，lark-oapi pyyaml）
└── ...

/tmp/feishu-bridge/                    （运行时，自动创建）
├── {window_id}.json                   （pending 权限请求）
├── daemon.pid
└── daemon.log

/home/qwer/.claude/hooks/
└── on-permission-pending.sh           → symlink
```

## 详细实现

### Step 1: `on-permission-pending.sh`（Notification Hook）

权限弹窗出现时，读取 stdin JSON + `$KITTY_WINDOW_ID`，写入 pending 文件。

```bash
#!/bin/bash
# Notification Hook - 记录 pending 权限请求
# async 执行，不阻塞 Claude Code

WINDOW_ID="${KITTY_WINDOW_ID:-}"
[ -z "$WINDOW_ID" ] && exit 0

STATE_DIR="/tmp/feishu-bridge"
mkdir -p "$STATE_DIR"

# 读取 stdin JSON
INPUT=$(cat)

# 用 python3 提取信息并写入 pending 文件
python3 -c "
import json, time, sys, os
try:
    data = json.loads('''$INPUT''') if '''$INPUT''' else {}
except:
    data = {}

pending = {
    'window_id': '$WINDOW_ID',
    'message': data.get('message', ''),
    'title': data.get('title', ''),
    'timestamp': time.time(),
    'notified': False,
    'feishu_msg_id': None
}

path = os.path.join('$STATE_DIR', '${WINDOW_ID}.json')
with open(path, 'w') as f:
    json.dump(pending, f, ensure_ascii=False, indent=2)
"

exit 0
```

**关键**：用 `KITTY_WINDOW_ID` 作文件名，因为 `kitty @ send-text` 按 window_id 定位窗口。

**参考文件**：
- `on-notify.sh`：同样是 Notification Hook，读取 `KITTY_WINDOW_ID`
- `on-tool-use.sh`：async 后台执行模式 `() & disown`

### Step 2: 修改 `on-stop.sh`

在 `exit 0` 前添加一行，Claude 停止时清理 pending 文件：

```bash
# 清理 feishu-bridge pending 文件
rm -f "/tmp/feishu-bridge/${WINDOW_ID}.json" 2>/dev/null
```

### Step 3: `feishu_client.py`（飞书 API 封装）

使用 `lark-oapi` 官方 Python SDK：

```python
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

class FeishuClient:
    def __init__(self, app_id, app_secret, user_id):
        self.client = lark.Client.builder() \
            .app_id(app_id).app_secret(app_secret).build()
        self.user_id = user_id

    def send_permission_message(self, pending: dict) -> str:
        """发送卡片消息，返回 message_id"""
        # 卡片内容：工具名、命令、目录、等待时长
        # receive_id_type="open_id", receive_id=self.user_id
        ...

    def reply_message(self, msg_id: str, text: str):
        """回复确认消息"""
        ...

    def start_ws_listener(self, on_reply_callback):
        """启动 WebSocket 长连接（无需公网 IP）"""
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(on_reply_callback) \
            .build()
        ws_client = lark.ws.Client(
            self.app_id, self.app_secret,
            event_handler=event_handler
        )
        ws_client.start()  # 阻塞，需在单独线程运行
```

飞书卡片消息格式：
```
🟡 Claude Code 等待权限确认

工具: Bash
内容: rm -rf node_modules
目录: /mnt/data/autolabel
等待: 5 分 12 秒

回复 y 允许 | 回复 n 拒绝
```

### Step 4: `kitty_responder.py`（按键发送）

```python
import subprocess, os

def send_keystroke(window_id: str, text: str):
    """向指定 kitty 窗口发送按键"""
    socket = os.environ.get("KITTY_LISTEN_ON", "unix:@mykitty")
    subprocess.run([
        "kitty", "@", "--to", socket,
        "send-text", "--match", f"id:{window_id}", text
    ], check=False)
```

**参考**：`tab-color-common.sh` 中 `kitty @ --to "$socket"` 的用法和 socket 路径。

### Step 5: `daemon.py`（守护进程）

```python
"""
飞书权限桥接守护进程

启动: python daemon.py
停止: python daemon.py stop
"""

class FeishuBridgeDaemon:
    def __init__(self, config_path):
        self.config = load_config(config_path)
        self.feishu = FeishuClient(...)
        self.wait_seconds = self.config['bridge']['wait_minutes'] * 60

    def run(self):
        # 1. 启动飞书 WebSocket 监听线程
        threading.Thread(target=self.feishu.start_ws_listener,
                         args=(self.handle_reply,), daemon=True).start()
        # 2. 主循环：监控 pending 文件
        self.monitor_loop()

    def monitor_loop(self):
        while True:
            now = time.time()
            for f in glob.glob("/tmp/feishu-bridge/*.json"):
                pending = json.load(open(f))
                age = now - pending["timestamp"]

                # 超过等待时间且未通知 → 发飞书
                if age >= self.wait_seconds and not pending.get("notified"):
                    msg_id = self.feishu.send_permission_message(pending)
                    pending["feishu_msg_id"] = msg_id
                    pending["notified"] = True
                    json.dump(pending, open(f, "w"), ensure_ascii=False)

                # 超过 30 分钟 → 清理过期
                if age >= self.config['bridge']['expire_minutes'] * 60:
                    os.remove(f)

            time.sleep(self.config['bridge']['poll_interval'])

    def handle_reply(self, event_data):
        """飞书消息回调"""
        text = extract_text(event_data)           # "y" / "n" / "yes" / "no"
        parent_id = get_parent_msg_id(event_data)  # 被回复的消息 ID

        # 遍历 pending 文件，匹配 feishu_msg_id
        for f in glob.glob("/tmp/feishu-bridge/*.json"):
            pending = json.load(open(f))
            if pending.get("feishu_msg_id") == parent_id:
                answer = "y\n" if text.lower() in ("y", "yes", "是") else "n\n"
                send_keystroke(pending["window_id"], answer)
                os.remove(f)
                self.feishu.reply_message(parent_id, f"已{'允许' if 'y' in answer else '拒绝'}")
                break
```

### Step 6: `config.yaml`

```yaml
feishu:
  app_id: ""          # 飞书自建应用 App ID
  app_secret: ""      # 飞书自建应用 App Secret
  user_id: ""         # 接收消息的用户 open_id

bridge:
  wait_minutes: 5     # 等待多久后发飞书通知
  poll_interval: 5    # 扫描 pending 文件间隔（秒）
  expire_minutes: 30  # pending 文件过期清理时间

kitty:
  socket: "unix:@mykitty"  # kitty remote control socket
```

### Step 7: `settings.json` Hook 注册

在现有 `Notification` 数组中新增 hook：

```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          { "type": "command", "command": "/home/qwer/.claude/hooks/on-notify.sh" },
          { "type": "command", "command": "/home/qwer/.claude/hooks/on-permission-pending.sh" }
        ]
      }
    ]
  }
}
```

## 实现顺序

1. 创建 `feishu-bridge/` 目录 + `config.yaml` + `requirements.txt`
2. 实现 `feishu_client.py`（飞书 API）
3. 实现 `kitty_responder.py`（按键发送）
4. 实现 `daemon.py`（守护进程）
5. 实现 `on-permission-pending.sh`（Hook）
6. 修改 `on-stop.sh`（清理逻辑）
7. 创建 symlink + 更新 `settings.json`
8. 端到端测试

## 前置条件

1. 在 [飞书开放平台](https://open.feishu.cn) 创建自建应用，启用"机器人"能力
2. 添加权限：`im:message`、`im:message:send_as_bot`
3. 开启事件订阅（WebSocket 模式）：`im.message.receive_v1`
4. 获取 App ID、App Secret、用户 open_id
5. `pip install lark-oapi pyyaml`

## 验证方式

1. 启动守护进程：`python daemon.py`
2. 临时从 `settings.json` 的 allow 列表移除某工具（如 `Write`）
3. 在 Claude Code 中触发该工具 → 权限弹窗出现
4. 等待 5 分钟（或临时改 config 为 30 秒）
5. 确认飞书收到卡片消息
6. 在飞书回复 y → 确认终端自动输入并继续

## 关键参考文件

| 文件                                       | 复用内容                           |
|--------------------------------------------|------------------------------------|
| `hooks/on-notify.sh`                       | Notification Hook 模式、环境变量   |
| `hooks/on-tool-use.sh`                     | async 后台执行 `() & disown`       |
| `hooks/tab-color-common.sh`                | kitty socket 管理、window_id 获取  |
| `hooks/on-stop.sh`                         | Stop Hook 模式                    |
