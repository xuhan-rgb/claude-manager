# CLAUDE.md

## Project Overview

本仓库包含两个独立功能模块：

### 1. manager/ — Claude Manager TUI 任务管理器

轻量级 TUI 任务管理器，用来在终端中管理多个 Claude/开发任务。左侧为 Textual TUI 面板，右侧为 tmux 工作区；每个任务对应一个 tmux session（主会话 + 可选命令会话），通过终端适配器创建分屏并进行 session 切换。

核心能力：
- 任务管理（创建/切换/删除/描述）
- 终端分屏（Kitty Remote Control、xterm/Terminator 兜底）
- tmux 会话生命周期管理
- 基于 tmux 活动检测的任务状态更新（running/completed）

### 2. kitty-enhance/ — Kitty 终端优化工具

Kitty 终端增强工具集，包括配置模板、Tab 管理、Claude Code Hook 通知。

核心能力：
- Kitty 高性能配置模板（远程控制、分屏、快捷键）
- Tmux 优化配置（Vi 风格、鼠标滚轮、分屏快捷键）
- Tab 管理 Shell 函数（重命名、颜色标记）
- Claude Code 完成通知（Tab 变红 + 桌面通知 + 自动重置）

## Directory Structure

```
claude-manager/
├── manager/                    # TUI 任务管理器
│   ├── src/claude_manager/     # Python 源码
│   ├── tests/                  # 测试
│   ├── pyproject.toml          # 包配置
│   └── watch_logs.sh           # 日志跟踪
├── kitty-enhance/              # Kitty 优化工具
│   ├── config/kitty/           # kitty.conf + theme.conf
│   ├── config/tmux/            # tmux.conf
│   ├── scripts/                # Kitty 辅助脚本
│   ├── hooks/                  # Claude Code hooks
│   ├── shell-functions.sh      # Tab 管理 Shell 函数
│   ├── install.sh              # 一键安装
│   └── uninstall.sh            # 卸载
├── CLAUDE.md
├── COMMANDS.md
└── README.md
```

## Environment Setup

依赖：
- Python 3.10+
- tmux（必须）
- 终端：Kitty（推荐，需 allow_remote_control）、xterm、Terminator

安装（开发模式）：
```bash
# TUI 任务管理器
pip install -e manager/

# Kitty 优化（配置、脚本、hooks）
cd kitty-enhance && ./install.sh
```

说明：当前版本不支持在 tmux 会话内直接运行（启动会被拒绝）。

## Common Commands

```bash
# 运行 TUI（自动检测终端并创建分屏）
claude-manager

# 显示调试面板
claude-manager --debug

# 环境检查
claude-manager --check

# 运行测试
cd manager && pytest

# 跟随日志
./manager/watch_logs.sh
```

## Architecture Overview (manager/)

入口与主流程：
- `manager/src/claude_manager/cli.py`：命令行入口，解析 `--check/--debug`，启动分屏。
- `manager/src/claude_manager/launcher.py`：检测终端 → 确保 tmux session → 创建面板 → 启动 TUI。
- `manager/src/claude_manager/app.py`：Textual TUI 主应用；任务 CRUD、状态检测、tmux 切换。

核心模块：
- `manager/src/claude_manager/tmux_control.py`：tmux session 管理。
- `manager/src/claude_manager/terminal/`：终端适配器（Kitty/xterm/Terminator）。
- `manager/src/claude_manager/data_store.py`：任务/终端/session JSON 持久化。
- `manager/src/claude_manager/config.py`：配置加载与默认值。
- `manager/src/claude_manager/models.py`：数据模型与默认布局预设。

## Architecture Overview (kitty-enhance/)

- `kitty-enhance/config/kitty/kitty.conf`：Kitty 配置模板（远程控制、快捷键、性能优化）。
- `kitty-enhance/config/tmux/tmux.conf`：Tmux 配置（Vi 风格、鼠标支持、分屏快捷键）。
- `kitty-enhance/scripts/`：Kitty Tab 操作脚本（重命名、快速重命名、重置颜色）。
- `kitty-enhance/hooks/on-stop.sh`：Claude Code 完成后 Tab 变红 + 桌面通知 + 后台轮询自动重置。
- `kitty-enhance/shell-functions.sh`：Shell 函数（tab-rename/tab-project/tab-alert 等）。
- `kitty-enhance/install.sh`：一键安装（配置、脚本、hooks、settings.json 注入）。

## Key Configuration

配置与数据位置（manager）：
- `~/.config/claude-manager/config.yaml`：状态检测与 UI 宽度
- `~/.config/claude-manager/terminal.yaml`：终端类型选择、面板布局
- `~/.config/claude-manager/layout.yaml`：保存上次的面板宽度
- `~/.config/claude-manager/claude_env.conf`：Claude API 环境变量覆盖
- `~/.config/claude-manager/logs/app.log`：运行日志
- `~/.local/share/claude-manager/data/tasks.json`：任务持久化

## Task Lifecycle & Status Detection

任务创建：
- TUI 中创建任务后生成 `task_id`（名称 MD5 前 6 位，冲突追加数字）。
- 创建主 session `cm-{task_id}` + 命令 session `cm-{task_id}-cmd`。

状态检测（定时 `config.status.check_interval`）：
- 使用 tmux `window_activity` 计算 `activity_ago`。
- 连续活跃 >= `continuous_duration` → running。
- running 且活动停止 → completed。
- 捕获 `Esc to cancel` 文本时强制标记 running。
- completed 被选中后重置为 pending。

## TUI Keybindings

| 键 | 功能 |
|----|------|
| `n` | 创建新任务 |
| `Enter` | 激活选中任务 |
| `r` | 立即刷新所有任务状态 |
| `R` | 重启选中任务的 Claude |
| `d` | 删除选中任务 |
| `1-5` | 快速切换任务 |
| `q` | 退出 |

## Testing

- `cd manager && pytest`（仅覆盖模型与序列化）
- TUI 与终端集成需要在真实终端环境下手动验证

## Known Gaps / Legacy

- `manager/src/claude_manager/kitty_control.py`：旧版 Kitty 控制器，已被 `terminal/kitty_adapter.py` 取代。
- `manager/src/claude_manager/process_monitor.py`：进程监控模块尚未集成到 UI。
- `manager/src/claude_manager/terminal/tmux_split_adapter.py`：纯 tmux 模式适配器，未接入自动检测。
