# 命令速查

## 核心特性

**Claude Code 自动状态提示** ⭐
- Claude 工作中：Tab 变蓝（非聚焦时显示）
- Claude 完成时：Tab 变红 + 桌面通知（非聚焦时显示）
- 查看结果后：自动恢复原色（3 秒）

## 安装

```bash
# 安装 Claude Manager（TUI 任务管理器）
pip install -e manager/

# 安装 Kitty 优化（配置、脚本、hooks）
cd kitty-enhance && ./install.sh

# 卸载 Kitty 优化
cd kitty-enhance && ./uninstall.sh
```

## 启动与运行（manager）

```bash
# 启动管理器
claude-manager

# 启动管理器（显示调试面板）
claude-manager --debug

# 查看实时日志
./manager/watch_logs.sh
```

## Kitty Tab 管理（kitty-enhance）

```bash
# Tab 重命名
tab-rename              # 完整重命名（含 git 分支）
tab-quick               # 快速重命名
tab-project             # 自动项目名 + 分支

# Tab 颜色标记
tab-alert               # 红色（需注意）
tab-warning             # 黄色（警告）
tab-done                # 绿色（完成）
tab-reset               # 重置颜色

# 别名
tr                      # = tab-rename
tq                      # = tab-quick
tp                      # = tab-project
tc                      # = tab-reset
ta                      # = tab-alert
```

## 飞书权限桥接（feishu-bridge）

```bash
# 一键配置（新用户用这个）
cd kitty-enhance/feishu-bridge && bash setup.sh

# 启动守护进程（前台运行，Ctrl+C 停止）
cd kitty-enhance/feishu-bridge && python daemon.py

# 查看运行状态和 pending 请求
python daemon.py status

# 停止守护进程
python daemon.py stop

# 查看守护进程日志
tail -f /tmp/feishu-bridge/daemon.log

# 安装依赖
pip install lark-oapi pyyaml
```

## 调试命令

```bash
# 查看最近的状态摘要（每15秒自动打印）
grep "\[状态摘要\]" ~/.config/claude-manager/logs/app.log | tail -3

# 查看状态转换
grep "\[状态转换\]" ~/.config/claude-manager/logs/app.log | tail -5

# 检查 tmux session
tmux list-sessions | grep cm-

# Hook 调试
export CLAUDE_HOOK_DEBUG=1
tail -f /tmp/claude-hook.log
```

## TUI 快捷键

| 键 | 功能 |
|----|------|
| `n` | 创建新任务 |
| `Enter` | 激活选中任务 |
| `r` | 立即刷新所有任务状态 |
| `R` | 重启选中任务 |
| `d` | 删除选中任务 |
| `1-5` | 快速切换任务 |
| `q` | 退出 |
