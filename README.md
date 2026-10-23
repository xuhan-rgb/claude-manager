# Claude Manager

面向 Claude Code / Codex 开发工作流的 Kitty 终端工具集，包含 Tab 状态提示、会话备份、工作状态看板，以及仍在开发中的任务管理 TUI。

## 功能与入口

| 需求 | 入口 | 说明 |
|------|------|------|
| 查看 AI 工作状态、管理 Tab | Kitty 增强 | 运行时选中 Tab 为主题绿色，未选中为蓝色；完成为红色，Claude 等待确认为黄色 |
| 保存和恢复终端会话 | `tab-save` / `tab-restore` | 保存当前 Kitty 窗口的 Tab，支持定时覆盖备份和对话恢复 |
| 按工程查看任务 | `work-status` | GUI 看板，支持跳转和关闭 Tab |
| 查找、切换 AI 终端 | `agent-terminals` | 交互列表、状态筛选、JSON 输出，支持多个 Kitty 实例 |
| 使用本地 Codex daemon | `codex-yolo` | 独立安装，共享本机 Unix socket，支持恢复会话 |
| 按会话选择 skill / MCP | `tools/ai-run` | 仅影响本次启动 |
| 输入分类与任务分派 | Jev（实验性） | 根据判断分派给 Luna，失败或不确定时交回当前会话 |
| 管理任务与 tmux 工作区 | `claude-manager`（开发中） | TUI 任务面板、状态检测和布局预设 |

## 导航

- [快速开始](#快速开始) · [依赖](#依赖)
- [Kitty 配置与快捷键](#kitty-配置) · [AI 状态提示](#ai-状态提示)
- [Codex 独立启动器](#codex-独立启动器) · [Tab 管理](#tab-管理命令) · [会话备份与恢复](#会话备份与恢复)
- [工作状态看板](#工作状态看板) · [终端发现与跳转](#终端发现与跳转)
- [飞书终端管理中心](#飞书终端管理中心) · [Tmux 配置](#tmux-配置)
- [按会话选择 skill / MCP](#按会话选择-skill--mcp) · [Jev 输入分派](#jev-输入分派)
- [Claude Manager TUI](#claude-manager-tui) · [配置文件](#配置文件) · [数据存储](#数据存储)
- [开发](#开发) · [项目结构](#项目结构)

## 快速开始

本节命令均从仓库根目录执行；Kitty 安装使用子 Shell，执行后仍停留在根目录。

### 1. 安装 Kitty 增强

适合日常 Claude Code / Codex 开发，无需 tmux。

```bash
(cd kitty-enhance && ./install.sh)

# 在 Kitty 中重新加载配置和 Shell 函数
kitty @ --to unix:@mykitty load-config
source ~/.bashrc  # zsh 用户使用 source ~/.zshrc

# 常用操作
tab-project              # Tab 标题设为项目名 + 分支
tab-rename               # 交互式重命名
tab-save work            # 立即保存，并默认每 10 分钟更新快照
```

安装器会复制 Kitty 配置和辅助脚本，配置 Claude Code Hooks，并向 Shell rc 添加函数加载入口。
完整安装也会尝试安装 `codex-yolo`；其默认权限修改和配置备份见 [Codex 独立启动器](#codex-独立启动器)。

### 2. 安装终端管理与工作状态看板

需要 Python 3.10+ 和 `uv`，依赖安装见下一节。此入口无需启动任务 TUI 或 tmux。

```bash
bash manager/install.sh
work-status                 # 打开工作状态 GUI
agent-terminals             # 交互式选择并跳转终端
agent-terminals list --active # 只看运行中 / 等待确认的终端
```

安装器使用 `uv` 创建 Python 虚拟环境，以 editable 模式安装，并将
`claude-manager`、`agent-terminals`、`work-status` 链接到 `~/.local/bin/`。
请确保该目录在 `PATH` 中。卸载使用 `bash manager/install.sh --uninstall`。

### 3. 按需启用任务 TUI

TUI 仍在开发中，日常终端管理建议使用上面的 Kitty 增强和独立终端管理入口。
需要先安装 Kitty 增强、Manager 和 tmux 2.4+。

```bash
claude-manager --check       # 检查环境
claude-manager              # 启动任务面板和 tmux 工作区
claude-manager --debug      # 启用调试面板
```

任务操作和快捷键见 [Claude Manager TUI](#claude-manager-tui)。旧入口
`claude-manager tabs ...` 仍兼容，等价于 `agent-terminals ...`。

---

## 依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 运行环境 |
| Kitty | - | 终端模拟器 |
| Tmux | 2.4+ | 会话管理（仅 TUI） |
| textual | >= 0.40.0 | TUI 框架 |
| PyQt5 | >= 5.15.0 | work-status 看板 |
| psutil | >= 5.9.0 | 进程监控 |
| pyyaml | >= 6.0 | 配置解析 |
| wmctrl | - | 看板跳转时激活 Kitty 窗口 |
| xclip | - | 剪贴板支持（可选） |

安装依赖：

```bash
# Ubuntu/Debian
sudo apt install kitty tmux wmctrl xclip

# 安装 uv（如果没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 Claude Manager
bash manager/install.sh
```

---

## 终端配置详解

### Kitty 配置

配置文件：[kitty-enhance/config/kitty/](kitty-enhance/config/kitty/)

| 文件 | 说明 |
|------|------|
| `kitty.conf` | 主配置 |
| `theme.conf` | 1984 Dark 主题 |
| `install.sh` | 一键安装脚本 |
| `README.md` | 快捷键文档 |

#### Kitty 快捷键

**创建窗口/标签**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `Alt+Enter` | 新建标签 | 在顶部标签栏创建新标签 |
| `Alt+n` | 新建 OS 窗口 | 创建独立的 Kitty 窗口 |
| `Ctrl+Enter` | 同目录新建窗口 | 在当前标签内分屏，继承工作目录 |

**窗口切换**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `Ctrl+←` | 切换到左侧窗口 | 在分屏窗口间切换 |
| `Ctrl+→` | 切换到右侧窗口 | |
| `Ctrl+↑` | 切换到上方窗口 | |
| `Ctrl+↓` | 切换到下方窗口 | |

**调整窗口大小** ⭐

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `Ctrl+Shift+←` | 窗口变窄 | 向左缩小当前窗口宽度 |
| `Ctrl+Shift+→` | 窗口变宽 | 向右扩大当前窗口宽度 |
| `Ctrl+Shift+↑` | 窗口变高 | 向上扩大当前窗口高度 |
| `Ctrl+Shift+↓` | 窗口变矮 | 向下缩小当前窗口高度 |

**标签切换**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `Alt+←` | 上一个标签 | 切换到左侧标签 |
| `Alt+→` | 下一个标签 | 切换到右侧标签 |
| `Alt+↑` | 标签左移 | 调整标签顺序 |
| `Alt+↓` | 标签右移 | |

**布局与全屏**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `Ctrl+Shift+e` | 选择布局 | 弹出布局选择菜单 |
| `Cmd+Shift+l` | 下一个布局 | 在 tall/stack/grid 间切换 |
| `Ctrl+Shift+f` | 全屏切换 | 进入/退出全屏模式 |

**通用操作**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `Ctrl+Shift+w` | 关闭窗口 | 关闭当前分屏窗口 |
| `Ctrl+Alt+w` | 关闭窗口 | 同上（备用） |
| `Ctrl+Shift+c` | 复制 | 复制选中内容到剪贴板 |
| `Ctrl+Shift+v` | 粘贴 | 从剪贴板粘贴 |
| `Ctrl+Shift+=` | 放大字体 | 增大字号 |
| `Ctrl+Shift+-` | 缩小字体 | 减小字号 |
| `Ctrl+Shift+Backspace` | 重置字体 | 恢复默认字号 |

#### Kitty 特性

- **远程控制**: 已启用 `allow_remote_control`，支持 `kitty @` 命令
- **性能优化**: 60fps、垂直同步、禁用 URL 检测
- **布局模式**: tall（主窗口在左）/ stack（堆叠）/ grid（网格）

#### Kitty 远程控制命令

```bash
# 列出所有窗口
kitty @ ls

# 在当前标签新建窗口
kitty @ launch --cwd=current

# 发送文本到指定窗口
kitty @ send-text --match id:1 "echo hello"

# 设置窗口标题
kitty @ set-window-title "My Window"
```

### AI 状态提示

Claude Code Hooks 和 Codex 事件监控会更新 Tab 状态；Tab 标题跟随最近聚焦的 AI 窗口。

| 状态 | Tab 显示 |
|------|----------|
| 运行中 | 选中为主题绿色，未选中为蓝色 |
| 等待确认（Claude） | 黄色通知 |
| 当前轮次完成 | 红色通知 |
| 聚焦带通知的 Tab | 清除红 / 黄通知，恢复默认颜色 |

**工作流程**：
- `on-tool-use.sh`：调用工具时记录运行状态 → 选中为主题绿色，未选中为蓝色
- `on-notify.sh`：需要确认时 → 黄色（权限对话框、输入确认等）
- `on-stop.sh`：完成回答时 → 红色（非聚焦显示）
- **自动恢复**：红/黄通知色在聚焦后恢复原色；运行中的 Tab 由 Kitty 即时切换选中绿色、未选中蓝色

**Codex 补充**：
- 安装 `kitty-enhance` 后，Shell 会自动包一层 `codex` 命令
- 这条链路是**独立实现**，不会改动现有 Claude Hook
- Codex 开始处理时 → 选中绿色、未选中蓝色；Codex 当前轮次完成时 → 红色
- 目前 Codex 复用了同一套 Tab 恢复逻辑；Claude 的黄色确认通知保持原样
- Tab 标题会同步成最近聚焦的 AI 窗口标题；Claude 提交 prompt 时会登记任务摘要，供 `work-status` 显示

### Codex 独立启动器

`codex-yolo` 可以单独安装到其他电脑，无需完整 Kitty 增强。

前提：Linux/macOS 上有 Bash、Python 3，以及支持 `--remote`、
`app-server daemon start` 的 Codex CLI。
请先在目标电脑配置 Codex 登录或 API provider。安装脚本使用本机 CLI 检查 remote 和 daemon 命令；
不下载 Codex，也不复制其他电脑的密钥、账号或项目路径。

在仓库根目录执行（无需安装 Kitty）：

```bash
bash kitty-enhance/install-codex-yolo.sh
source ~/.bashrc  # zsh 用户：source ~/.zshrc；也可以重新打开终端
codex-yolo
codex-yolo --cd /path/to/project
codex-yolo resume --last
```

安装到 `~/.local/bin/codex-yolo`，支持重复运行。完整 Kitty 安装也会尝试安装该命令。
`bash kitty-enhance/install.sh --codex-only` 也会调用同一个独立安装脚本。
安装器在 shell rc 末尾添加受管理的配置块，使旧的同名 alias/函数不再遮蔽新命令；
首次修改前将原 rc 备份为 `.bashrc.before-codex-yolo` / `.zshrc.before-codex-yolo`。

启动流程沿用当前系统配置：优先通过已有的 `codex-auth run --` 选择账号；
未安装 `codex-auth` 时直接使用 PATH 中的 `codex`。
先启动或复用本地共享 daemon，读取返回的 `socketPath`，再使用
`--remote unix://…` 连接。
启动时不再自动选择 `yolo` profile，避免旧 `yolo.config.toml` 覆盖主配置。
修改 `${CODEX_HOME:-~/.codex}/config.toml` 中的模型后，新打开的 `codex-yolo` 对话直接使用新配置。
这里的 remote 指本机 Unix socket。其他参数原样传给交互客户端；
`--help` / `--version` 不启动 daemon。daemon 启动失败或响应缺少有效 socket 时停止启动。

安装器在 `${CODEX_HOME:-~/.codex}/config.toml` 设置基础默认权限
`approval_policy = "never"` 和 `sandbox_mode = "danger-full-access"`；普通 `codex`
新建任务也会继承 YOLO 默认权限。已有 `yolo.config.toml` 的权限字段与权限配置块会移除，
其余模型、provider、skills 和 MCP 设置保留；缺少时创建仅继承基础配置的最小 profile。
首次修改已有配置前备份为 `config.toml.before-codex-yolo` / `yolo.config.toml.before-codex-yolo`。
不在启动命令中添加权限覆盖，使 `codex-yolo resume`、`resume --last` 和进入后 `/resume`
均可沿用服务端保存的任务权限；旧任务不会被强制改为 YOLO。更新后退出旧交互客户端再启动，
后台 daemon 无需因本次配置迁移而重启。不会安装或覆盖 `codex-auth`。
`--codex-only` 不安装 Kitty 通知组件；已有 Kitty wrapper 时，daemon 管理调用不触发窗口监控，
交互客户端仍保留 Kitty 环境。共享 daemon 下多窗口会话与任务摘要的精确绑定不在此安装功能范围内。

### Tab 管理命令

在 Shell 中使用快速命令管理 Tab：

| 命令 | 别名 | 功能 | 示例 |
|------|------|------|------|
| `tab-rename` | `tr` | 交互式重命名（支持 git 分支） | `tr` → 输入名称 |
| `tab-quick` | `tq` | 快速重命名 | `tq my-task` |
| `tab-project` | `tp` | 自动设置项目名+分支 | `tp` |
| `tab-reset` | `tc` | 重置 Tab 颜色为默认 | `tc` |
| `tab-alert` | `ta` | 手动标记为红色 | `ta` |
| `tab-warning` | - | 手动标记为黄色 | `tab-warning` |
| `tab-done` | - | 手动标记为绿色 | `tab-done` |
| `tab-save` | - | 立即保存，并默认每 10 分钟覆盖更新同一份快照 | `tab-save work` |
| `tab-restore` | - | 在新 Kitty 窗口恢复保存的 Tab 和对话 | `tab-restore work` |
| `tab-list` | - | 列出已保存的 Tab 快照 | `tab-list` |
| `tab-backup` | - | 查看、停止周期任务，或恢复最近一份周期快照 | `tab-backup status` |

**使用示例**：
```bash
# 快速重命名当前 Tab
tr                  # 交互式，支持 git 分支检测
tr "feature-x"      # 直接指定名称

# 自动设置项目名+分支
tp                  # 变为 "project-name (main)"

# 颜色标记
ta                  # 红色（需要关注）
tab-warning         # 黄色（警告）
tab-done            # 绿色（完成）
tc                  # 重置为默认
```

### 会话备份与恢复

`tab-save work` 会先保存一次，然后通过用户级 systemd timer 每 10 分钟更新
`work.session` 和 `work.meta.json`，仅保留最新一份，不生成历史文件。
不传名称时使用 `auto`。周期任务在后台执行，不占用执行命令的 Shell。
首次更新命令后，在现有 Shell 中运行：

```bash
# 在仓库根目录执行
source kitty-enhance/shell-functions.sh

tab-save work                 # 立即保存，并每 10 分钟更新
tab-save work --interval 30m  # 修改频率（支持 s、m、h）
tab-save work --once          # 仅保存一次，不修改已有定时任务
tab-backup status            # 查看下一次保存时间
tab-backup stop              # 停止定时任务，保存文件保留
tab-restore work             # 恢复这份快照
tab-backup restore           # 恢复最近更新的周期快照
```

周期任务只备份执行 `tab-save` 时所在的 Kitty OS 窗口（包括全部 Tab），
每个用户只有一个定时任务；再次运行 `tab-save` 会更新目标窗口、保存名称和周期。
关闭目标 Kitty 窗口后，每轮检查跳过保存，保留最后一份快照和后台 timer。
关闭某个 Shell 或 Tab 时，只要整个目标窗口仍在，其他 Tab 继续保存。
重新打开 Kitty 后需再运行 `tab-save work` 绑定新窗口。
这是当前用户登录会话中的 timer，不会配置开机自启。
`tab-restore <name>` 和 `tab-backup restore` 在快照包含本地 Unix socket 的 Codex
连接时，会先运行 `codex app-server daemon start`，成功后再启动 Kitty。重启电脑后
无需手动先启动 daemon；启动失败时会报错并取消恢复。
后台保存结果和错误可通过
`journalctl --user -u kitty-tab-backup.service -n 20 --no-pager` 查看。
保存时会汇总缺失对话 ID 的提示，这类窗口无法保证恢复到原对话。

`tab-save work` 会把可恢复的对话写入 `~/.config/kitty-enhance/sessions/work.session`，
恢复时使用 `claude --resume <session-id>` 或 `codex resume <session-id>`。
保存前请至少发送一条消息，让对话日志落盘；旧快照需要重新保存才能补入会话 ID。
Claude 按 PID 读取会话记录；普通 Codex 读取该进程打开的会话日志。
本地 Unix socket 的 Codex daemon 模式优先用窗口标题匹配本地会话索引中的名称，
仅在名称与目录唯一对应、且对话日志存在时保存 ID；未匹配到名称时，再检查工作目录
唯一对应的已加载日志。同目录同名的多个候选不会猜测 ID。找不到 ID 会输出
`no session-id, fresh restore`，
此时保留启动命令，无法保证恢复到原对话。远程网络 daemon 的会话识别尚未支持。

### Tab 状态故障排查

如果 Tab 没有变色或自动恢复不工作：

```bash
# 1. 检查 Hook 是否安装
ls -l ~/.claude/hooks/

# 2. 检查 Shell 函数是否加载
type tab-rename

# 3. 启用调试日志
export CLAUDE_HOOK_DEBUG=1

# 4. 查看日志
tail -f /tmp/claude-hook.log

# 5. 验证 Kitty Remote Control
kitty @ ls
```

---

## 飞书终端管理中心

通过飞书远程管理所有 Claude Code / Codex 终端：权限审批、进度查看、远程指令。

```
┌─ 权限通知 ────────────────────────────────────────────┐
│  权限弹窗 → Hook 记录 pending → 超时 → 飞书卡片通知  │
│                                          ↓            │
│                                   回复 y/n → 终端继续  │
├─ 终端管理 ────────────────────────────────────────────┤
│  ls → 查看所有终端列表                                │
│  #N → 终端详情    #N 进度 → 查看屏幕                  │
│  #N <指令> → 远程发送文本到终端                       │
├─ 完成通知 ────────────────────────────────────────────┤
│  Claude / Codex 完成回答 → 飞书推送对话内容           │
└───────────────────────────────────────────────────────┘
```

**消息通道**：WebSocket 长连接 + API 轮询双通道，消息延迟 ~2 秒（WebSocket 固有延迟 ~15 秒，API 轮询兜底）。

### 飞书指令速查

| 指令 | 功能 | 示例 |
|------|------|------|
| `ls` | 终端列表 | `ls` |
| `ls -l` | 详细列表（含屏幕预览） | `ls -l` |
| `#N` | 终端详情 | `#7` |
| `#N 进度` | 查看终端屏幕 | `#7 进度` |
| `#N <文本>` | 远程发送指令 | `#7 请继续` |
| `#N esc` | 发送 Esc 键 | `#7 esc` |
| `#N ctrl+c` | 发送 Ctrl+C | `#7 ctrl+c` |
| `#N clear` | 清空终端屏幕 | `#7 clear` |
| `y` / `n` | 权限回复 | `y` |
| `?` | 显示帮助 | `?` |

> 终端处于工作中/等待状态时，发送指令会先弹出确认，避免误操作。

### 前置条件

1. Kitty 终端（已启用 `allow_remote_control`）
2. Python 3.10+ 与 `lark-oapi` 依赖
3. 飞书自建应用（见下方配置步骤）

### 飞书应用配置

1. **创建应用**：登录 [飞书开放平台](https://open.feishu.cn/app) → 创建自建应用

2. **获取凭据**：进入应用 → 左侧「凭证与基础信息」→ 记录 **App ID** 和 **App Secret**

3. **开启机器人**：左侧「应用能力」→「添加应用能力」→ 开启「机器人」

4. **添加权限**：左侧「权限管理」→ 搜索并开通：
   - `im:message:readonly` — 读取机器人所在聊天的消息（用于 API 轮询兜底）
   - `im:message:send_as_bot` — 以机器人身份发消息

   > 隐私说明：`im:message:readonly` 仅能读取**机器人参与的聊天**，不会访问用户的其他群聊或私聊。

5. **配置事件订阅**：左侧「事件与回调」→ 事件配置：
   - 订阅方式选「**长连接**」
   - 添加事件 `im.message.receive_v1`（接收消息）
   - **注意**：保存时会提示「应用未建立长连接」，需要先运行一次守护进程建立连接，然后再回来保存

6. **发布应用**：顶部「创建版本」→ 填写版本号 → 申请发布上线

7. **获取 open_id**：应用上线后，在飞书中搜索你的机器人 → 发一条消息 → 守护进程日志会打印你的 `open_id`（格式：`ou_xxxxxxxx`）

### 安装与配置

```bash
# 安装 Python 依赖
pip install lark-oapi pyyaml

# 编辑配置文件，填入飞书凭据
vim kitty-enhance/feishu-bridge/config.yaml
```

配置文件内容：
```yaml
feishu:
  app_id: "cli_xxxxx"        # 飞书自建应用 App ID
  app_secret: "xxxxx"        # 飞书自建应用 App Secret
  user_id: "ou_xxxxx"        # 接收消息的用户 open_id
  chat_id: ""                # P2P 聊天 ID（可选，留空自动捕获）

bridge:
  wait_minutes: 5             # 等待多久后发飞书通知（0=立即）
  poll_interval: 2            # 扫描 pending 文件间隔（秒）
  expire_minutes: 30          # pending 过期清理时间
  poll_api_interval: 2        # API 轮询间隔（秒），0=禁用

hub:
  registry_cleanup_interval: 120  # 注册表清理间隔（秒）
  max_screen_lines: 20            # 进度查看最大行数
  command_max_length: 500         # 指令最大长度
```

### 使用

```bash
# 启动守护进程
cd kitty-enhance/feishu-bridge
python daemon.py

# 查看状态（含在线终端列表）
python daemon.py status

# 停止
python daemon.py stop
```

启动后：
- **权限通知**：Claude Code 权限弹窗超时后自动发送飞书卡片，回复 y/n 即可操作
- **完成通知**：Claude / Codex 完成回答后推送对话内容到飞书
- **终端管理**：随时发送 `ls` 查看所有终端，`#N 进度` 查看屏幕

### 终端自动注册

终端通过三种方式注册到管理中心：

1. **Hook 实时注册**（推荐）：Claude Code Hook 在工具调用、完成、权限弹窗时自动注册终端状态
2. **Codex 包装器注册**：Shell 中启动 `codex` 时，后台监视会话事件并注册状态
3. **定期扫描**：守护进程定期扫描所有 Kitty 实例，发现运行 Claude / Codex 的窗口自动注册

### 新用户接入（一键配置）

飞书应用只需创建一次，团队共用同一个 App ID / App Secret。新用户接入只需：

```bash
cd kitty-enhance/feishu-bridge
bash setup.sh
```

脚本会自动：检查依赖 → 填入共享凭据 → 连接飞书获取个人 open_id → 生成 config.yaml → 安装 Hook。

新用户需要的信息（问管理员要）：
- **App ID** 和 **App Secret** — 团队共用
- 飞书中搜索机器人名字，发一条消息 — 脚本自动获取 open_id

### 首次建立长连接

飞书后台保存「长连接」配置时要求客户端已连接。首次配置时先启动守护进程（`python daemon.py`），再去飞书后台点「保存」。

---

## Tmux 配置

配置文件：[kitty-enhance/config/tmux/](kitty-enhance/config/tmux/)

| 文件 | 说明 |
|------|------|
| `tmux.conf` | 主配置 |
| `install.sh` | 一键安装脚本 |
| `README.md` | 快捷键文档 |

### Tmux 快捷键

**前缀键**: `Ctrl+a`（已从 `Ctrl+b` 修改）

> 以下 `前缀` 均指先按 `Ctrl+a`，松开后再按下一个键

**分屏操作**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `前缀 + h` | 左右分屏 | 在右侧创建新面板 |
| `前缀 + v` | 上下分屏 | 在下方创建新面板 |
| `Ctrl+Space` | 上下分屏并均分 | 自动平均分配高度 |
| `Ctrl+F2` | 左右分屏 | 无需前缀，直接分屏 |
| `Ctrl+F4` | 创建 2×2 四面板 | 一键创建四宫格布局 |
| `Ctrl+F6` | 创建 3+3 六面板 | 左右各三个面板 |

**面板切换（Vim 风格）** ⭐

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `Alt+h` | 切换到左侧面板 | 无需前缀，直接切换 |
| `Alt+j` | 切换到下方面板 | |
| `Alt+k` | 切换到上方面板 | |
| `Alt+l` | 切换到右侧面板 | |

**面板管理**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `前缀 + z` | 放大/还原面板 | 全屏显示当前面板，再按还原 |
| `前缀 + <` | 与上一个面板交换 | 调整面板位置 |
| `前缀 + >` | 与下一个面板交换 | |

**会话管理**

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `前缀 + s` | 同步输入模式 | 向所有面板同时输入（广播） |
| `前缀 + r` | 重载配置 | 修改 tmux.conf 后重载 |

### 鼠标滚轮翻页 ⭐

| 操作 | 效果 | 说明 |
|------|------|------|
| 滚轮向上 | 进入 copy-mode | 开始翻看历史输出 |
| 继续滚动 | 翻页 | 可以一直往上翻 |
| **打字** | **自动退出，正常输入** | 无需手动退出 |
| `q` / `Escape` | 退出 copy-mode | 手动退出 |

### Copy-mode（Vi 风格）

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `v` | 开始选择 | 进入选择模式 |
| `y` | 复制并退出 | 复制选中内容到 tmux 缓冲区 |
| `/` | 搜索 | 输入关键词搜索 |
| `n` | 下一个匹配 | 跳到下一个搜索结果 |
| `N` | 上一个匹配 | 跳到上一个搜索结果 |
| `PageUp/Down` | 翻页 | 快速翻页 |
| 鼠标拖选 | 选择并复制 | 自动复制到系统剪贴板 |

### Tmux 常用命令

```bash
# 列出所有会话
tmux ls

# 创建新会话
tmux new -s session_name

# 附加到会话
tmux attach -t session_name

# 切换会话
tmux switch -t session_name

# 关闭会话
tmux kill-session -t session_name

# 重载配置（在 tmux 内）
tmux source-file ~/.tmux.conf
```

---

## 工作状态看板

扫描全部 Kitty 窗口里的 Claude/Codex，按 Git 工程分组，卡片上显示处理中/待确认/已完成、当前任务、工作目录。

```bash
work-status                            # 打开 GUI（默认后台、单实例）
ws                                     # 同上
agent-terminals work-status -i         # 终端交互式列表
agent-terminals work-status --json     # JSON
```

- 单击卡片：激活对应 Kitty 窗口并聚焦 Tab
- 卡片 ×：关闭该 Tab
- 右键：忽略/取消忽略某个 Kitty 窗口
- 任务文案优先来自当前窗口刚提交的 prompt；没有则读本地 Claude/Codex session

安装：`bash manager/install.sh`（会链接 `work-status` 到 `~/.local/bin/`）

## 终端发现与跳转

自动发现所有 kitty 终端中运行的 Claude/Codex 实例，支持交互式选择跳转。

```bash
agent-terminals                        # 交互式选择（↑↓/jk 选择，Enter 跳转，q 退出）
agent-terminals list                   # 列出所有活跃终端
agent-terminals list --active          # 只看 working/waiting 状态
agent-terminals list --json            # JSON 格式输出
agent-terminals focus <terminal_id>    # 跳转到指定终端
# 等价入口：claude-manager tabs list / claude-manager tabs focus <terminal_id>
```

**输出示例**：
```
ID                  TAB                                          PROJECT         AGENT   STATUS     IDLE
2@mykitty-324733    Add project management and recovery feature  claude-manager  claude  working    刚刚
18@mykitty-324733   Build flight ticket scraper web application  dev-scripts     claude  waiting    7分钟前
7@mykitty-4149434   Claude Code                                  papers          claude  waiting    2小时前
1@mykitty-1827907   data                                         data            codex   completed  6分钟前
```

### 已知限制

- 仅支持 **kitty 终端直接启动** 的 Claude/Codex
- **tmux 内的 Claude 暂时无法被发现**（环境变量传递、ID 冲突等问题，详见 CLAUDE.md）
- gnome-terminal、VS Code 终端、SSH 远程终端暂不支持

---

## 按会话选择 skill / MCP

`tools/ai-run` 只影响这一次启动的 Claude/Codex，不改全局配置。

```bash
python3 tools/ai-run inventory
python3 tools/ai-run claude --skills agent-reach,tdd --mcp none
python3 tools/ai-run claude --skills none --mcp none --yolo
python3 tools/ai-run codex --skills brainstorming --mcp openaiDeveloperDocs -- --model gpt-5.6-sol
```

## Jev 输入分派

实验性功能，需单独安装并配置 TypeSafe API key 和 Codex hook，详见 [安装说明](docs/jev-router.md#安装)。

每条输入先由 `UserPromptSubmit` hook 让 Jev 判断 `simple_request` 和 `coding_task`，
再用 `jev-dispatch STATE.json` 执行。简单请求由独立 Luna 直接完成并交付；不确定、
失败或 API 异常交回当前会话。代码任务由当前会话补齐范围、上下文和实际 checks 后，
复用状态执行，checks 失败即返回 current。复杂任务仍可由当前模型使用原生 Luna 子代理。
默认 sandbox 是 `read-only`，明确授权写入时才使用 `workspace-write`。

统一设置入口：终端 `jev status` 查看总开关、输入路由、判断打印；`jev on/off`、
`jev entry on/off`、`jev print on/off` 即时切换后续判断。
需要完全停用 Codex hook 时运行 `jev-hook off`；`jev-hook on` 重新安装，`jev-hook status`
查看实际安装状态。详细规则通过 `jev-delegation` skill 手动调用，不写入全局 `AGENTS.md`。
当前模型委派子任务仍通过 `jev-run register/check/verify` 判断是否需要主模型审核。
`jev-execute` 独立简单入口免模型审核，`--parent-run` 委派路径保留审核；旧 `jev-chat` 只作
legacy，不推荐。入口不绕过 hooks trust、权限或审批。安装和使用见
[Jev 输入分派说明](docs/jev-router.md)。

---

## Claude Manager TUI

⚠️ **注意**：TUI 方案仍在优化中，推荐优先使用 [Kitty 增强](#快速开始) 进行日常开发。

### 启动方式

```bash
claude-manager           # 启动（自动创建三列分屏）
claude-manager --check   # 检查环境配置
claude-manager --debug   # 启用调试面板
```

### 界面布局

```
┌─────────────┬─────────────────────────────┐
│  TUI 面板   │  tmux 工作区                │
│  (25%)      │  (75%)                      │
│             │                             │
│  任务列表   │  每个任务 = tmux session    │
│  状态监控   │  可有多个 window            │
└─────────────┴─────────────────────────────┘
```

### 任务状态颜色

| 显示 | 颜色 | 状态 |
|------|------|------|
| **▶ 任务名** | 绿色 | 激活中 |
| **● 任务名** | 蓝色 | 运行中（Claude 正在回答） |
| **● 任务名** | 黄色 | 等待确认（权限对话框） |
| **● 任务名** | 红色 | 已完成（等待查看） |
| **○ 任务名** | 白色 | 待开始 |

### TUI 快捷键

#### 任务操作

| 快捷键 | 功能 |
|--------|------|
| `n` | 新建任务 |
| `d` | 删除任务 |
| `Enter` | 激活任务（切换 tmux session） |
| `Tab` | 切换面板 |
| `1-5` | 快速切换任务 |

#### 终端操作

| 快捷键 | 功能 |
|--------|------|
| `t` | 新建终端 |
| `c` | 新建 Claude 终端 |
| `r` | 重启 Claude（使用最新配置） |
| `x` | 关闭终端 |

#### 布局预设

| 快捷键 | 预设 | 说明 |
|--------|------|------|
| `F1` | focus | 单 Claude 终端 |
| `F2` | develop | Claude + Shell |
| `F3` | test | Claude + ROS2 + RQT |
| `F4` | monitor | 4 终端网格 |

#### 通用

| 快捷键 | 功能 |
|--------|------|
| `?` | 显示帮助 |
| `q` | 退出 |

---

## 配置文件

### 主配置

位置：`~/.config/claude-manager/config.yaml`

```yaml
status:
  check_interval: 1.0        # 状态检测间隔（秒）
  active_threshold: 1.0      # 活跃判断阈值
  continuous_duration: 2.0   # 连续活跃时长阈值

ui:
  left_panel_columns: 35     # 左侧面板宽度（首次启动默认值）
  min_right_columns: 80      # 右侧最小宽度
```

### 窗口布局（自动保存）

位置：`~/.config/claude-manager/layout.yaml`

**工作流程**：
1. 启动时自动加载上次保存的三列宽度
2. 使用 `Ctrl+Shift+←/→` 调整各列宽度
3. 退出时（按 `q`）自动保存当前布局
4. 下次启动时恢复相同宽度

```yaml
left_columns: 35      # 左侧 TUI 面板宽度
middle_columns: 120   # 中间 tmux 窗口宽度
right_columns: 60     # 右侧 tmux 窗口宽度
total_columns: 217    # 终端总宽度（用于检测大小变化）
```

> 如果终端大小改变，会重新计算默认比例

### Claude 环境变量

Claude Manager 会自动继承启动进程的 `ANTHROPIC_*` 环境变量，无需额外配置文件。

```bash
# 在启动 claude-manager 之前设置（或写入 ~/.bashrc）
export ANTHROPIC_BASE_URL="https://your-api-endpoint/api"
export ANTHROPIC_AUTH_TOKEN="your_token_here"
```

---

## 数据存储

```
~/.local/share/claude-manager/data/
├── tasks.json        # 任务列表
├── terminals.json    # 终端配置
└── session.json      # 会话状态

~/.config/claude-manager/logs/
└── app.log           # 应用日志
```

---

## 开发

```bash
# 安装开发依赖
pip install -e "manager/[dev]"

# 运行测试
cd manager && pytest

# 查看日志
tail -f ~/.config/claude-manager/logs/app.log
```

### 调试命令

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

---

## 项目结构

```
.
├── manager/                    # TUI 任务管理器 + 工作状态看板
│   ├── src/claude_manager/
│   │   ├── app.py             # TUI 主逻辑
│   │   ├── cli.py             # 命令行入口
│   │   ├── launcher.py        # 启动器
│   │   ├── tmux_control.py    # Tmux 管理
│   │   ├── data_store.py      # 数据持久化
│   │   ├── models.py          # 数据模型
│   │   ├── tabs/              # 终端发现、跳转、work-status
│   │   └── terminal/          # 终端适配器
│   ├── tests/
│   ├── pyproject.toml
│   └── watch_logs.sh
│
├── tools/
│   ├── ai-run                  # 按会话选择 skill / MCP
│   ├── jev / jev-hook           # Jev 开关与 Hook 管理
│   ├── jev-dispatch / jev-execute # 输入分派与执行
│   ├── jev-run                  # 委派任务登记、检查与审核
│   └── jev-delegation/          # 手动调用的委派 skill
│
├── docs/
│   └── jev-router.md            # Jev 安装与使用
│
├── kitty-enhance/              # Kitty 优化工具集 ⭐
│   ├── config/
│   │   ├── kitty/             # Kitty 配置
│   │   │   ├── kitty.conf     # 主配置（性能优化 + 快捷键）
│   │   │   ├── theme.conf     # 1984 Dark 主题
│   │   │   └── README.md
│   │   └── tmux/              # Tmux 配置
│   │       ├── tmux.conf      # Vi 风格 + 鼠标翻页
│   │       └── README.md
│   ├── scripts/                # Kitty 辅助脚本
│   │   ├── rename-tab.sh
│   │   ├── quick-rename-tab.sh
│   │   ├── ai-tab-title-monitor.py # Tab 标题跟随 AI 窗口
│   │   ├── codex-event-monitor.py  # Codex 会话事件监控
│   │   ├── session-snapshot.py     # 保存 / 恢复 Kitty 会话
│   │   ├── session-backup.py       # systemd 周期备份
│   │   ├── codex-working.sh        # Codex 运行状态色
│   │   └── codex-completed.sh      # Codex 完成 Tab 变红
│   ├── hooks/                  # Claude Code Hooks
│   │   ├── on-tool-use.sh      # 工具调用时更新运行状态色
│   │   ├── on-user-prompt.sh   # 提交 prompt 时登记任务摘要
│   │   ├── on-stop.sh          # 完成时 Tab 变红 + 通知
│   │   ├── on-notify.sh        # 通知处理
│   │   ├── on-permission-pending.sh # 权限弹窗记录（飞书桥接）
│   │   ├── feishu-register.sh  # 终端注册公共函数（被各 Hook source）
│   │   └── tab-color-common.sh # 共享颜色管理
│   ├── feishu-bridge/           # 飞书终端管理中心
│   │   ├── daemon.py            # 守护进程（权限通知 + 终端管理 + API 轮询）
│   │   ├── feishu_client.py     # 飞书 API 封装（卡片/文本/消息拉取）
│   │   ├── command_handler.py   # 飞书指令解析（ls/#N/y/n 等）
│   │   ├── terminal_registry.py # 终端注册表（多 Kitty 实例发现与管理）
│   │   ├── kitty_responder.py   # Kitty 终端交互（按键/屏幕抓取/清屏）
│   │   ├── config.yaml          # 配置（需填入凭据）
│   │   ├── config_example.yaml  # 配置模板
│   │   └── requirements.txt     # Python 依赖
│   ├── shell-functions.sh      # Tab 管理 Shell 函数
│   ├── install.sh              # 一键安装脚本
│   ├── install-codex-yolo.sh    # Codex 独立启动器安装
│   ├── uninstall.sh            # 卸载脚本
│   ├── KITTY_SETUP.md          # 详细设置指南
│   └── COLOR_SCHEME.md         # 颜色方案文档
│
├── .gitignore                  # Git 忽略规则
├── CLAUDE.md                   # 项目规范
└── README.md                   # 本文件
```

---

## License

MIT
