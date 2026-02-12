# Kitty 优化设置指南

## 概述

Claude Manager 提供完整的 Kitty 终端优化方案，包括：

- **性能优化配置** - FPS、延迟、缓冲调优
- **Tab 管理脚本** - 快速重命名、颜色标记
- **Claude Code 集成** - 任务完成自动提示
- **Shell 函数集** - 便捷的命令行工具

## 快速安装

```bash
cd /mnt/data/claude-manager
./install-kitty.sh
```

安装完成后：
1. **重启 Kitty 终端**
2. **重新加载 Shell 配置**：`source ~/.bashrc` 或 `source ~/.zshrc`

## 功能详解

### 1. Tab 颜色标记

当 Claude Code 完成任务时：

```
┌────────────────────────┐
│ 🔴 Tab 自动变红        │ ← Claude 完成，需要查看
│ 📢 桌面通知            │
│ 🔔 终端响铃            │
└────────────────────────┘
           ↓
    切换到该 Tab
           ↓
┌────────────────────────┐
│ ⚪ Tab 颜色重置        │ ← 3 秒后自动恢复
└────────────────────────┘
```

**工作原理**：
- Hook 在 Claude 完成时触发（`~/.claude/hooks/on-stop.sh`）
- 当前 tab 变红（活跃：红色，非活跃：深红）
- 后台轮询检测 tab 是否被选中
- 选中后等待 3 秒，然后重置颜色

### 2. Tab 管理命令

#### 完整重命名（含 git 分支）
```bash
tab-rename          # 或 tr
# 交互式输入名称，自动检测 git 分支
# 格式：NAME [DIR:BRANCH] | DESC
```

#### 快速重命名
```bash
tab-quick           # 或 tq
# 仅输入名称，快速重命名
```

#### 自动项目检测
```bash
tab-project         # 或 tp
# 自动使用当前目录名 + git 分支
```

#### 颜色标记
```bash
tab-alert           # 或 ta - 红色（需要注意）
tab-warning         # 黄色（警告）
tab-done            # 绿色（完成）
tab-reset           # 或 tc - 重置颜色
```

### 3. Kitty 配置优化

**性能参数**（`~/.config/kitty/kitty.conf`）：
```ini
# 性能优化
max_fps 60                # 限制刷新率
sync_to_monitor yes       # 垂直同步
input_delay 3             # 减少频繁处理
detect_urls no            # 禁用 URL 检测
scrollback_lines 500      # 减少滚动缓冲

# 远程控制（必需）
allow_remote_control yes
listen_on unix:@mykitty
```

**快捷键**（部分精选）：
| 快捷键 | 功能 |
|--------|------|
| `Alt+Enter` | 新建 tab |
| `Ctrl+←/→/↑/↓` | 方向切换窗口 |
| `Alt+←/→` | 前/后一个 tab |
| `Ctrl+Shift+←/→/↑/↓` | 调整窗口大小 |
| `Ctrl+Shift+e` | 选择布局 |

完整快捷键：参见 `config/kitty/README.md`

### 4. Shell 函数集

所有函数定义在 `shell-functions.sh`，包括：

```bash
# Tab 管理
tab-rename / tr        # 完整重命名
tab-quick / tq         # 快速重命名
tab-project / tp       # 自动项目名
tab-reset / tc         # 重置颜色
tab-alert / ta         # 红色标记

# 辅助函数
_kitty_socket          # 获取 socket 地址
```

## 调试

### 启用调试日志

```bash
export CLAUDE_HOOK_DEBUG=1
```

### 查看日志

```bash
tail -f /tmp/claude-hook.log
```

### 测试 Remote Control

```bash
# 测试基本功能
kitty @ ls

# 测试 socket 连接
kitty @ --to "unix:@mykitty-$KITTY_PID" ls
```

### 手动测试 Hook

```bash
echo '{"cwd": "/test"}' | ~/.claude/hooks/on-stop.sh
```

## 故障排查

### Tab 没有变红

**检查清单**：
1. Hook 是否安装？
   ```bash
   ls -l ~/.claude/hooks/on-stop.sh
   ```

2. Claude Code 配置是否正确？
   ```bash
   cat ~/.claude.json | grep onStop
   ```

3. Remote Control 是否启用？
   ```bash
   kitty @ ls
   ```

4. 环境变量是否存在？
   ```bash
   echo $KITTY_LISTEN_ON
   echo $KITTY_PID
   ```

### Tab 变红后不自动恢复

**可能原因**：
1. 后台轮询进程未启动
   ```bash
   ps aux | grep on-stop
   ```

2. Socket 地址不正确
   ```bash
   # 启用调试
   export CLAUDE_HOOK_DEBUG=1
   # 然后触发 Claude 完成，查看日志
   tail -f /tmp/claude-hook.log
   ```

3. 多个 Kitty 实例冲突
   ```bash
   # 查看所有 socket
   ss -lx | grep kitty
   ```

### Shell 函数不可用

```bash
# 检查是否已 source
grep "shell-functions.sh" ~/.bashrc

# 手动加载
source /mnt/data/claude-manager/shell-functions.sh

# 测试
tab-quick
```

## 手动安装（不使用脚本）

### 1. 安装 Kitty 配置

```bash
mkdir -p ~/.config/kitty
cp config/kitty/kitty.conf ~/.config/kitty/
cp config/kitty/theme.conf ~/.config/kitty/
```

### 2. 安装脚本

```bash
mkdir -p ~/.config/kitty/scripts
cp kitty-scripts/*.sh ~/.config/kitty/scripts/
chmod +x ~/.config/kitty/scripts/*.sh
```

### 3. 安装 Shell 函数

```bash
# 添加到 .bashrc 或 .zshrc
echo 'source /mnt/data/claude-manager/shell-functions.sh' >> ~/.bashrc
source ~/.bashrc
```

### 4. 安装 Hook

```bash
mkdir -p ~/.claude/hooks
ln -sf "$(pwd)/claude-hooks/on-stop.sh" ~/.claude/hooks/on-stop.sh
```

### 5. 配置 Claude Code

编辑 `~/.claude.json`：
```json
{
  "hooks": {
    "onStop": "~/.claude/hooks/on-stop.sh"
  }
}
```

## 卸载

```bash
# 删除配置
rm -rf ~/.config/kitty/kitty.conf.bak.*
rm ~/.config/kitty/theme.conf

# 删除脚本
rm -rf ~/.config/kitty/scripts

# 删除 hook
rm ~/.claude/hooks/on-stop.sh

# 从 .bashrc/.zshrc 移除
# 手动编辑删除 shell-functions.sh 相关行
```

## 依赖

- **Kitty** - 终端模拟器
- **Python 3** - Hook 脚本
- **jq** - JSON 处理（可选，用于通知）

## 许可

MIT License

## 相关文档

- [COMMANDS.md](COMMANDS.md) - 命令速查
- [config/kitty/README.md](config/kitty/README.md) - Kitty 配置详解
- [CLAUDE.md](CLAUDE.md) - 项目指南
