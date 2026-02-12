# 快速调试参考卡片

## 🚀 启动测试

```bash
cd /mnt/data/claude-manager
pip install -e .

# 终端 1: 启动管理器
claude-manager

# 终端 2: 查看实时日志
./watch_logs.sh
```

## 📊 检查点

### 1. 检查 Kitty at_prompt 标志

```bash
# 查看你的 Claude 窗口
kitten @ ls | python3 -c "
import json, sys
for w in json.load(sys.stdin)[0]['tabs'][0]['windows']:
    if 'Claude' in w.get('title', ''):
        print(f\"ID={w['id']}, at_prompt={w.get('at_prompt', False)}, title={w['title']}\")
"
```

### 2. 检查 tmux session

```bash
# 列出所有 cm- session
tmux list-sessions | grep cm-

# 检查特定 session 的活动监控
tmux show-window-options -t cm-task1 | grep monitor
```

### 3. 查看最近日志

```bash
# 最近 20 行状态日志
tail -20 ~/.config/claude-manager/logs/app.log | grep "\[状态"

# 查找状态转换
grep "\[状态转换\]" ~/.config/claude-manager/logs/app.log | tail -5

# 查看状态摘要（每15秒自动打印）
grep "\[状态摘要\]" ~/.config/claude-manager/logs/app.log | tail -3
```

## 🎯 预期行为

| 操作 | at_prompt | 状态 | 颜色 |
|------|-----------|------|------|
| 刚创建任务 | true | pending | ○ 白色 |
| 开始输入问题 | false | running | ● 蓝色 |
| Claude 回答中 | false | running | ● 蓝色 |
| Claude 完成 | true | completed | ● 红色 |

## 🔧 常用调整

### 加快检测速度

编辑 `src/claude_manager/app.py:170` 行：

```python
# 从 5 秒改为 2 秒
self.set_interval(2, self.check_task_status_async)
```

### 调整完成判断阈值

编辑 `src/claude_manager/app.py:258` 行：

```python
# 从 25 行改为 20 行
if kitty_at_prompt and line_count > 20 and not is_welcome_screen:
```

## 🐛 常见问题

### 问题: 颜色一直不变

```bash
# 1. 检查是否有日志输出
tail -f ~/.config/claude-manager/logs/app.log

# 2. 检查 tmux_window_id 是否正确
# 在 claude-manager 启动时应该看到:
# "✅ 分屏布局已创建"
# "   右侧: tmux 工作区 (Window ID: XXX)"

# 3. 手动刷新
# 在 claude-manager 中按 'r' 键
```

### 问题: at_prompt 总是 false

```bash
# 检查 Kitty 版本
kitty --version

# 确保 Kitty 支持 at_prompt 标志
# 需要 Kitty >= 0.26.0
```

## 📝 关键日志标记

- `[状态转换]` → 🟢 **状态变化了！**
- `[Kitty标志] at_prompt=true` → ✅ **在提示符处**
- `[Kitty标志] at_prompt=false` → ⏳ **正在工作**
- `is_welcome=True` → ⚠️ **刚启动，不算完成**

## ⚡ 快捷键

| 键 | 功能 |
|----|------|
| `r` | 立即刷新所有任务状态 |
| `n` | 创建新任务 |
| `Enter` | 激活选中任务 |
| `1-5` | 快速切换任务 |
| `q` | 退出 |

---

**提示**: 如果颜色变换不对，先查看日志确认 `at_prompt` 的值！
