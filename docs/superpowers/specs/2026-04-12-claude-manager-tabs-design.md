# claude-manager tabs 子命令设计

**日期**：2026-04-12  
**状态**：草案（待评审）  
**作者**：Claude + 用户协作设计

## 背景与动机

当用户在多个 kitty tab 中同时运行 Claude/Codex 时，会遇到两个实际问题：

1. **难以定位**：忘了某个任务打开在哪个 tab 里，需要手动翻 tab 寻找。
2. **缺少全局视图**：没有一个地方能集中看到"当前我有哪些 AI 终端在跑、它们各自在忙什么"。

`claude-manager` 虽名为"manager"，但目前只管理通过 TUI 创建的任务（走 tmux session）。对于用户在日常工作中直接用 `kitty tab → claude` 随手开的终端，claude-manager 完全看不到。这是一个明显的功能缺口。

## 已有基础设施

项目里 `kitty-enhance/feishu-bridge/` 模块已经实现了一套"终端注册表"机制：

- Claude Code 的 hook（`on-tool-use.sh`、`on-stop.sh`、`on-permission-pending.sh`）在触发时会 source `feishu-register.sh`
- `_feishu_register` 函数将当前 kitty window 的信息写入 `/tmp/feishu-bridge/registry.json`，包含：window_id、kitty_socket、tab_title、cwd、status、agent_kind、last_activity、registered_at
- 这份 registry 原本设计用于让 feishu-bridge 的 daemon 发飞书通知

经实测：feishu-bridge 的 daemon 进程**从未启动过**，配置文件的飞书凭据为空，但 hook 本身在正常工作——`registry.json` 实时反映着当前的 Claude/Codex 终端。

这意味着**数据源已经具备**，只是缺少一个能读它、展示它、跳转到它的消费者。

## 设计原则

1. **共享契约**：`/tmp/feishu-bridge/registry.json` 的路径和 schema 保持不变，作为 claude-manager 和未来恢复的 feishu-bridge 之间隐式的接口。
2. **零改动 hooks 和 feishu-bridge**：不动现有注册脚本，不动 feishu-bridge 目录。用户将来想启用 feishu-bridge 时无需任何额外迁移。
3. **YAGNI**：只做 MVP 所需的 list + focus。不做 tag、description、kill、log、模糊匹配等次要功能。
4. **活性优先**：显示的列表必须反映**当前实际存在**的终端，不显示陈旧记录。

## 架构

```
┌─────────────────────────────────────────────────────┐
│ Claude Code 工具调用                                │
└─────────────────┬───────────────────────────────────┘
                  │ hook 事件
                  ▼
┌─────────────────────────────────────────────────────┐
│ kitty-enhance/hooks/on-tool-use.sh 等（不动）       │
│   source feishu-register.sh → _feishu_register      │
└─────────────────┬───────────────────────────────────┘
                  │ 写入
                  ▼
┌─────────────────────────────────────────────────────┐
│ /tmp/feishu-bridge/registry.json（共享契约）        │
│   键: window_id                                     │
│   值: {socket, tab_title, cwd, status,              │
│        agent_kind, last_activity, registered_at}    │
└─────────────────┬─────────────────┬─────────────────┘
                  │                 │
                  │ 读               │ 未来恢复后读
                  ▼                 ▼
   ┌──────────────────────┐  ┌─────────────────────┐
   │ claude-manager tabs  │  │ feishu-bridge       │
   │ list / focus         │  │ daemon（休眠中）    │
   └──────────────────────┘  └─────────────────────┘
```

## 模块布局

新增代码集中在一个独立子包内：

```
manager/src/claude_manager/
├── tabs/                        ← 新模块
│   ├── __init__.py
│   ├── cli.py                   ← argparse 子命令（list / focus）
│   ├── registry.py              ← 读 registry.json + 活性过滤
│   └── kitty.py                 ← 调用 kitty @ focus-window
└── cli.py                       ← 主入口，增加 "tabs" 子命令分支
```

### 各文件职责

**`tabs/registry.py`**（~60 行）
- `load_registry() -> dict[str, dict]`：从 `/tmp/feishu-bridge/registry.json` 读取原始数据。文件不存在或损坏时返回空字典。
- `list_alive_terminals() -> list[TerminalInfo]`：读 + 活性过滤 + 按 `last_activity` 倒序排序。
- 内部辅助：`_get_alive_windows(socket: str) -> dict[str, dict]`，对单个 socket 调 `kitty @ --to <socket> ls`，返回 `{window_id: {tab_title, cwd}}`。既用于活性过滤，也顺手拿到**实时的** tab_title（避免显示 hook 注册时的陈旧标题）。

**`tabs/kitty.py`**（~40 行）
- `focus_window(socket: str, window_id: str) -> bool`：执行 `kitty @ --to <socket> focus-window --match id:<window_id>`。返回是否成功，不抛异常。
- 单一职责，易于单元测试（mock subprocess）。

**`tabs/cli.py`**（~80 行）
- 定义 `tabs` 子命令树：
  - `tabs list [--active] [--json]`
  - `tabs focus <window_id>`
- 用 `rich.Table` 渲染表格输出
- 入口函数 `run(argv: list[str]) -> int`，供主 `cli.py` 调用

**`cli.py`**（主入口，改动约 10 行）
- 检测 `sys.argv[1] == "tabs"` 时，调用 `claude_manager.tabs.cli.run(sys.argv[2:])` 并退出
- 不进入 TUI 启动逻辑，不进行"在 tmux 内拒绝启动"的检查
- 其他命令路径保持现状

## 数据模型

### 输入（外部 schema，不变）

`/tmp/feishu-bridge/registry.json`：

```json
{
  "42": {
    "window_id": "42",
    "kitty_socket": "unix:@mykitty-12345",
    "tab_title": "claude-manager",
    "cwd": "/home/qwer/code/claude-manager",
    "registered_at": 1712890000.0,
    "last_activity": 1712893500.0,
    "status": "working",
    "agent_kind": "claude",
    "agent_name": "Claude"
  }
}
```

### 内部模型

```python
from dataclasses import dataclass
from pathlib import Path
import time

@dataclass(frozen=True)
class TerminalInfo:
    window_id: str
    socket: str
    tab_title: str
    cwd: str
    status: str          # "working" / "waiting" / "completed" / "idle"
    agent_kind: str      # "claude" / "codex"
    last_activity: float
    registered_at: float

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    @property
    def project_name(self) -> str:
        return Path(self.cwd).name or self.cwd
```

`frozen=True`：`TerminalInfo` 是 registry 的只读快照，构造后不应修改。

### 活性过滤流程

`list_alive_terminals()` 的执行步骤：

1. 读 `registry.json`，得到全部原始 entries
2. 按 `kitty_socket` 分组：`dict[socket, list[raw_entry]]`
3. 对每个 socket 调一次 `kitty @ --to <socket> ls`，解析 JSON，得到 `live_windows: dict[window_id, {tab_title, cwd}]`
4. 过滤：只保留 `window_id in live_windows` 的 entries
5. 构造 `TerminalInfo` 对象时，`tab_title` 优先用 `live_windows[wid]['tab_title']`（实时），fallback 用 registry 的值
6. 按 `last_activity` 倒序返回

## CLI 用户体验

### `claude-manager tabs list`

默认展示所有活跃的终端（含 completed 状态）：

```
$ claude-manager tabs list
ID   TAB              PROJECT               AGENT   STATUS    IDLE
42   claude-manager   claude-manager        claude  working   刚刚
18   uwb_driver       uwb_driver            claude  waiting   3分钟前
12   experiments      experiments           codex   idle      12分钟前

共 3 个活跃终端
```

**列含义**：

| 列 | 来源 | 说明 |
|----|------|------|
| `ID` | `window_id` | kitty window 的数字 ID，`focus` 命令使用 |
| `TAB` | `tab_title` | hook 注册时的 tab 标题 |
| `PROJECT` | `Path(cwd).name` | 工作目录的 basename，通常就是项目名 |
| `AGENT` | `agent_kind` | `claude` 或 `codex` |
| `STATUS` | `status` | `working`/`waiting`/`completed`/`idle`，支持上色 |
| `IDLE` | `time.time() - last_activity` | 格式化为"刚刚"/"N 分钟前"/"N 小时前" |

**STATUS 颜色方案**（复用 `feishu-bridge/terminal_registry.py::STATUS_ICON` 的含义）：
- `working` → 绿色
- `waiting` → 黄色
- `completed` → 红色
- `idle` → 灰色

**选项**：
- `--active`：过滤掉 `completed` 和 `idle`，只显示 `working` / `waiting`
- `--json`：输出机器可读的 JSON 格式，方便脚本化（`[{window_id, tab_title, ...}, ...]`）

**空列表场景**：

```
$ claude-manager tabs list
没有活跃的终端。

提示：
- 确认 kitty hook 已经安装（在 kitty tab 里运行 claude 后会自动注册）
- 注册数据位于 /tmp/feishu-bridge/registry.json
```

### `claude-manager tabs focus <id>`

```
$ claude-manager tabs focus 18
切换到 "uwb_driver"（window_id=18, socket=unix:@mykitty-12345）
```

命令返回后，kitty 应该已经把焦点切到对应的 tab + window。

**错误提示**：

```
$ claude-manager tabs focus 99
错误: 未找到 window_id=99 的终端。

当前活跃的终端:
  42   claude-manager
  18   uwb_driver
  12   experiments
```

退出码非零。

### MVP 明确不做的

- **模糊匹配**：`focus uwb` 匹配 tab_title。留到 v2。
- **标签/描述**：`tag` / `rename` 命令。
- **日志查看**：`log <id>` 抓取屏幕内容。
- **新建终端**：`open <project>` 起新 tab 并自动启 claude。
- **关闭终端**：`kill <id>`。

## 错误处理与边界情况

| 场景 | 行为 |
|------|------|
| `registry.json` 不存在 | `list` 输出友好空提示；`focus` 报 "未找到" 并退出码非零 |
| `registry.json` JSON 损坏 | 记录日志，视为空；不抛异常 |
| `kitty @ ls` 超时（5 秒上限） | 该 socket 下所有 entries 跳过（视为死亡） |
| `kitty @ focus-window` 非零退出 | 打印 stderr 到终端；`focus` 命令退出码非零 |
| 多个 kitty 实例同时存在 | 按 socket 分组查询，合并结果 |
| 同一 project 下多个 tab | 正常显示为多行；用 `ID` 区分 |
| registry 中某 window_id 陈旧（tab 已关闭） | 活性过滤剔除 |
| hook 从未触发过某个 tab | 该 tab 不出现在列表——这是预期行为（用户尚未在里面运行 Claude） |
| 命令在 tmux 会话内执行 | 正常工作。`tabs` 子命令**不进入 TUI 启动流程**，绕过 `launcher.py` 的 tmux 检查 |

**关键约束**：`tabs` 子命令必须在主 `cli.py` 入口处尽早分流，**早于**任何"tmux 内拒绝启动"的检查。

## 测试策略

### 单元测试

| 测试对象 | 方法 |
|---------|------|
| `registry.py::load_registry` | 用 `tmp_path` fixture 写假 registry.json，断言解析结果 |
| `registry.py::list_alive_terminals` | mock `subprocess.run` 返回假 `kitty @ ls` 输出，验证活性过滤 |
| `kitty.py::focus_window` | mock `subprocess.run`，断言命令行参数正确、成功/失败路径都覆盖 |
| `cli.py` | 集成测试：用 `capsys` 捕获输出，断言表格格式、空列表提示、错误提示 |

测试文件：`manager/tests/test_tabs.py`，~150 行。

### 手工验收

1. 在几个 kitty tab 中分别启动 `claude` 和 `codex`
2. 让它们各自触发一次工具调用（触发 hook 写入 registry）
3. 运行 `claude-manager tabs list`，确认所有活跃终端可见
4. 关闭其中一个 tab，再次运行 `list`，确认它消失
5. 运行 `claude-manager tabs focus <id>`，确认 kitty 焦点切换到目标 tab
6. 运行 `claude-manager tabs focus 9999`（不存在），确认错误提示和非零退出码
7. 运行 `claude-manager tabs list --active`，确认只显示 working/waiting
8. 运行 `claude-manager tabs list --json`，确认输出 JSON 可被 `jq` 解析
9. 在一个 tmux 会话里运行 `claude-manager tabs list`，确认不被 launcher 的 tmux 检查拒绝

## 对现有代码的影响

**新增**：
- `manager/src/claude_manager/tabs/` 子包（~180 行）
- `manager/tests/test_tabs.py`（~150 行）

**修改**：
- `manager/src/claude_manager/cli.py`：在入口分流 `tabs` 子命令（~10 行）

**不动**：
- `kitty-enhance/hooks/`：任何 hook 脚本
- `kitty-enhance/feishu-bridge/`：整个目录
- `/tmp/feishu-bridge/registry.json`：路径和 schema

## 未来扩展路径

如果将来需要添加下述功能，以下是建议的演进方向：

- **tag / description**：新增 `~/.local/share/claude-manager/tab_annotations.json` 覆盖层，以 `cwd + agent_kind` 为键存储人工标注。`tabs list` 在渲染时 JOIN 两份数据。
- **web dashboard**：把 `tabs/registry.py` 包成 HTTP endpoint（FastAPI 或轻量 wsgi），前端消费同一份 `TerminalInfo` 数据结构。
- **kill / restart**：通过 kitty remote control 发送 `send-text` 或 `close-window`。
- **模糊匹配**：`focus` 接受 substring，用 `tab_title` / `project_name` 做 prefix match。

上述扩展不会影响 MVP 的核心数据通路，因为 registry 读取路径保持不变，新功能都是在 CLI 层或新数据文件层叠加。
