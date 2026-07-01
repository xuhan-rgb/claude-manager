# dir-jump — 跨终端目录跳转

**日期**: 2026-05-14
**模块**: kitty-enhance

## 目标

热键唤起一个全屏 picker，列出当前所有 kitty window 的 cwd，**按最近活动时间倒序排列**，**上下箭头切换** 选中条目，Enter 聚焦到该 window。

**关键约束**：选中后是 **聚焦已有 window**（`kitten @ focus-window`），不是新开 —— 该 window 的 shell 历史、正在运行的命令、scrollback 全部保留，等同于用户手动点过去。用于快速回到某个目录翻文件而不破坏现场。

## 范围（非目标）

- 不内嵌文件浏览器 / 编辑器；选中后落回 shell，由用户自行 `ls` / `ranger` / `nvim`。
- 不收集 shell history、不扫描进程列表 —— 候选只来自实时 `kitten @ ls`。
- 不替代 `agent-terminals`：那个按 terminal_id 列出 Claude/Codex；这个按 cwd 列出所有 kitty window，覆盖范围互补。

## 架构

三个可独立测试的模块：

### 1. 数据采集 — `scripts/dir_collector.py`

```
collect_open_dirs() -> list[DirEntry]
```

- **Socket 发现**：
  1. 读 `/tmp/feishu-bridge/registry.json`，收集所有 `kitty_socket` 字段（去重）—— 这是已知的 kitty 实例集合
  2. 并入环境变量 `$KITTY_LISTEN_ON`（dir-jump 总是从 kitty 内部启动，肯定能拿到）—— 兜底覆盖没跑过 agent 的纯 shell kitty
  3. 对每个 socket 调 `kitten @ --to <socket> ls`，失败的 socket 跳过（说明 kitty 实例已经关了）
- 解析 JSON，从每个 `window.foreground_processes[0].cwd` 取 cwd
- 从每个 `window.foreground_processes[0].cwd` 提取 cwd（PID 为 shell 进程的最深前台进程）
- 按 cwd 聚合：同一个 cwd 在多个 window → 合并成一条，`window_refs` 列表保留所有 `(socket, window_id, tab_title)` 供选中后跳转
- 计算每条 entry 的 `last_activity`：
  - 优先从 `/tmp/feishu-bridge/registry.json` 取对应 `(window_id, socket)` 的 `last_activity`
  - 若该 window 没在 registry 里（纯 shell window），用 `window_id` 数值大小作 fallback（kitty window_id 单调递增，新建的更大）
- 同一 cwd 多 window：取所有 window 中最大的 `last_activity`

```python
@dataclass
class DirEntry:
    cwd: str
    window_refs: list[WindowRef]   # 至少一条
    last_activity: float           # epoch seconds (registry) 或 window_id 归一化 fallback
```

### 2. 排序 — `scripts/dir_jump.py`

```python
entries.sort(key=lambda e: -e.last_activity)
```

一行，不再拆独立函数。

### 3. UI + 跳转 — `scripts/dir_jump.py`

- 复用 `manager/src/claude_manager/tabs/interactive.py` 的 alt-screen / raw-mode / 上下箭头 / 斑马纹模板
- 列展示：`CWD`（带 `~` 缩写）、`TAB`（多个 window 时显示 `+N`）、`LAST`（人类可读 idle，如 `2m ago`）
- 选中 Enter → 调 `kitten @ --to <socket> focus-window --match id:<window_id>`（聚焦 `window_refs[0]`）

## 触发方式

`config/kitty/kitty.conf` 追加：

```
map ctrl+shift+d launch --type=overlay --cwd=current python3 ~/.local/share/kitty-enhance/scripts/dir_jump.py
```

`--type=overlay` 让 picker 浮在当前 window 上，退出后焦点自动回原 window —— 体感接近 Ghostty quake。

## 数据流

```
hotkey
  └─> dir_jump.py
       ├─> dir_collector.collect_open_dirs()
       │     ├─> kitten @ ls (每个 socket)
       │     └─> 读 registry.json 取 last_activity
       ├─> sort by last_activity desc
       ├─> interactive picker (alt screen)
       └─> on Enter: kitten @ focus-window
```

## 错误处理

- 没有活跃 kitty socket / 无候选：picker 打印 "no kitty windows" 后退出码 0
- `kitten @ ls` 在某个 socket 上失败：跳过该 socket，继续其他 socket，stderr 记一行
- registry.json 读失败：当作空，仅用 window_id fallback 排序

## 测试

- `dir_collector` 单元测试用 fixture JSON 模拟 `kitten @ ls` 输出 + 假 registry，验证聚合 + last_activity 计算
- UI 手测：装好后按热键，肉眼验证排序、上下箭头、跳转

## 文件清单

新增：
- `kitty-enhance/scripts/dir_collector.py`
- `kitty-enhance/scripts/dir_jump.py`
- `kitty-enhance/tests/test_dir_collector.py`

修改：
- `kitty-enhance/config/kitty/kitty.conf`（加 keymap）
- `kitty-enhance/install.sh`（拷 scripts）
- `kitty-enhance/CLAUDE.md`（增加 dir-jump 段落）

依赖：仅 Python 3.10+ 标准库（json / dataclasses / argparse / termios / tty）。
