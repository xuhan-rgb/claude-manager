# Jev 输入分派与执行

当前策略要求每条文字输入先经过一次 Jev 分类，包括问候和复杂问题。`UserPromptSubmit`
hook 只做分类并写入持久状态；它不伪造 hooks 信任，也不是宿主强制执行器。用户必须
在 `/hooks` 中手工确认信任，会话是否调用 dispatcher 仍遵循 hook 指令。

## 安装

需要 Python 3.10+、`uv`、`codex` CLI 和 TypeSafe API key；新的 dispatcher 不要求 Git。安装入口及既有路由器：

```bash
mkdir -p ~/.local/share/jev-router ~/.local/bin
uv venv ~/.local/share/jev-router/venv
uv pip install --python ~/.local/share/jev-router/venv/bin/python -r tools/requirements-jev.txt
cp tools/jev_settings.py tools/jev_hook_control.py tools/jev_dispatch.py tools/jev_state.py tools/jev_prompt_hook.py tools/jev_execute.py tools/jev_router.py ~/.local/share/jev-router/
cp tools/jev tools/jev-hook tools/jev-run tools/jev-dispatch tools/jev-execute ~/.local/bin/
chmod +x ~/.local/bin/jev ~/.local/bin/jev-hook ~/.local/bin/jev-run ~/.local/bin/jev-dispatch ~/.local/bin/jev-execute
mkdir -p ~/.agents/skills/jev-delegation
cp tools/jev-delegation/SKILL.md ~/.agents/skills/jev-delegation/
```

在 `~/.codex/hooks.json` 中合并以下定义，保留其他 hooks，并在 `/hooks` 中确认信任：

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "~/.local/share/jev-router/venv/bin/python ~/.local/share/jev-router/jev_prompt_hook.py",
        "timeout": 25,
        "statusMessage": "Jev 正在判断输入路由",
        "additionalContextLimit": 1500
      }]
    }]
  }
}
```

hook 输出状态
路径和明确命令 `jev-dispatch STATE.json`；不要把旧 `jev-chat` 作为新入口启用，也不
要伪造信任或声称已完成 UI 验证。

## 物理启停 hook

需要让 Codex 完全回到没有 Jev hook 的配置时，运行：

```bash
jev-hook off
```

它会从 `~/.codex/hooks.json` 移除 Jev 的 `UserPromptSubmit` 项，只保留其他 hook，
并将配置原子写回。`jev-hook on` 会重新安装 Jev hook；`jev-hook status` 显示实际
安装状态。修改后建议重新启动 Codex 会话，确保宿主重新读取配置；缓存中的旧 hook
也会通过本地开关立即空返回。

`jev-hook off` 只控制 hook 是否安装，不删除 skill、脚本或配置文件。详细 Jev 规则
通过 `jev-delegation` skill 手动调用，不写入全局 `AGENTS.md`。

## 统一热配置

统一入口是 `jev` 或 `jev status`，不带斜杠。终端命令已验证可执行。
Codex 输入框中的同名命令依赖已加载并信任的 UserPromptSubmit hook。
当前用户会话实际拒绝 `/prompts:jev`，因此不再安装或推荐该菜单入口；
不能把提示词展开的单元测试当成 TUI 命令注册成功的证据。

```text
jev on / jev off                Jev 总开关
jev entry on / jev entry off    输入路由开关
jev print on / jev print off    判断打印开关
jev status                     全部状态
```

配置集中保存在 `~/.config/jev-router/settings.json`，每次调用重新读取，后续判断立即
生效，无需重启；已开始的模型请求不会被取消。三个开关默认开启。总开关关闭不会
抹掉另外两个设置，重新开启会保留原值。

这些命令可以直接在终端执行；启用 hook 时，已信任的 UserPromptSubmit hook 也识别输入框中的
精确 `jev ...` 控制命令，执行后消费这条输入，不调用模型（宿主可能显示 hook 阻止
提交的提示，其中包含配置结果）。普通问题仍由 Jev 判断，不使用关键词捷径。

- 总开关 off：绕过整套 Jev 入口、分派、检查和审核流程；当前模型按普通任务规则决定执行、测试、委派与审核。尚未启动的 Luna 分派交回当前会话，已经开始的调用不取消。
- 输入路由 off：直接由当前模型接收输入，委派后 Jev 审核判断仍保留。
- 判断打印 off：隐藏问题、概率和最终选择，不改变路由，错误仍显示。

环境变量 `JEV_ENABLED`、`JEV_ENTRY`、`JEV_PRINT_JUDGMENTS` 的 0/1 值作为启动默认值；
持久热配置优先。hook 参数 `--print-judgments` / `--no-print-judgments` 可显式覆盖打印。
修改 hook 命令可能需重新信任；使用 `jev` 修改配置无需改 hook 定义。

## 输入分类

hook 每条输入调用一次 Jev，批量询问：

- `simple_request`：是否意图明确、范围有限，可由轻量模型完成；包括问候、简单答复和明确的局部实现；
- `coding_task`：是否需要处理代码、文件或使用工具。

只有 `simple_request >= .8` 且（`coding_task <= .2` 或 `coding_task >= .8`）才选择
独立 Luna；边界、不确定或 Jev/API 异常都选择 `current`。每个
`session_id`/`turn_id` 分类幂等，状态保存在 `~/.local/state/jev-router`。保存
`prompt`、`cwd`、概率、executor、结果和 checks，但状态输出不打印输入上下文。

普通问候也必须先分类；它不再绕过入口。简单非编码输入无需 Git 或任务 JSON，调用：

```bash
jev-dispatch /path/to/STATE.json
```

状态文件由 dispatcher 的原子文件锁防止重复执行。状态从 `luna_ready` 到
`luna_running`，最后为 `done` 或 `failed`；`current_required` 只返回当前会话的
决定。已 `done` 的状态只返回保存结果，不再次启动 Luna；中断的 `luna_running`
不会自动重跑，交由父会话处理。

## 简单请求与代码任务

简单请求由脚本启动独立 Luna `codex exec -m gpt-5.6-luna`，使用只读、无工具的
reply 指令，完成后直接交付，不再运行后验 Jev 或交给父模型审核。Luna 执行失败时
状态为 `failed`，由当前会话处理。这不是当前模型的原生子代理；复杂任务仍可由当前模型按运行时规则
使用原生 Luna 子代理。

若分类为代码任务，父会话先补齐 `scope`、`context` 和 `checks`，写成任务文件，
再复用已分类状态：

```bash
jev-dispatch /path/to/STATE.json --task-file /tmp/task.json \
  --sandbox workspace-write
```

不重新路由。任务文件中的 checks 必须是非空 argv 数组，不经过 shell；代码执行实际
checks，任一失败即 `failed` 并返回当前会话。默认 sandbox 为 `read-only`，只有任务
明确授权时才允许 `workspace-write`。新 dispatcher 的代码和聊天路线均不要求 Git；兼容入口 `jev-execute` 仍要求有 HEAD 的 Git 仓库。

## 当前模型委派子任务后的审核判断

入口直接选中的简单任务免模型审核；当前模型拆分并委派的子任务保留审核门控。
对于 native Luna 子代理，在执行前使用 `jev-run register TASK.json --repo REPO` 记录
任务范围和初始快照（不重新做入口分类）；执行后提交包含 `status`、`summary`、
`unresolved` 的报告，再依次执行：

```bash
jev-run check RUN_DIR --report REPORT.json
jev-run verify RUN_DIR
```

检查通过后由 Jev 判断是否交回当前模型审核。未完成、检查失败、证据过期、Jev
不可用或总开关关闭时均交回当前模型。这个 Git 快照协议要求仓库已有 HEAD；其他
场景不能伪造验证成功，应由当前模型处理。复杂任务整体的集成验证仍由当前模型负责。
`jev-execute --parent-run RUN_DIR` 同样保留后验审核判断。

## 旧完整入口

`jev-execute` 保留用于已有完整 manifest 的代码任务入口：仍执行入口 Jev、实际 checks
和保守回父策略，独立入口简单路径不进行后验模型审核；`--parent-run` 委派路径保留审核判断。它不能替代新的每输入 hook 分类。

`task`、`context`、`acceptance_criteria`、`allowed_paths`、`checks` 等完整任务字段和
父子任务协议仍见 [jev-delegation skill](../tools/jev-delegation/SKILL.md)。复杂任务的
架构、拆解、集成和最终决定由当前模型负责；子任务结果不会豁免父集成验证。

已通过 63 项相关自动化测试；真实 Jev → Luna 问候和非 Git 目录代码修改检查均完成，重复分派没有启动第二个 worker。真实复杂请求测试遇到 Jev 服务错误并回退当前会话。没有进行 UI 或截图验证，宿主自动触发与委派尚未进行端到端 UI 验证。
