# Claude Manager

基于 Kitty 终端的轻量级任务管理器，专为 Claude Code 和 ROS2 开发工作流设计。

## 功能特性

- **任务管理**: 创建、追踪、管理开发任务
- **多终端支持**: 同时管理多个终端窗口（Claude、Shell、ROS2 等）
- **状态检测**: 自动检测 Claude 任务状态（运行中/已完成/等待确认）
- **布局预设**: 一键切换专注/开发/测试/监控模式
- **Kitty + Tmux 集成**: 深度集成 Kitty Remote Control 和 Tmux

## 快速安装

本节快速开始，详细步骤见下方"使用方式"章节

---

## 使用方式

本仓库提供 **两种** 使用方式，可根据需求选择：

### 方式一：Kitty 优化 ⭐（推荐快速开始）

**适用场景**：日常 Claude Code 开发，需要自动状态提示和快速 Tab 管理

**特点**：
- ✅ 轻量化（仅需 Kitty 配置 + Shell 函数）
- ✅ Claude 工作状态自动显示（Tab 变色：蓝→红→自动恢复）
- ✅ Tab 快速管理（`tab-rename`, `tab-project`, `tab-alert` 等）
- ✅ 无需 Tmux，直接在 Kitty 中使用

**安装**：
```bash
cd kitty-enhance && ./install.sh
```

⚠️ **配置改变**（仅 Kitty 相关）：
- 复制配置到 `~/.config/kitty/`（主配置、主题、脚本）
- 添加 Shell 函数到 `~/.bashrc` / `~/.zshrc`
- 添加 Claude Code Hook 到 `~/.claude/hooks/`

**使配置生效**：
```bash
# 重新加载 Kitty 配置（无需重启）
kitty +kitten @ load-config --to unix:@mykitty

# 重新加载 Shell 配置
source ~/.bashrc  # 或 source ~/.zshrc
```

**快速命令**（详见下方快捷键说明）：
```bash
tr / tab-rename    # 重命名 Tab
tp / tab-project   # 自动项目名 + 分支
ta / tab-alert     # 标记为红色
```

详细说明：见 [Kitty 增强功能](#kitty-增强功能-) 章节

---

### 方式二：Claude Manager TUI（功能完整）

⚠️ **当前状态**：此方案仍在开发中，**不建议用于生产环境**。建议使用方式一（Kitty 优化）进行日常开发。

**适用场景**：复杂多任务开发（ROS2、多项目并行）、需要集中管理多个 Claude 会话

**特点**：
- ✅ TUI 任务管理面板（创建/删除/切换任务）
- ✅ 自动任务状态检测（运行中/已完成）
- ✅ Tmux 深度集成（分屏管理、窗口布局）
- ✅ 布局预设快捷键（专注/开发/测试/监控模式）
- ✅ 结合 Kitty 优化 + Tmux 优化 + Claude Manager

**前置要求**：
- 已安装 Kitty 优化（方式一）
- Tmux 2.4+ 已安装

**安装**：
```bash
pip install -e manager/
```

⚠️ **配置改变**（Tmux + TUI 相关）：
- 复制 `~/.tmux.conf`（Tmux 优化配置）
- 保存任务数据到 `~/.local/share/claude-manager/`
- 保存配置到 `~/.config/claude-manager/`

**启动**：
```bash
# 启动 TUI 管理器（自动创建分屏）
claude-manager

# 查看环境配置
claude-manager --check

# 启用调试面板
claude-manager --debug
```

**快速键**（详见下方 TUI 快捷键说明）：
- `n` - 新建任务
- `Enter` - 激活任务
- `1-5` - 快速切换

详细说明：见 [Claude Manager 使用](#claude-manager-使用) 章节

---

## 依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 运行环境 |
| Kitty | - | 终端模拟器 |
| Tmux | 2.4+ | 会话管理 |
| textual | >= 0.40.0 | TUI 框架 |
| psutil | >= 5.9.0 | 进程监控 |
| pyyaml | >= 6.0 | 配置解析 |
| xclip | - | 剪贴板支持（可选） |

安装依赖：

```bash
# Ubuntu/Debian
sudo apt install kitty tmux xclip

# Python 依赖
pip install -e .
```

---

## 终端配置详解

### Kitty 配置

配置文件：`config/kitty/`

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

#### Kitty 增强功能 ⭐

**Claude Code 自动状态提示**

Claude Manager 集成了 Claude Code Hooks，自动管理 Tab 颜色显示任务状态：

```
思考中      调用工具      询问确认      完成后
（未配）      ↓            ↓            ↓
⚪ 白色    🔵 蓝色      🟡 黄色      🔴 红色
                      （非聚焦）    （非聚焦）
                                      ↓
                                  切换到 Tab
                                      ↓
                                  ⚪ 3秒后恢复
```

**工作流程**：
- **思考阶段**：白色（暂无专门 Hook）
- `on-tool-use.sh`：调用工具时 → 蓝色（非聚焦显示）
- `on-notify.sh`：需要确认时 → 黄色（权限对话框、输入确认等）
- `on-stop.sh`：完成回答时 → 红色（非聚焦显示）
- **自动恢复**：切换到该 Tab 后 3 秒自动恢复原色

**Tab 管理命令**

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

**安装增强功能**

增强功能已包含在 `kitty-enhance/` 中，通过一键安装脚本配置：

```bash
cd kitty-enhance && ./install.sh    # 配置 hooks 和 shell 函数
```

安装内容：
- ✅ 复制 Kitty 配置到 `~/.config/kitty/`
- ✅ 复制优化脚本到 `~/.config/kitty/scripts/`
- ✅ 配置 Claude Code Hooks 到 `~/.claude/hooks/`
- ✅ 添加 Shell 函数到 `.bashrc`/`.zshrc`

**安装后使配置生效**：
```bash
kitty +kitten @ load-config --to unix:@mykitty
source ~/.bashrc
```

**故障排查**

如果 Tab 没有变色或自动恢复不工作：

```bash
# 1. 检查 Hook 是否安装
ls -l ~/.claude/hooks/

# 2. 检查 Shell 函数是否加载
which tab-rename

# 3. 启用调试日志
export CLAUDE_HOOK_DEBUG=1

# 4. 查看日志
tail -f /tmp/claude-hook.log

# 5. 验证 Kitty Remote Control
kitty @ ls
```

---

### 飞书终端管理中心（Feishu Terminal Hub）

通过飞书远程管理所有 Claude Code 终端：权限审批、进度查看、远程指令。

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
│  Claude 完成回答 → 飞书推送对话内容                   │
└───────────────────────────────────────────────────────┘
```

**消息通道**：WebSocket 长连接 + API 轮询双通道，消息延迟 ~2 秒（WebSocket 固有延迟 ~15 秒，API 轮询兜底）。

#### 飞书指令速查

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

#### 前置条件

1. Kitty 终端（已启用 `allow_remote_control`）
2. Python 3.10+ 与 `lark-oapi` 依赖
3. 飞书自建应用（见下方配置步骤）

#### 飞书应用配置

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

#### 安装与配置

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

#### 使用

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
- **完成通知**：Claude 完成回答后推送对话内容到飞书
- **终端管理**：随时发送 `ls` 查看所有终端，`#N 进度` 查看屏幕

#### 终端自动注册

终端通过两种方式注册到管理中心：

1. **Hook 实时注册**（推荐）：Claude Code Hook 在工具调用、完成、权限弹窗时自动注册终端状态
2. **定期扫描**：守护进程定期扫描所有 Kitty 实例，发现运行 Claude 的窗口自动注册

#### 新用户接入（一键配置）

飞书应用只需创建一次，团队共用同一个 App ID / App Secret。新用户接入只需：

```bash
cd kitty-enhance/feishu-bridge
bash setup.sh
```

脚本会自动：检查依赖 → 填入共享凭据 → 连接飞书获取个人 open_id → 生成 config.yaml → 安装 Hook。

新用户需要的信息（问管理员要）：
- **App ID** 和 **App Secret** — 团队共用
- 飞书中搜索机器人名字，发一条消息 — 脚本自动获取 open_id

#### 首次建立长连接

飞书后台保存「长连接」配置时要求客户端已连接。首次配置时先启动守护进程（`python daemon.py`），再去飞书后台点「保存」。

---

### Tmux 配置

配置文件：`config/tmux/`

| 文件 | 说明 |
|------|------|
| `tmux.conf` | 主配置 |
| `install.sh` | 一键安装脚本 |
| `README.md` | 快捷键文档 |

#### Tmux 快捷键

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

#### 鼠标滚轮翻页 ⭐

| 操作 | 效果 | 说明 |
|------|------|------|
| 滚轮向上 | 进入 copy-mode | 开始翻看历史输出 |
| 继续滚动 | 翻页 | 可以一直往上翻 |
| **打字** | **自动退出，正常输入** | 无需手动退出 |
| `q` / `Escape` | 退出 copy-mode | 手动退出 |

#### Copy-mode（Vi 风格）

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| `v` | 开始选择 | 进入选择模式 |
| `y` | 复制并退出 | 复制选中内容到 tmux 缓冲区 |
| `/` | 搜索 | 输入关键词搜索 |
| `n` | 下一个匹配 | 跳到下一个搜索结果 |
| `N` | 上一个匹配 | 跳到上一个搜索结果 |
| `PageUp/Down` | 翻页 | 快速翻页 |
| 鼠标拖选 | 选择并复制 | 自动复制到系统剪贴板 |

#### Tmux 常用命令

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

## Claude Manager 使用

⚠️ **注意**：Claude Manager TUI 方案仍在优化中，推荐优先使用 [方式一：Kitty 优化](#方式一kitty-优化-推荐快速开始) 进行日常开发。

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

位置：`~/.config/claude-manager/claude_env.conf`

```bash
ANTHROPIC_BASE_URL=http://localhost:3000/api
ANTHROPIC_AUTH_TOKEN=your_token_here
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
pip install -e ".[dev]"

# 运行测试
pytest

# 查看日志
tail -f ~/.config/claude-manager/logs/app.log
```

---

## 项目结构

```
.
├── manager/                    # TUI 任务管理器
│   ├── src/claude_manager/
│   │   ├── app.py             # TUI 主逻辑
│   │   ├── cli.py             # 命令行入口
│   │   ├── launcher.py        # 启动器
│   │   ├── tmux_control.py    # Tmux 管理
│   │   ├── data_store.py      # 数据持久化
│   │   ├── models.py          # 数据模型
│   │   └── terminal/          # 终端适配器
│   ├── tests/
│   ├── pyproject.toml
│   └── watch_logs.sh
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
│   │   └── quick-rename-tab.sh
│   ├── hooks/                  # Claude Code Hooks
│   │   ├── on-tool-use.sh      # 工具调用时 Tab 变蓝
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
│   ├── uninstall.sh            # 卸载脚本
│   ├── KITTY_SETUP.md          # 详细设置指南
│   └── COLOR_SCHEME.md         # 颜色方案文档
│
├── COMMANDS.md                 # 命令速查
├── CLAUDE.md                   # 项目规范
└── README.md                   # 本文件
```

---

## License

MIT
