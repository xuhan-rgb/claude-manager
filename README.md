# Claude Manager

基于 Kitty 终端的轻量级任务管理器，专为 Claude Code 和 ROS2 开发工作流设计。

## 功能特性

- **任务管理**: 创建、追踪、管理开发任务
- **多终端支持**: 同时管理多个终端窗口（Claude、Shell、ROS2 等）
- **状态检测**: 自动检测 Claude 任务状态（运行中/已完成/等待确认）
- **布局预设**: 一键切换专注/开发/测试/监控模式
- **Kitty + Tmux 集成**: 深度集成 Kitty Remote Control 和 Tmux

## 快速开始

### 1. 一键配置终端环境

```bash
# 安装 Kitty 配置（高性能 + 远程控制）
/mnt/data/claude-manager/config/kitty/install.sh

# 安装 Tmux 配置（Vi 风格 + 鼠标翻页）
/mnt/data/claude-manager/config/tmux/install.sh
```

> 安装后需要**重启 Kitty** 使配置生效

### 2. 安装 Claude Manager

```bash
cd /mnt/data/claude-manager
pip install -e .
```

### 3. 启动

```bash
claude-manager
```

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
/mnt/data/claude-manager/
├── config/
│   ├── kitty/            # Kitty 终端配置
│   │   ├── kitty.conf
│   │   ├── theme.conf
│   │   ├── install.sh
│   │   └── README.md
│   ├── tmux/             # Tmux 配置
│   │   ├── tmux.conf
│   │   ├── install.sh
│   │   └── README.md
│   └── layouts/          # 布局预设
├── src/claude_manager/
│   ├── app.py            # TUI 主逻辑
│   ├── cli.py            # 命令行入口
│   ├── launcher.py       # 启动器
│   ├── kitty_control.py  # Kitty API
│   ├── tmux_control.py   # Tmux 管理
│   ├── data_store.py     # 数据持久化
│   └── models.py         # 数据模型
├── tests/
├── pyproject.toml
└── README.md
```

---

## License

MIT
