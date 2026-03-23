"""启动器 - 创建终端分屏布局

支持多种终端（Kitty、tmux 等）的分屏布局创建。

布局（以三栏为例）：
┌──────────────┬───────────────────────┬───────────────────────┐
│  TUI 面板    │  tmux 客户端           │  tmux 客户端           │
│  (Window 1)  │  (Window 2)            │  (Window 3)            │
│  比例可配置  │  比例可配置            │  比例可配置            │
└──────────────┴───────────────────────┴───────────────────────┘

工作流程：
1. 检测终端类型，获取对应适配器
2. 加载已有任务，确保对应 tmux session 存在
3. 根据配置创建分屏窗口
4. 启动 TUI 并传入窗口 ID 列表
"""

import os
import sys
import time
import logging

from .terminal import get_adapter, check_environment, TerminalAdapter
from .tmux_control import TmuxController, check_tmux
from .data_store import DataStore
from .config import (
    get_config,
    get_terminal_config,
    load_layout,
    save_layout,
    PanelConfig,
)

logger = logging.getLogger(__name__)


def ensure_task_sessions():
    """确保所有已有任务的 tmux session 存在

    Returns:
        (claude_session, cmd_session, has_tasks)
    """
    data_store = DataStore()
    tmux = TmuxController()

    tasks = data_store.load_tasks()

    if not tasks:
        # 没有任务，保持右侧为普通终端，不附加 tmux
        return None, None, False

    # 为每个任务确保 session 存在
    first_session = None
    first_cmd_session = None
    for task in tasks:
        session_name = tmux.get_session_name(task.task_id)
        cmd_session_name = tmux.get_cmd_session_name(task.task_id)
        if not tmux.session_exists(task.task_id):
            # 创建 session
            if tmux.create_session(task.task_id, task.cwd, "claude"):
                print(f"✅ 已创建 session: {session_name}")
            else:
                print(f"⚠️  创建 session 失败: {session_name}")
        else:
            tmux.configure_session(task.task_id)

        if not tmux.cmd_session_exists(task.task_id):
            if tmux.create_cmd_session(task.task_id, task.cwd):
                print(f"✅ 已创建 session: {cmd_session_name}")
            else:
                print(f"⚠️  创建 session 失败: {cmd_session_name}")
        else:
            tmux.configure_session_by_name(cmd_session_name)
            tmux.ensure_cmd_layout(task.task_id)

        if first_session is None:
            first_session = session_name
            first_cmd_session = cmd_session_name

    return (
        first_session,
        first_cmd_session,
        True,
    )


def launch_split_layout(return_panel_windows: bool = False):
    """创建分屏布局并启动 TUI

    Returns:
        (success, result)
        - 成功时 result 为窗口 ID 列表
        - 失败时 result 为错误消息
    """
    # 检查终端环境
    ok, msg, adapter = check_environment()
    if not ok:
        return False, f"终端检查失败: {msg}"

    print(f"📱 {msg}")

    if adapter.name == "terminator":
        term_cfg = get_terminal_config().terminator
        layout_name = term_cfg.get("layout", "auto")
        if not adapter.start_layout(layout_name, term_cfg):
            return False, "Terminator 启动布局失败"

    # 检查 tmux
    tmux_ok, tmux_msg = check_tmux()
    if not tmux_ok:
        return False, f"tmux 检查失败: {tmux_msg}"

    tmux = TmuxController()
    tmux.configure_global_options()

    # 获取当前窗口信息
    current_window = adapter.get_current_window()
    if not current_window:
        return False, "无法获取当前窗口"

    # 确保所有任务的 tmux session 存在
    first_session, first_cmd_session, has_tasks = ensure_task_sessions()

    # 加载终端配置
    terminal_config = get_terminal_config()
    panels = terminal_config.layout.panels

    no_remote_control = adapter.name in {"xterm", "terminator"}

    # 设置布局模式（如果适配器支持）
    if not no_remote_control:
        adapter.lock_layout(["splits"])
        adapter.set_layout("splits")
        time.sleep(0.05)

    # 获取总列数
    total_columns = adapter.get_total_columns()
    if not no_remote_control:
        print(f"📊 终端总宽度：{total_columns} 列")

    # 加载保存的布局配置
    saved_layout = load_layout()

    # 创建分屏窗口
    window_ids = []
    created_panels = []
    panel_windows = []

    if adapter.name == "terminator":
        panel_windows = [
            {"name": "main_tmux", "window_id": "main", "command": "tmux attach -d -t {session}"},
            {"name": "cmd_tmux", "window_id": "cmd", "command": "tmux attach -t {cmd_session}"},
        ]
        window_ids = ["main", "cmd"]
        created_panels = [(PanelConfig(name="main_tmux"), "main"), (PanelConfig(name="cmd_tmux"), "cmd")]
    else:
        # 创建分屏窗口
        for panel in panels:
            if panel.name == "tui":
                # TUI 在当前窗口运行，记录当前窗口 ID
                created_panels.append((panel, current_window.id))
                continue

            # 检查是否可选面板，且终端宽度不足
            if not no_remote_control:
                remaining_columns = total_columns - sum(
                    int(total_columns * p.ratio) for p, _ in created_panels
                )
                if panel.optional and remaining_columns < panel.min_columns:
                    print(f"⚠️  跳过可选面板 {panel.name}（宽度不足）")
                    continue

            # 构建命令（替换占位符）
            if has_tasks and panel.command:
                command = panel.command.format(
                    session=first_session,
                    cmd_session=first_cmd_session,
                )
            else:
                command = "bash"

            # 创建分屏
            result = adapter.create_split(
                direction=terminal_config.layout.direction,
                command=command if no_remote_control else "bash",
                cwd=os.getcwd(),
            )

            if not result.success:
                print(f"⚠️  创建面板 {panel.name} 失败: {result.error}")
                if not panel.optional:
                    return False, f"创建必需面板 {panel.name} 失败"
                continue

            print(f"✅ 已创建面板 {panel.name} (ID: {result.window_id})")
            window_ids.append(result.window_id)
            created_panels.append((panel, result.window_id))
            panel_windows.append(
                {
                    "name": panel.name,
                    "window_id": result.window_id,
                    "command": panel.command,
                }
            )

    # 等待窗口启动
    time.sleep(0.2)

    # 发送 tmux attach 命令（仅在已有任务时，且非 xterm 模式）
    if has_tasks and not no_remote_control:
        for panel, window_id in created_panels:
            if panel.name == "tui":
                continue

            if not panel.command:
                continue
            command = panel.command.format(
                session=first_session,
                cmd_session=first_cmd_session,
            )
            if command:
                adapter.send_text(f"{command}\n", window_id)

    # 等待 tmux 启动
    time.sleep(0.3)

    # 调整窗口大小
    if not no_remote_control:
        _adjust_panel_sizes(adapter, created_panels, total_columns, saved_layout)

    # 等待 Kitty 窗口尺寸生效，然后强制 tmux 重新适配窗口大小
    if has_tasks and not no_remote_control:
        time.sleep(0.3)
        import subprocess
        for session_name in [first_session, first_cmd_session]:
            if session_name:
                subprocess.run(
                    ['tmux', 'resize-window', '-A', '-t', session_name],
                    capture_output=True, timeout=2,
                )

    # 切换焦点回 TUI 窗口
    if not no_remote_control:
        adapter.focus_window(current_window.id)

    if return_panel_windows:
        return True, {
            "window_ids": window_ids,
            "panel_windows": panel_windows,
            "has_tasks": has_tasks,
        }
    return True, window_ids


def _adjust_panel_sizes(
    adapter: TerminalAdapter,
    created_panels: list,
    total_columns: int,
    saved_layout,
) -> None:
    """调整各面板的大小

    Args:
        adapter: 终端适配器
        created_panels: [(PanelConfig, window_id), ...]
        total_columns: 总列数
        saved_layout: 保存的布局配置
    """
    cfg = get_config()
    SEPARATOR_WIDTH = 1
    num_separators = len(created_panels) - 1
    available_columns = total_columns - (num_separators * SEPARATOR_WIDTH)

    # 判断是否使用保存的布局（终端大小变化超过 20% 时丢弃旧布局）
    size_ratio = (
        abs(total_columns - saved_layout.total_columns) / saved_layout.total_columns
        if saved_layout.total_columns > 0
        else 1.0
    )
    use_saved = (
        saved_layout.middle_columns > 0
        and len(created_panels) >= 3
        and saved_layout.total_columns > 0
        and size_ratio < 0.2
    )

    if use_saved:
        # 使用保存的布局
        target_columns = [
            saved_layout.left_columns,
            saved_layout.middle_columns,
            available_columns - saved_layout.left_columns - saved_layout.middle_columns,
        ]
        # 确保右侧窗口不会太窄
        if target_columns[2] < 10:
            use_saved = False

    if not use_saved:
        # 计算默认布局
        target_columns = []
        for panel, _ in created_panels:
            cols = int(available_columns * panel.ratio)
            cols = max(cols, panel.min_columns)
            if panel.max_columns > 0:
                cols = min(cols, panel.max_columns)
            target_columns.append(cols)

        # 调整以确保总和等于 available_columns
        diff = available_columns - sum(target_columns)
        if diff != 0 and target_columns:
            # 将差值加到最后一个非固定面板
            for i in range(len(target_columns) - 1, -1, -1):
                panel, _ = created_panels[i]
                if panel.max_columns == 0:
                    target_columns[i] += diff
                    break

    # 应用布局
    for i, (panel, window_id) in enumerate(created_panels):
        if i >= len(target_columns):
            break
        cols = target_columns[i]
        adapter.focus_window(window_id)
        adapter.resize_window(window_id, columns=cols)
        time.sleep(0.1)

    # 打印布局信息
    layout_str = ", ".join(
        f"{panel.name}={cols}"
        for (panel, _), cols in zip(created_panels, target_columns)
    )
    if use_saved:
        print(f"📐 恢复布局：{layout_str}")
    else:
        print(f"⚙️  设置布局：{layout_str}")

    # 保存布局（仅在首次计算时）
    if not use_saved and len(target_columns) >= 2:
        left = target_columns[0] if len(target_columns) > 0 else 0
        middle = target_columns[1] if len(target_columns) > 1 else 0
        right = target_columns[2] if len(target_columns) > 2 else 0
        save_layout(left, middle, right, total_columns)


def launch_tui_with_split(debug: bool = False):
    """启动完整的分屏 TUI 环境"""
    success, result = launch_split_layout(return_panel_windows=True)

    if not success:
        print(f"❌ {result}")
        print("\n💡 提示：")
        print("  1. 确保在 Kitty 终端或 tmux 会话中运行")
        print("  2. 如果使用 Kitty，确保 allow_remote_control=yes")
        print("  3. 确保已安装 tmux")
        sys.exit(1)

    tmux_window_ids = result.get("window_ids", [])
    panel_windows = result.get("panel_windows", [])
    has_tasks = result.get("has_tasks", False)
    print(f"✅ 分屏布局已创建")
    print(f"   左侧: TUI 面板")
    if len(tmux_window_ids) == 1:
        panel_label = "tmux 工作区" if has_tasks else "普通终端"
        print(f"   右侧: {panel_label} (Window ID: {tmux_window_ids[0]})")
    elif len(tmux_window_ids) > 1:
        panel_label = "tmux 工作区" if has_tasks else "普通终端"
        print(
            f"   右侧: {panel_label} "
            f"(Window IDs: {', '.join(str(w) for w in tmux_window_ids)})"
        )
    print()

    # 启动 TUI
    from .app import run_app
    run_app(tmux_window_ids=tmux_window_ids, tmux_panel_windows=panel_windows, debug=debug)


if __name__ == "__main__":
    launch_tui_with_split()
