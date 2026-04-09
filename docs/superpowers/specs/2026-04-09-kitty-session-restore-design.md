# Kitty Session 保存与恢复

## 概述

在 `kitty-enhance/shell-functions.sh` 中新增 4 个 shell 函数，实现 Kitty 终端会话的手动保存与恢复。保存时通过 `kitty @ ls` 获取完整终端状态，生成 Kitty 原生 session 文件；恢复时启动新 Kitty 实例加载该 session 文件。

## 命令接口

| 命令                    | 功能                     |
|-------------------------|--------------------------|
| `session-save <name>`   | 保存当前 Kitty 状态      |
| `session-restore <name>`| 启动新 Kitty 恢复 session |
| `session-list`          | 列出所有已保存 session   |
| `session-delete <name>` | 删除指定 session         |

别名：`ss` = `session-save`，`sr` = `session-restore`，`sl` = `session-list`。

## 文件布局

```
~/.config/kitty-enhance/sessions/
├── work.session        # Kitty session 文件（纯文本）
├── work.meta.json      # 元数据（保存时间、Tab 数量等）
├── debug.session
└── debug.meta.json
```

## 保存流程（session-save）

1. 调用 `kitty @ ls`（通过 `$KITTY_LISTEN_ON`）获取 JSON
2. Python 脚本解析 JSON，对每个 Tab 提取：
   - **Tab 标题**：`tab["title"]`
   - **布局**：`tab["layout"]`（tall/fat/grid/horizontal/vertical/splits/stack）
   - **每个 Window**：
     - 工作目录：`window["cwd"]`
     - 前台命令：`window["foreground_processes"][0]["cmdline"]`
3. 命令检测逻辑：
   - cmdline[0] 包含 `claude` → 记录为 `claude`（不保留 flags 如 `--dangerously-skip-permissions`）
   - cmdline[0] 是 shell（`bash`/`zsh`/`sh`/`fish`）→ 不写 `launch` 命令（session 文件默认开 shell）
   - 其他 → 记录完整 cmdline（如 `nautilus`、`htop`）
4. 生成 Kitty session 文件格式：

```
# Session: work | Saved: 2026-04-09 12:00:00 | Tabs: 7

new_tab Claude Code
layout tall
cd /mnt/data/claude-manager
launch claude
cd /home/qwer
launch --type=window bash
cd /home/qwer
launch --type=window bash

new_tab uwb
layout tall
cd /mnt/data/jszr_driver/uwb_driver
launch claude
cd /mnt/data/jszr_driver/uwb_driver
launch --type=window bash
```

5. 同时生成 `{name}.meta.json`：

```json
{
  "name": "work",
  "saved_at": "2026-04-09T12:00:00",
  "tabs": 7,
  "windows": 24
}
```

## 恢复流程（session-restore）

```bash
kitty --session ~/.config/kitty-enhance/sessions/{name}.session --detach
```

`--detach` 使新 Kitty 在后台启动，不阻塞当前 shell。

## 实现位置

所有代码在 `kitty-enhance/` 目录下：

- `kitty-enhance/shell-functions.sh`：追加 `session-save`、`session-restore`、`session-list`、`session-delete` 函数定义及别名
- `kitty-enhance/scripts/session-snapshot.py`：Python 脚本，接收 `kitty @ ls` JSON（stdin），输出 session 文件内容（stdout）

将解析逻辑放在独立 Python 脚本中，而非 shell 函数内嵌 heredoc，理由：
- JSON 解析和 session 文件生成逻辑有一定复杂度，Python 更适合
- 独立文件便于测试和维护

## 边界情况

- `kitty @ ls` 失败（Kitty Remote Control 未启用）→ 报错退出
- 同名 session 已存在 → 覆盖并提示
- `session-restore` 指定的 name 不存在 → 报错并执行 `session-list`
- Tab 标题包含特殊字符 → session 文件中保留原始标题（Kitty 支持 Unicode）
- Window 的 foreground_processes 为空 → 当作 shell 处理

## 不做的事

- 不保存终端滚动历史
- 不保存环境变量
- 不保存 window 精确尺寸（由 Kitty layout 自动分配）
- 不支持跨 OS window 保存（只保存当前 OS window）
- 不自动保存（只手动触发）
