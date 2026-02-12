# Kitty 终端配置

高性能配置 + 远程控制 + 分屏管理

## 一键安装

```bash
/mnt/data/claude-manager/config/kitty/install.sh
```

安装后需要**重启 Kitty** 或新开标签页生效。

## 快捷键速查

### 窗口/标签创建

| 快捷键 | 功能 |
|--------|------|
| `Alt+Enter` | 新建标签 |
| `Alt+n` | 新建 OS 窗口 |
| `Ctrl+Enter` | 在当前目录新建窗口 |

### 窗口切换

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+←/→/↑/↓` | 切换到相邻窗口 |
| `Ctrl+Shift+←/→/↑/↓` | 调整窗口大小 |
| `Ctrl+Shift+e` | 选择布局 |
| `Cmd+Shift+l` | 下一个布局 |

### 标签切换

| 快捷键 | 功能 |
|--------|------|
| `Alt+←` | 上一个标签 |
| `Alt+→` | 下一个标签 |
| `Alt+↑` | 标签左移 |
| `Alt+↓` | 标签右移 |

### 通用操作

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+w` | 关闭窗口 |
| `Ctrl+Shift+f` | 全屏切换 |
| `Ctrl+Shift+c` | 复制 |
| `Ctrl+Shift+v` | 粘贴 |
| `Ctrl+Shift+=` | 放大字体 |
| `Ctrl+Shift+-` | 缩小字体 |
| `Ctrl+Shift+Backspace` | 重置字体 |

## 配置特性

### 性能优化

- `max_fps 60`: 降低刷新率，减少 CPU 占用
- `sync_to_monitor yes`: 垂直同步，避免过度渲染
- `input_delay 3`: 适当延迟，减少频繁处理
- `detect_urls no`: 禁用 URL 检测，减少扫描开销
- `scrollback_lines 500`: 减少滚动缓冲，节省内存

### 远程控制

配置已启用 `allow_remote_control`，支持 `kitty @` 命令：

```bash
# 列出所有窗口
kitty @ ls

# 在当前标签新建窗口
kitty @ launch --cwd=current

# 发送文本到窗口
kitty @ send-text --match id:1 "echo hello"
```

### 布局模式

支持三种布局：
- `tall`: 主窗口在左，其他在右侧堆叠
- `stack`: 全部堆叠，一次显示一个
- `grid`: 网格布局

按 `Ctrl+Shift+e` 选择布局。

## 主题

默认使用 1984 Dark 主题（深蓝色背景）。

如需切换主题，编辑 `theme.conf` 或使用 kitty 内置主题：

```bash
kitty +kitten themes
```

## 依赖

- Kitty >= 0.26.0
- JetBrainsMono Nerd Font（可选，会回退到系统字体）

安装字体：
```bash
# Ubuntu/Debian
sudo apt install fonts-jetbrains-mono

# 或下载 Nerd Font 版本
# https://www.nerdfonts.com/font-downloads
```

## 文件结构

```
~/.config/kitty/
├── kitty.conf    # 主配置
└── theme.conf    # 主题颜色
```
