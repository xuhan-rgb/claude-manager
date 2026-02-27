# 飞书终端管理中心（Feishu Terminal Hub）

## 背景

当前飞书桥接（feishu-bridge）仅支持权限弹窗通知和 y/n 回复。随着同时运行多个 Claude 终端的场景增多，需要一个更完整的终端管理能力：实时掌握所有终端状态、查看任务进度、向特定终端下达指令。

## 目标

在现有 feishu-bridge 基础上扩展，实现：

1. **终端注册与列表** — 所有 Claude 终端自动注册到 daemon，飞书可查看终端列表
2. **实时进度推送** — 关键进度（任务开始、工具调用、任务完成）自动推送到飞书
3. **终端寻址与交互** — 飞书可 @特定终端查看进度、发送指令

## 核心概念

### 终端身份

每个 Claude 终端用 `window_id` 唯一标识，附带以下元信息：

```json
{
  "window_id": "7",
  "kitty_socket": "unix:@mykitty-3823109",
  "tab_title": "claude-manager",      // 项目名/任务名
  "cwd": "/mnt/data/claude-manager",  // 工作目录
  "registered_at": 1740000000.0,
  "last_activity": 1740000060.0,
  "status": "working"                 // idle | working | waiting | completed
}
```

### 终端状态

| 状态 | 含义 | 触发条件 |
|------|------|----------|
| `idle` | 空闲，等待用户输入 | 新注册 / 任务完成后 |
| `working` | Claude 正在工作 | PreToolUse hook 触发 |
| `waiting` | 等待用户确认（权限弹窗） | Notification hook 触发 |
| `completed` | 任务完成 | Stop hook 触发 |

## 架构设计

### 文件布局

```
kitty-enhance/feishu-bridge/
├── daemon.py              # 守护进程（扩展）
├── feishu_client.py       # 飞书 API（扩展）
├── kitty_responder.py     # kitty 交互（现有）
├── terminal_registry.py   # 【新增】终端注册表
├── command_handler.py     # 【新增】飞书指令解析与分发
├── config.yaml
├── config_example.yaml
├── setup.sh
└── requirements.txt

kitty-enhance/hooks/
├── on-tool-use.sh         # 修改：追加终端心跳上报
├── on-notify.sh           # 不变
├── on-permission-pending.sh  # 不变（权限通知保留）
├── on-stop.sh             # 修改：追加终端状态上报
└── tab-color-common.sh    # 不变
```

### 数据流

```
                          ┌──────────────────────────┐
                          │     /tmp/feishu-bridge/   │
                          │                          │
  Hook 事件               │  registry.json           │  ← 终端注册表
  ──────────→             │  {wid}.json              │  ← 权限 pending（现有）
  on-tool-use.sh ────→    │  heartbeat-{wid}.json    │  ← 心跳/状态更新
  on-stop.sh ────→        │                          │
                          └──────────┬───────────────┘
                                     │
                          ┌──────────▼───────────────┐
                          │       daemon.py           │
                          │                          │
                          │  _monitor_loop()          │  扫描 pending（现有）
                          │  _registry_loop()         │  扫描注册表/心跳（新增）
                          │  _handle_reply()          │  飞书消息回调（扩展）
                          └──────────┬───────────────┘
                                     │
                          ┌──────────▼───────────────┐
                          │     飞书 WebSocket         │
                          │                          │
                          │  ← 接收用户消息           │
                          │  → 发送卡片/文本          │
                          └──────────────────────────┘
```

## 功能详细设计

### 一、终端自动注册

#### 触发时机

每个 Claude 终端首次触发任意 hook 时，自动注册到 `/tmp/feishu-bridge/registry.json`。

#### Hook 修改（on-tool-use.sh / on-stop.sh）

在现有逻辑末尾追加注册逻辑（轻量，不影响现有功能）：

```bash
# ── 终端注册（追加到 hook 末尾）──
REGISTRY="/tmp/feishu-bridge/registry.json"
# 用 flock 保证并发安全
(
  flock -n 200 || exit 0
  python3 -c "
import json, time, os, fcntl
reg_path = '$REGISTRY'
wid = os.environ.get('KITTY_WINDOW_ID', '')
if not wid: exit()
try:
    with open(reg_path, 'r') as f: reg = json.load(f)
except: reg = {}
reg[wid] = {
    'window_id': wid,
    'kitty_socket': os.environ.get('KITTY_LISTEN_ON', ''),
    'tab_title': '${TAB_TITLE:-}',
    'cwd': os.environ.get('PWD', ''),
    'registered_at': reg.get(wid, {}).get('registered_at', time.time()),
    'last_activity': time.time(),
    'status': '$STATUS'  # working / completed / waiting
}
with open(reg_path, 'w') as f: json.dump(reg, f, ensure_ascii=False, indent=2)
"
) 200>/tmp/feishu-bridge/.registry.lock
```

其中 `$STATUS` 根据 hook 类型确定：
- `on-tool-use.sh` → `working`
- `on-stop.sh` → `completed`
- `on-permission-pending.sh` → `waiting`

#### registry.json 格式

```json
{
  "7": {
    "window_id": "7",
    "kitty_socket": "unix:@mykitty-3823109",
    "tab_title": "claude-manager",
    "cwd": "/mnt/data/claude-manager",
    "registered_at": 1740000000.0,
    "last_activity": 1740000060.0,
    "status": "working"
  },
  "2": {
    "window_id": "2",
    "kitty_socket": "unix:@mykitty-3823109",
    "tab_title": "uwb-driver",
    "cwd": "/mnt/data/jszr_driver/uwb_driver",
    "registered_at": 1740000010.0,
    "last_activity": 1740000055.0,
    "status": "completed"
  }
}
```

### 二、飞书查看终端列表

#### 指令格式

用户在飞书发送：

| 指令 | 功能 |
|------|------|
| `ls` 或 `列表` | 查看所有在线终端 |
| `#7` 或 `@7` | 查看 7 号终端详情 |
| `#7 进度` | 查看 7 号终端的屏幕内容（最新进度） |
| `#7 <任意文本>` | 向 7 号终端发送文本指令 |
| `y` / `n` | 权限回复（现有功能，保持不变） |

#### 终端列表卡片

daemon 收到 `ls` 指令后，读取 registry.json + kitty @ ls（验证窗口是否存活），发送卡片：

```
📋 Claude 终端列表（共 3 个）

🟢 #7  claude-manager     工作中   2 分钟前活跃
🔴 #2  uwb-driver        已完成   5 分钟前
🟡 #1  jszr-perception   等待确认  刚刚

───────────────────────
回复 #编号 查看详情，如 "#7 进度"
```

状态图标映射：
- 🟢 `working` — 工作中
- 🔴 `completed` — 已完成
- 🟡 `waiting` — 等待确认
- ⚪ `idle` — 空闲

#### 终端详情

用户发 `#7` 或 `@7`，返回：

```
📺 终端 #7 详情

📁 项目: claude-manager
📂 路径: /mnt/data/claude-manager
🟢 状态: 工作中
⏱️ 活跃: 2 分钟前
📅 注册: 10 分钟前

回复 "#7 进度" 查看终端屏幕
回复 "#7 <指令>" 发送文本到终端
```

### 三、查看终端进度

用户发 `#7 进度`，daemon 调用 `kitty @ get-text` 抓取屏幕内容，发送：

```
📺 终端 #7 屏幕内容

```
⏺  Implementing feature X...
   Created src/feature.py
   Running tests...

✓  All 15 tests passed

⏺  Now updating documentation...
   Reading README.md...
```

───────────────────────
最后 20 行 | 抓取于 19:30:45
```

#### 实现

```python
def get_terminal_screen(self, window_id: str, socket: str, lines: int = 20) -> str:
    """抓取终端屏幕内容"""
    cmd = [
        "kitty", "@", "--to", socket,
        "get-text", "--match", f"id:{window_id}", "--extent=screen"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        return ""
    # 取最后 N 行非空行
    all_lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
    return '\n'.join(all_lines[-lines:])
```

### 四、向终端发送指令

用户发 `#7 帮我看看测试结果`，daemon 将文本发送到终端：

#### 安全考虑

- 不直接发送到 Claude 的 stdin（避免注入问题）
- 而是在终端中**模拟用户输入**，让 Claude 看到后自行处理
- 限制：仅在终端状态为 `idle` 或 `completed` 时允许发送（避免干扰正在工作的 Claude）

#### 实现流程

```
用户飞书: "#7 帮我看看测试结果"
    ↓
daemon 解析: window_id=7, text="帮我看看测试结果"
    ↓
检查状态: registry[7].status
    ↓
如果 working/waiting → 回复 "⚠️ 终端 #7 正在工作中，请等待完成后再发指令"
如果 idle/completed → send_keystroke(7, "帮我看看测试结果\n", socket)
    ↓
回复飞书: "✅ 已发送到终端 #7"
```

### 五、关键进度自动推送（可选，后续迭代）

> 此功能为可选增强，第一期可不实现。

在 Stop hook 触发时，自动向飞书推送任务完成通知：

```
✅ 终端 #7 任务完成

📁 项目: claude-manager
⏱️ 用时: 15 分钟

最后输出:
```
✓ All tests passed
✓ Files updated: 3
```
```

## 实现计划

### 第一期：终端注册 + 列表查看 + 进度查看

1. **新增 terminal_registry.py** — 终端注册表读写
2. **新增 command_handler.py** — 飞书指令解析（ls / #N / #N 进度）
3. **修改 daemon.py** — 扩展 `_handle_reply` 支持新指令，清理过期注册
4. **修改 feishu_client.py** — 新增列表卡片、详情卡片、屏幕内容消息
5. **修改 on-tool-use.sh** — 追加终端注册（status=working）
6. **修改 on-stop.sh** — 追加终端状态更新（status=completed）
7. **修改 on-permission-pending.sh** — 追加终端状态更新（status=waiting）

### 第二期：指令发送

8. **扩展 command_handler.py** — 解析 `#N <文本>` 指令
9. **扩展 kitty_responder.py** — 支持发送任意文本
10. **安全限制** — 状态检查、长度限制

### 第三期：自动进度推送（可选）

11. **修改 on-stop.sh** — 完成时自动推送飞书通知
12. **新增推送配置** — 哪些事件推送、推送频率控制

## 指令解析规则（command_handler.py）

```python
def parse_command(text: str) -> dict:
    """解析飞书消息为结构化指令

    返回:
        {"type": "permission_reply", "answer": "y"}          # 权限回复
        {"type": "list_terminals"}                            # 终端列表
        {"type": "terminal_detail", "window_id": "7"}        # 终端详情
        {"type": "terminal_screen", "window_id": "7"}        # 查看进度
        {"type": "terminal_command", "window_id": "7", "text": "..."} # 发指令
        {"type": "unknown"}                                   # 无法识别
    """
    text = text.strip()

    # 权限回复（优先级最高，兼容现有功能）
    if text.lower() in ("y", "n", "yes", "no", "是", "否"):
        return {"type": "permission_reply", "answer": text}

    # 终端列表
    if text.lower() in ("ls", "列表", "list", "终端"):
        return {"type": "list_terminals"}

    # #N 或 @N 开头的指令
    match = re.match(r'[#@](\d+)\s*(.*)', text)
    if match:
        wid = match.group(1)
        rest = match.group(2).strip()
        if not rest:
            return {"type": "terminal_detail", "window_id": wid}
        if rest in ("进度", "屏幕", "screen", "progress"):
            return {"type": "terminal_screen", "window_id": wid}
        return {"type": "terminal_command", "window_id": wid, "text": rest}

    return {"type": "unknown"}
```

## 注册表清理

daemon 在 `_monitor_loop` 中定期清理不存在的终端：

```python
def _cleanup_registry(self):
    """清理已关闭的终端"""
    # 通过 kitty @ ls 获取当前所有窗口 ID
    active_windows = get_active_window_ids(socket)

    # 移除 registry 中不存在的窗口
    for wid in list(registry.keys()):
        if wid not in active_windows:
            del registry[wid]
```

清理频率：每 30 秒一次（不需要太频繁）。

## 配置扩展

```yaml
# config.yaml 新增
hub:
  auto_push_on_complete: false   # 任务完成时自动推送飞书（第三期）
  registry_cleanup_interval: 30  # 注册表清理间隔（秒）
  max_screen_lines: 20           # 进度查看最大行数
  command_max_length: 500        # 指令最大长度
```

## 关键约束

1. **向后兼容** — 现有权限 y/n 回复功能完全保留，新指令不影响旧流程
2. **轻量 Hook** — 注册逻辑追加到现有 hook 末尾，使用 flock 避免竞争，失败静默
3. **单进程** — 仍然只有一个 daemon 进程，通过指令类型分发处理
4. **registry.json 单文件** — 避免文件碎片化，用 flock 保证并发安全

## 参考文件

| 文件 | 说明 |
|------|------|
| `kitty-enhance/feishu-bridge/daemon.py` | 守护进程主体，扩展消息处理 |
| `kitty-enhance/feishu-bridge/feishu_client.py` | 飞书 API，新增卡片类型 |
| `kitty-enhance/feishu-bridge/kitty_responder.py` | kitty 交互，新增 get-text |
| `kitty-enhance/hooks/on-tool-use.sh` | 追加注册逻辑 |
| `kitty-enhance/hooks/on-stop.sh` | 追加状态更新 |
| `kitty-enhance/hooks/on-permission-pending.sh` | 追加状态更新 |
| `kitty-enhance/hooks/tab-color-common.sh` | 公共库（不修改） |
| `~/.claude/settings.json` | Hook 注册（不修改） |
