# CLAUDE.md

## Project Overview

本仓库包含两个独立功能模块：

### 1. manager/ — Claude Manager TUI 任务管理器

轻量级 TUI 任务管理器，用来在终端中管理多个 Claude/开发任务。左侧为 Textual TUI 面板，右侧为 tmux 工作区；每个任务对应一个 tmux session（主会话 + 可选命令会话），通过终端适配器创建分屏并进行 session 切换。

核心能力：
- 任务管理（创建/切换/删除/描述）
- **终端发现**（自动发现 kitty 中运行的 Claude/Codex，交互式跳转）
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
├── manager/                    # 终端管理器（终端发现 + TUI 任务面板）
│   ├── src/claude_manager/
│   │   ├── tabs/               # 终端发现与跳转模块
│   │   ├── terminal/           # 终端适配器
│   │   ├── cli.py              # 主入口
│   │   └── ...
│   ├── tests/
│   ├── install.sh              # 一键安装
│   ├── pyproject.toml
│   └── watch_logs.sh
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

安装：
```bash
# 终端管理器（含终端发现 + TUI）
cd manager && ./install.sh

# Kitty 优化（配置、脚本、hooks）
cd kitty-enhance && ./install.sh
```

说明：当前版本不支持在 tmux 会话内直接运行（启动会被拒绝）。

## Common Commands

```bash
# 终端发现与跳转
agent-terminals                  # 交互式选择
agent-terminals list             # 列表
agent-terminals focus <id>       # 跳转
claude-manager tabs list         # 兼容入口

# TUI 任务管理器
claude-manager                   # 启动 TUI
claude-manager --check           # 环境检查
claude-manager --debug           # 调试面板

# 测试
cd manager && pytest

# 日志
./manager/watch_logs.sh
```

## Architecture Overview (manager/tabs — 终端发现)

数据流：
```
Claude Code hook 触发 (on-tool-use.sh 等)
    → feishu-register.sh 写入 /tmp/feishu-bridge/registry.json
    → agent-terminals list 读取 registry
    → 对每个 kitty socket 调 kitten @ ls 做活性过滤
    → agent-terminals focus 调 kitten @ focus-window 跳转
```

模块：
- `manager/src/claude_manager/tabs/registry.py`：TerminalInfo 数据模型、registry 读取、活性过滤
- `manager/src/claude_manager/tabs/kitty.py`：kitten @ focus-window 包装
- `manager/src/claude_manager/tabs/cli.py`：argparse 命令、表格渲染（含 CJK 宽度对齐、斑马纹）
- `manager/src/claude_manager/tabs/interactive.py`：交互式选择器（alternate screen buffer、raw mode）

共享契约：
- `/tmp/feishu-bridge/registry.json` 由 kitty-enhance hooks 写入，tabs 模块只读。路径和 schema 不变，hooks 和 feishu-bridge 代码均未修改。
- terminal_id 格式为 `window_id@socket_label`（如 `2@mykitty-324733`），用于唯一标识跨 kitty 实例的终端。

### tmux 内终端发现的已知问题

在 kitty tab 里通过 tmux 运行 Claude 时，存在三层障碍导致 `agent-terminals` 无法发现：

1. **环境变量不传递**：tmux 默认不传递 `$KITTY_WINDOW_ID` 和 `$KITTY_LISTEN_ON` 到子 session。已在 `tmux.conf` 添加 `set -ga update-environment " KITTY_WINDOW_ID"` 缓解，但仅对新建的 tmux session 生效，已存在的 session 需要重新 attach。

2. **Window ID 冲突**：同一个 kitty window 内的多个 tmux pane 共享同一个 `$KITTY_WINDOW_ID`。registry 以 terminal_id 为 key，多个 Claude 实例会互相覆盖，只有最后活跃的那个出现在列表里。

3. **Window ID 错位**：`claude-manager` TUI 创建 tmux session 时继承的是 TUI 面板的 kitty window ID，而非右侧工作区面板的 ID。focus 跳转会跳到错误的窗口。

可能的后续方案：通过进程扫描（`ps aux | grep claude`）作为 fallback 补充发现，或扩展 hook 让 tmux 内的 Claude 用 `$TMUX_PANE` 作为标识。

## Architecture Overview (manager/TUI — 任务管理器)

入口与主流程：
- `manager/src/claude_manager/cli.py`：命令行入口，`tabs` 子命令在最前端分流（绕过 TUI/tmux 检查），其余走 `--check/--debug` 或启动分屏。
- `manager/src/claude_manager/launcher.py`：检测终端 → 确保 tmux session → 创建面板 → 启动 TUI。
- `manager/src/claude_manager/app.py`：Textual TUI 主应用；任务 CRUD、状态检测、tmux 切换。

TUI 核心模块：
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
- Claude API 环境变量：自动继承启动进程的 `ANTHROPIC_*` 变量
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
