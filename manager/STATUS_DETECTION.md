# 状态检测机制说明

## 核心原理：Kitty `at_prompt` 标志

基于用户提示，我们使用 **Kitty 的 `at_prompt` 标志**作为主要检测机制。这是 Kitty 内置的功能，当程序在提示符处等待输入时，该标志为 `true`。

### 为什么 `at_prompt` 最可靠？

1. **Kitty 原生支持**：不依赖内容分析，直接使用 Kitty 的检测
2. **实时更新**：Kitty 实时跟踪终端状态
3. **准确判断**：精确区分"工作中"和"等待输入"

## 状态转换逻辑

```
○ pending (白色)
   ↓ 检测到用户输入活动
● running (蓝色)
   ↓ at_prompt=true + 有工作内容 + 非欢迎界面
● completed (红色)
```

### 详细规则

| 当前状态 | 检测条件 | 新状态 |
|---------|---------|--------|
| **pending** | 有活动 + 内容 > 20 行 | **running** |
| **running** | `at_prompt=true` + 内容 > 25 行 + 非欢迎界面 | **completed** |
| **running** | `at_prompt=false` | 保持 **running** |
| **completed** | - | 保持 **completed** |

## 调试方法

### 1. 实时查看日志

```bash
# 方法 A: 使用脚本（带颜色高亮）
cd /mnt/data/claude-manager
./watch_logs.sh

# 方法 B: 直接使用 tail
tail -f ~/.config/claude-manager/logs/app.log | grep "\[状态"
```

日志示例：
```
2026-02-03 20:55:10 [INFO] [状态检测] 任务 task1, 当前状态: pending
2026-02-03 20:55:10 [INFO] [Kitty标志] at_prompt=False (window_id=148)
2026-02-03 20:55:10 [INFO] [活动监控] has_activity=False, is_silent=False
2026-02-03 20:55:10 [INFO] [内容分析] line_count=18, is_welcome=True, has_prompt=True, has_meandering=False
2026-02-03 20:55:10 [DEBUG] [状态保持] task1: 保持 pending (等待用户输入)
```

### 2. 测试 Kitty at_prompt 标志

```bash
# 查看所有窗口的 at_prompt 状态
kitten @ ls | python3 -c "
import json, sys
data = json.load(sys.stdin)
for os_win in data:
    for tab in os_win['tabs']:
        for win in tab['windows']:
            at_prompt = win.get('at_prompt', False)
            print(f\"Window {win['id']:3d}: at_prompt={at_prompt:5} | {win['title'][:50]}\")
"
```

### 3. 手动测试状态转换

```python
# 在 Python 中测试
from src.claude_manager.kitty_control import KittyController

kitty = KittyController()
window_id = 148  # 你的 Claude 窗口 ID

# 检查 at_prompt 状态
at_prompt = kitty.get_window_at_prompt(window_id)
print(f"Window {window_id} at_prompt: {at_prompt}")
```

## 日志说明

### 日志级别

- **INFO**: 关键状态转换和检测结果
- **DEBUG**: 详细的检测过程
- **WARNING**: 异常情况

### 关键日志标记

| 标记 | 含义 | 颜色（watch_logs.sh） |
|------|------|---------------------|
| `[状态摘要]` | 所有任务状态概览（每15秒） | 蓝色 |
| `[状态检测]` | 开始检测任务状态 | 青色 |
| `[Kitty标志]` | Kitty at_prompt 结果 | 黄色 |
| `[活动监控]` | tmux 活动监控结果 | 黄色 |
| `[内容分析]` | pane 内容分析结果 | 紫色 |
| `[状态转换]` | 状态发生变化 | 绿色（重要！） |
| `[状态保持]` | 状态未变化 | 默认 |

## 测试流程

### 完整测试步骤

1. **启动并查看日志**

```bash
# 终端 1: 启动 claude-manager
cd /mnt/data/claude-manager
pip install -e .
claude-manager

# 终端 2: 实时查看日志
./watch_logs.sh
```

2. **创建任务并观察**

```
在 claude-manager 中:
- 按 'n' 创建新任务
- 观察日志: 应该显示 pending 状态
```

3. **输入问题并观察**

```
在右侧 Claude 中:
- 输入一个问题
- 等待 5 秒或按 'r' 刷新
- 观察日志: 应该看到 pending → running 转换
```

4. **等待完成并观察**

```
Claude 回答完成后:
- at_prompt 应该变为 true
- 等待 5 秒或按 'r' 刷新
- 观察日志: 应该看到 running → completed 转换
```

### 预期日志输出

**创建任务时**:
```
[状态检测] 任务 abc123, 当前状态: pending
[Kitty标志] at_prompt=True (window_id=148)
[内容分析] line_count=18, is_welcome=True, has_prompt=True
[状态保持] abc123: 保持 pending (等待用户输入)
```

**开始工作时**:
```
[状态检测] 任务 abc123, 当前状态: pending
[Kitty标志] at_prompt=False (window_id=148)
[活动监控] has_activity=True, is_silent=False
[内容分析] line_count=35, is_welcome=False, has_prompt=False, has_meandering=True
[状态转换] abc123: pending → running (检测到活动, lines=35)
```

**完成工作时**:
```
[状态检测] 任务 abc123, 当前状态: running
[Kitty标志] at_prompt=True (window_id=148)
[内容分析] line_count=120, is_welcome=False, has_prompt=True, has_meandering=False
[状态转换] abc123: running → completed (at_prompt=True, lines=120, welcome=False)
```

## 故障排查

### 问题 1: 状态一直不变

**检查**:
```bash
# 查看日志
tail -20 ~/.config/claude-manager/logs/app.log

# 检查 Kitty 窗口 ID
kitten @ ls | grep -A 5 "Claude"
```

**可能原因**:
- `tmux_window_id` 不正确
- Kitty at_prompt 检测失败
- 内容长度不满足阈值

### 问题 2: pending → running 太慢

**解决**: 减少检测间隔（`app.py:170`）

```python
# 当前: 5 秒
self.set_interval(5, self.check_task_status_async)

# 改为: 2 秒
self.set_interval(2, self.check_task_status_async)
```

### 问题 3: running → completed 太慢

**解决**: 调整内容阈值（`app.py:258`）

```python
# 当前: 25 行
if kitty_at_prompt and line_count > 25 and not is_welcome_screen:

# 改为: 20 行
if kitty_at_prompt and line_count > 20 and not is_welcome_screen:
```

## 高级：监听系统通知（可选）

如果你想监听 Claude Code 发送的系统通知：

```bash
# 实时监听所有通知
dbus-monitor "interface='org.freedesktop.Notifications'" | grep --line-buffered -A 10 "string \"Claude"

# 或使用 Python 脚本
python3 << 'EOF'
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)

def notification_handler(*args):
    app_name = args[0] if len(args) > 0 else ""
    summary = args[3] if len(args) > 3 else ""
    body = args[4] if len(args) > 4 else ""

    if "Claude" in app_name or "Claude" in summary:
        print(f"通知: {app_name} | {summary} | {body}")

bus = dbus.SessionBus()
bus.add_signal_receiver(
    notification_handler,
    "Notify",
    "org.freedesktop.Notifications",
    "/org/freedesktop/Notifications"
)

print("监听通知中... (Ctrl+C 停止)")
loop = GLib.MainLoop()
loop.run()
EOF
```

---

**创建日期**: 2026-02-03
**版本**: v0.3.0 - 基于 Kitty at_prompt 的可靠检测
