# CLAUDE.md

## Project Overview

本仓库包含两个独立功能模块：

### 1. manager/ — Claude Manager TUI 任务管理器

轻量级 TUI 任务管理器，用来在终端中管理多个 Claude/开发任务。左侧为 Textual TUI 面板，右侧为 tmux 工作区；每个任务对应一个 tmux session（主会话 + 可选命令会话），通过终端适配器创建分屏并进行 session 切换。

核心能力：
- 任务管理（创建/切换/删除/描述）
- **终端发现**（自动发现 kitty 中运行的 Claude/Codex，交互式跳转）
- **工作状态看板**（`work-status` GUI：按工程分组，显示当前任务摘要，支持跳转/关 Tab）
- 终端分屏（Kitty Remote Control、xterm/Terminator 兜底）
- tmux 会话生命周期管理
- 基于 tmux 活动检测的任务状态更新（running/completed）

### 2. kitty-enhance/ — Kitty 终端优化工具

Kitty 终端增强工具集，包括配置模板、Tab 管理、Claude Code Hook 通知。

核心能力：
- Kitty 高性能配置模板（远程控制、分屏、快捷键）
- Tmux 优化配置（Vi 风格、鼠标滚轮、分屏快捷键）
- Tab 管理 Shell 函数（重命名、颜色标记）
- Claude Code / Codex 状态提示（Tab 变色 + 桌面通知 + 自动重置）
- Tab 标题跟随最近聚焦的 AI 窗口（含工作中 spinner）
- 把当前用户 prompt 写入 registry，供工作状态看板显示

## Directory Structure

```
claude-manager/
├── manager/                    # 终端管理器（终端发现 + TUI 任务面板 + 工作状态 GUI）
│   ├── src/claude_manager/
│   │   ├── tabs/               # 终端发现、跳转、工作状态看板
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
│   ├── scripts/                # Kitty 辅助脚本（含 Codex 监控、Tab 标题）
│   ├── hooks/                  # Claude Code hooks
│   ├── shell-functions.sh      # Tab 管理 Shell 函数
│   ├── install.sh              # 一键安装
│   └── uninstall.sh            # 卸载
├── tools/                      # 独立 CLI（ai-run：按会话选择 skill/MCP）
├── CLAUDE.md
└── README.md
```

## Environment Setup

依赖：
- Python 3.10+
- tmux（必须，仅 TUI 任务管理器）
- 终端：Kitty（推荐，需 allow_remote_control）、xterm、Terminator
- 工作状态 GUI：PyQt5、wmctrl（用于激活 Kitty OS 窗口）

安装：
```bash
# 终端管理器（含终端发现 + work-status GUI + TUI）
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

# 工作状态看板
work-status                      # PyQt5 GUI（按工程分组，单击跳转）
ws                               # 同上（shell 别名）
agent-terminals work-status -i   # 终端交互式列表
agent-terminals work-status --json

# 按会话选择 skill / MCP（不改全局配置）
python3 tools/ai-run inventory
python3 tools/ai-run claude --skills none --mcp none
python3 tools/ai-run codex --skills brainstorming --mcp none -- --model gpt-5.6-sol

# TUI 任务管理器
claude-manager                   # 启动 TUI
claude-manager --check           # 环境检查
claude-manager --debug           # 调试面板

# 测试
cd manager && pytest
cd kitty-enhance && python -m pytest tests/

# 日志
./manager/watch_logs.sh
```

## Architecture Overview (manager/tabs — 终端发现与工作状态)

数据流：
```
Claude Code hook / Codex wrapper
    → feishu-register.sh / codex-working.sh 写入 /tmp/feishu-bridge/registry.json
    → agent-terminals list 读取 registry，kitten @ ls 做活性过滤
    → work-status 再扫全部 kitty socket，按工程分组展示任务
```

任务摘要数据流：
```
Claude UserPromptSubmit → on-user-prompt.sh → registry.task_summary
Codex user_message     → codex-event-monitor.py → CM_TASK_SUMMARY → registry
看板读取：当前窗口的 registry 记录优先；
          没有则回退 ~/.claude/projects/*/sessions-index.json
          或 ~/.codex/sessions/*.jsonl 中匹配 cwd 的最新用户消息
```

模块：
- `manager/src/claude_manager/tabs/registry.py`：TerminalInfo 数据模型、registry 读取、活性过滤
- `manager/src/claude_manager/tabs/kitty.py`：kitten @ focus-window 包装
- `manager/src/claude_manager/tabs/cli.py`：argparse 命令、表格渲染（含 CJK 宽度对齐、斑马纹）
- `manager/src/claude_manager/tabs/interactive.py`：交互式选择器（alternate screen buffer、raw mode）
- `manager/src/claude_manager/tabs/work_status.py`：扫描全部 Kitty 窗口/Tab，提取 Claude/Codex 进程
- `manager/src/claude_manager/tabs/task_summary.py`：从本地 session 文件回退任务摘要
- `manager/src/claude_manager/tabs/work_status_gui.py`：PyQt5 看板（`work-status` 入口，单实例、后台启动）
- `manager/src/claude_manager/tabs/work_status_interactive.py`：终端内交互式列表（`agent-terminals work-status -i`）

共享契约：
- `/tmp/feishu-bridge/registry.json` 由 kitty-enhance hooks / Codex 脚本写入，tabs 模块只读。路径不变。
- 每条记录新增可选字段 `task_summary`（当前用户 prompt 第一行，最多 72 字）；缺省时看板走本地 session 回退。
- terminal_id 格式为 `window_id@socket_label`（如 `2@mykitty-324733`），用于唯一标识跨 kitty 实例的终端。
- `work-status` 用 Kitty `is_active` 标记每个 OS 窗口当前打开的 Tab（非焦点窗口不能用 `is_focused`）。

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
- `kitty-enhance/scripts/ai-tab-title-monitor.py`：把 Tab 标题同步成最近聚焦的 Claude/Codex 窗口标题；socket 级锁，无 AI 后退出。
- `kitty-enhance/scripts/codex-event-monitor.py`：监视 Codex session jsonl；`user_message` 写任务摘要，标题 spinner 作为 working 补充信号。
- `kitty-enhance/scripts/codex-working.sh` / `codex-completed.sh`：Codex Tab 变蓝/变红，并更新 registry。
- `kitty-enhance/hooks/on-user-prompt.sh`：Claude `UserPromptSubmit`，登记当前任务摘要。
- `kitty-enhance/hooks/on-stop.sh`：Claude 完成后 Tab 变红 + 桌面通知 + 后台轮询自动重置。
- `kitty-enhance/hooks/tab-color-common.sh`：`set_tab_color` / `clear_tab_color_state`（先恢复默认色再删状态，避免焦点竞态留下孤儿颜色）。
- `kitty-enhance/bin/codex`：Codex wrapper；启动标题监控 + 事件监控。pidfile 按 `socket hash + window id` 隔离多 Kitty 实例。
- `kitty-enhance/shell-functions.sh`：Shell 函数（tab-rename/tab-project/tab-alert、`ws` → `work-status`）。
- `kitty-enhance/install.sh`：一键安装（配置、脚本、hooks、settings.json 注入，含 `UserPromptSubmit`）。

## Architecture Overview (tools/ai-run)

`tools/ai-run` 为单次会话选择 skill / MCP，不改 `~/.claude` / `~/.codex` 全局文件。

- Claude：`--settings skillOverrides` + 临时 `--mcp-config`；`--yolo` → `--dangerously-skip-permissions`
- Codex：`-c skills.config=...` 与 `mcp_servers.*.enabled=`；`--yolo` → `--dangerously-bypass-approvals-and-sandbox`
- `ai-run inventory` 列出当前目录可见的 skill / MCP 名称

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

- `cd manager && pytest`：模型、任务摘要、work-status GUI（offscreen）、跳转命令、`ai-run`
- `cd kitty-enhance && python -m pytest tests/`：Codex wrapper/monitor、Tab 标题、Tab 颜色状态
- TUI 与真实 Kitty/tmux 集成需要在终端环境下手动验证

## Known Gaps / Legacy

- `manager/src/claude_manager/kitty_control.py`：旧版 Kitty 控制器，已被 `terminal/kitty_adapter.py` 取代。
- `manager/src/claude_manager/process_monitor.py`：进程监控模块尚未集成到 UI。
- `manager/src/claude_manager/terminal/tmux_split_adapter.py`：纯 tmux 模式适配器，未接入自动检测。
