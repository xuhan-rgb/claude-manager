"""Textual TUI 主应用 - Kitty 分屏 + tmux session 管理

架构：
- 左侧 Kitty Window：TUI 面板（本程序）
- 右侧 Kitty Window：tmux 客户端
- 每个任务 = 一个 tmux session（可包含多个 window）
- 切换任务 = 切换 tmux session
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Static, ListItem, ListView, Label, Button, Input, Rule

try:
    from textual.widgets import TextArea
except Exception:  # pragma: no cover - fallback for older Textual
    TextArea = None
from textual.screen import ModalScreen
from textual import on, work

from .models import Task
from .data_store import DataStore
from .tmux_control import TmuxController
from .terminal import get_adapter, TerminalAdapter
from .config import get_config, save_layout

import os
import logging
import time
import hashlib
import re
from pathlib import Path

# 设置日志
LOG_DIR = Path.home() / ".config" / "claude-manager" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)


class TaskItem(ListItem):
    """任务列表项

    颜色方案：
    - 激活的任务: 绿色箭头 ▶ (is_active)
    - 运行中: 蓝色 ● (running，Claude 正在工作)
    - 等待确认: 黄色 ● (running + waiting_confirm)
    - 已完成: 红色 ● (completed，等待查看)
    - 待开始: 白色 ○ (pending，还未开始工作)
    """

    def __init__(self, task_data: Task, is_active: bool = False, waiting_confirm: bool = False):
        super().__init__()
        self.task_data = task_data
        self.is_active = is_active
        self.waiting_confirm = waiting_confirm

    def compose(self) -> ComposeResult:
        t = self.task_data
        # 状态标签
        if t.status == 'running' and self.waiting_confirm:
            status_suffix = " [yellow]等待确认[/]"
        elif t.status == 'running':
            status_suffix = " [dim]任务中[/]"
        elif t.status == 'completed':
            status_suffix = " [dim]任务完成[/]"
        else:
            status_suffix = ""

        # 图标和颜色（非选中任务颜色更暗）
        if self.is_active:
            yield Static(f"[green bold]▶ {t.name}[/]{status_suffix}")
        elif t.status == 'completed':
            yield Static(f"[dim red]● {t.name}{status_suffix}[/]")
        elif t.status == 'running' and self.waiting_confirm:
            yield Static(f"[dim yellow]● {t.name}{status_suffix}[/]")
        elif t.status == 'running':
            yield Static(f"[dim blue]● {t.name}{status_suffix}[/]")
        elif t.status == 'pending':
            yield Static(f"[dim]○ {t.name}[/]")
        else:
            yield Static(f"[dim]✗ {t.name}[/]")


def generate_task_id(name: str) -> str:
    """根据任务名称生成短 ID（MD5 前 6 位）"""
    import hashlib
    h = hashlib.md5(name.encode('utf-8')).hexdigest()
    return h[:6]


class NewTaskDialog(ModalScreen):
    """新建任务对话框"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("新建任务", id="dialog-title")
            yield Label("任务名称", classes="field-label")
            yield Input(placeholder="输入任务名称...", id="task-name")
            yield Label("工作目录", classes="field-label")
            yield Input(placeholder="输入工作目录...", id="task-cwd", value=os.getcwd())
            yield Label("任务描述", classes="field-label")
            if TextArea:
                desc = TextArea(id="task-desc")
                desc.text = ""
                yield desc
            else:
                yield Input(placeholder="可选，简短描述...", id="task-desc")
            with Container(id="dialog-buttons"):
                yield Button("取消", id="cancel")
                yield Button("创建", variant="primary", id="create")

    def on_mount(self) -> None:
        cfg = get_config()
        try:
            dialog = self.query_one("#dialog", Container)
        except Exception:
            return
        dialog.styles.width = cfg.ui.left_panel_columns
        self._resize_desc()

    def _resize_desc(self) -> None:
        if not TextArea:
            return
        try:
            desc = self.query_one("#task-desc", TextArea)
        except Exception:
            return
        width = max(desc.size.width - 2, 1)
        text = desc.text or ""
        lines = 0
        for line in (text.splitlines() or [""]):
            line_len = max(len(line), 1)
            lines += (line_len - 1) // width + 1
        max_height = (self.size.height - 8) if self.size.height else 10
        if max_height < 4:
            max_height = 10
        target = min(max(lines + 1, 3), max_height)
        if desc.styles.height != target:
            desc.styles.height = target

    def on_resize(self) -> None:
        self._resize_desc()

    def on_key(self, event) -> None:
        if TextArea:
            try:
                desc = self.query_one("#task-desc", TextArea)
            except Exception:
                return
            if desc.has_focus:
                self._resize_desc()

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#create")
    def action_create(self) -> None:
        name = self.query_one("#task-name", Input).value.strip()
        cwd = self.query_one("#task-cwd", Input).value.strip() or os.getcwd()
        desc_widget = self.query_one("#task-desc")
        description = desc_widget.text if hasattr(desc_widget, "text") else desc_widget.value
        description = description.strip()
        if name:
            task_id = generate_task_id(name)
            self.dismiss({'task_id': task_id, 'name': name, 'cwd': cwd, 'description': description})


class EditTaskDescriptionDialog(ModalScreen):
    """编辑任务描述对话框"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, task_name: str, description: str):
        super().__init__()
        self.task_name = task_name
        self.description = description

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("任务描述", id="dialog-title")
            yield Label(f"任务: {self.task_name}", classes="field-label")
            if TextArea:
                desc = TextArea(id="edit-desc")
                desc.text = self.description
                yield desc
            else:
                yield Input(placeholder="输入描述...", id="edit-desc", value=self.description)
            with Container(id="dialog-buttons"):
                yield Button("取消", id="cancel")
                yield Button("保存", variant="primary", id="save")

    def on_mount(self) -> None:
        cfg = get_config()
        try:
            dialog = self.query_one("#dialog", Container)
        except Exception:
            return
        dialog.styles.width = cfg.ui.left_panel_columns
        self._resize_desc()

    def _resize_desc(self) -> None:
        if not TextArea:
            return
        try:
            desc = self.query_one("#edit-desc", TextArea)
        except Exception:
            return
        width = max(desc.size.width - 2, 1)
        text = desc.text or ""
        lines = 0
        for line in (text.splitlines() or [""]):
            line_len = max(len(line), 1)
            lines += (line_len - 1) // width + 1
        max_height = (self.size.height - 8) if self.size.height else 10
        if max_height < 4:
            max_height = 10
        target = min(max(lines + 1, 3), max_height)
        if desc.styles.height != target:
            desc.styles.height = target

    def on_resize(self) -> None:
        self._resize_desc()

    def on_key(self, event) -> None:
        if TextArea:
            try:
                desc = self.query_one("#edit-desc", TextArea)
            except Exception:
                return
            if desc.has_focus:
                self._resize_desc()

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        desc_widget = self.query_one("#edit-desc")
        description = desc_widget.text if hasattr(desc_widget, "text") else desc_widget.value
        description = description.strip()
        self.dismiss(description)


class ClaudeManagerApp(App):
    """Claude Manager - Kitty 分屏 + tmux session 管理

    架构：
    - 左侧 Kitty Window：TUI 面板
    - 右侧 Kitty Window：tmux 客户端（运行 tmux attach）
    - 每个任务对应一个 tmux session：cm-{task_id}
    - 每个 session 可包含多个 tmux window（claude, shell, rqt 等）
    """

    CSS = """
    Screen { background: $surface; }
    #main-container { width: 100%; height: 100%; padding: 0 1; }
    .section-title { text-style: bold; color: $warning; padding: 1 0 0 0; }
    ListView { height: auto; margin: 0; padding: 0; background: transparent; }
    ListItem { padding: 0; height: 1; }
    ListItem > Static { padding: 0 1; }
    ListItem:hover { background: $surface-lighten-1; }
    ListItem.-highlight { background: $primary 30%; }
    #debug-panel { height: 1fr; padding: 0 1; color: $text-muted; }
    #desc-panel { height: auto; padding: 0 1; color: $text-muted; }
    #cwd-panel { height: auto; padding: 0 1; color: $text-muted; }
    #status-line { dock: bottom; height: 1; background: $surface-darken-1; color: $text-muted; padding: 0 1; }
    #dialog { width: auto; height: auto; padding: 1 2; background: $surface; border: solid $primary; }
    #dialog-title { text-style: bold; text-align: center; padding-bottom: 1; }
    #dialog-buttons { height: auto; align: center middle; padding-top: 1; }
    #dialog-buttons Button { margin: 0 1; min-width: 8; }
    .field-label { color: $text; padding: 0 0 0 0; }
    Input { margin: 0 0 1 0; height: 3; }
    TextArea { margin: 0 0 1 0; height: 5; }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("n", "new_task", "新任务"),
        Binding("d", "delete_task", "删除"),
        Binding("m", "edit_description", "描述"),
        Binding("r", "restart_claude", "重启Claude"),
        Binding("e", "edit_config", "编辑配置"),
        Binding("up", "move_up", "上移", show=False),
        Binding("down", "move_down", "下移", show=False),
        Binding("k", "move_up", show=False),
        Binding("j", "move_down", show=False),
        Binding("1", "activate_1", show=False),
        Binding("2", "activate_2", show=False),
        Binding("3", "activate_3", show=False),
        Binding("4", "activate_4", show=False),
        Binding("5", "activate_5", show=False),
    ]

    def __init__(
        self,
        tmux_window_ids: list[int] | None = None,
        tmux_panel_windows: list[dict] | None = None,
        debug: bool = False,
    ):
        super().__init__()
        self.data_store = DataStore()
        self.tmux = TmuxController()
        self.adapter = get_adapter()  # 终端适配器（自动检测终端类型）
        self.tasks: list[Task] = []
        self.active_task_id: str | None = None
        self._suppress_highlight = False
        self._pane_state: dict[str, dict[str, float | str]] = {}
        self._prompt_state: dict[str, dict[str, float | str]] = {}
        self._pane_change_window = 20
        self._debug_state: dict[str, dict[str, object]] = {}
        self._continuous_active_start: dict[str, float] = {}  # task_id -> 连续活跃开始时间
        self._active_cwd_task_id: str | None = None
        self._active_cwd: str | None = None
        self.debug_mode = debug
        self._task_list_signature: tuple | None = None
        # 右侧 Kitty Window 的 ID（可多个）
        if tmux_panel_windows:
            self.tmux_panel_windows = self._normalize_panel_windows(tmux_panel_windows)
            self.tmux_window_ids = [p["window_id"] for p in self.tmux_panel_windows]
        else:
            self.tmux_window_ids = [str(w) for w in (tmux_window_ids or []) if w]
            self.tmux_panel_windows = self._normalize_panel_windows(
                [{"window_id": w} for w in self.tmux_window_ids]
            )
        # 状态打印计数器（每3次检测打印一次，即每15秒）
        self._status_print_counter = 0

    def _infer_panel_role(self, name: str | None, command: str | None) -> str | None:
        """根据面板名称或命令推断角色（main/cmd）"""
        if command:
            if "{cmd_session}" in command:
                return "cmd"
            if "{session}" in command:
                return "main"
        if name:
            lowered = name.lower()
            if "cmd" in lowered:
                return "cmd"
            if "main" in lowered:
                return "main"
        return None

    def _normalize_panel_windows(self, panel_windows: list[dict]) -> list[dict]:
        """规范化右侧面板信息"""
        panels: list[dict] = []
        for entry in panel_windows:
            if not entry:
                continue
            name = entry.get("name")
            window_id = entry.get("window_id")
            command = entry.get("command") or ""
            if window_id is None:
                continue
            role = self._infer_panel_role(name, command)
            panels.append(
                {
                    "name": name,
                    "window_id": str(window_id),
                    "command": command,
                    "role": role,
                }
            )

        # 如果没有明确的 cmd 面板，默认把第二个面板当作 cmd
        if panels and not any(p["role"] == "cmd" for p in panels) and len(panels) > 1:
            panels[1]["role"] = "cmd"

        for panel in panels:
            if panel["role"] is None:
                panel["role"] = "main"

        return panels

    def _format_panel_command(
        self,
        panel: dict,
        session_name: str,
        cmd_session_name: str,
    ) -> str | None:
        """根据面板配置生成 tmux attach 命令"""
        command = (panel.get("command") or "").strip()
        if not command:
            if panel.get("role") == "cmd":
                command = "tmux attach -t {cmd_session}"
            else:
                command = "tmux attach -d -t {session}"
        try:
            return command.format(session=session_name, cmd_session=cmd_session_name)
        except Exception:
            return command

    def _iter_panel_targets(self, session_name: str, cmd_session_name: str):
        """遍历面板及其目标 session"""
        panels = self.tmux_panel_windows or []
        for panel in panels:
            target_session = cmd_session_name if panel.get("role") == "cmd" else session_name
            attach_command = self._format_panel_command(panel, session_name, cmd_session_name)
            yield panel["window_id"], target_session, attach_command, panel.get("role")

    def _has_cmd_panel(self) -> bool:
        """是否存在命令面板"""
        return any(p.get("role") == "cmd" for p in (self.tmux_panel_windows or []))

    def _get_active_task(self) -> Task | None:
        """获取当前激活任务"""
        if not self.active_task_id:
            return None
        return next((t for t in self.tasks if t.task_id == self.active_task_id), None)

    def _format_path(self, path: str, max_length: int = 48) -> str:
        """格式化路径显示，避免过长"""
        if not path:
            return "-"
        try:
            path_str = str(Path(path).expanduser())
        except Exception:
            path_str = str(path)

        home = str(Path.home())
        if path_str.startswith(home):
            path_str = "~" + path_str[len(home):]

        if len(path_str) <= max_length:
            return path_str

        sep = os.sep
        if path_str.startswith("~"):
            parts = [p for p in path_str.split(sep) if p]
            tail = sep.join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else "")
            return f"~/{tail}" if tail else "~"
        if path_str.startswith(sep):
            parts = [p for p in path_str.split(sep) if p]
            tail = sep.join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else "")
            return f"/{tail}" if tail else sep
        parts = [p for p in path_str.split(sep) if p]
        tail = sep.join(parts[-2:]) if len(parts) >= 2 else path_str
        return f".../{tail}" if tail else "..."

    def _resolve_status_cwd(self) -> str:
        """获取状态栏显示的当前目录"""
        task = self._get_active_task()
        if task:
            if self._active_cwd_task_id == task.task_id and self._active_cwd:
                return self._active_cwd
            if task.cwd:
                return task.cwd
        return os.getcwd()

    def _refresh_active_cwd(self) -> None:
        """刷新当前任务的工作目录缓存（后台线程调用）"""
        task = self._get_active_task()
        if not task:
            self._active_cwd_task_id = None
            self._active_cwd = None
            return
        tmux_cwd = self.tmux.get_active_pane_path(task.task_id)
        if tmux_cwd:
            self._active_cwd_task_id = task.task_id
            self._active_cwd = tmux_cwd
            return
        self._active_cwd_task_id = task.task_id
        self._active_cwd = task.cwd or os.getcwd()

    def _update_status_line(self) -> None:
        """更新底部状态栏"""
        try:
            status_line = self.query_one("#status-line", Static)
        except Exception:
            return
        status_line.update(
            "n:新建 m:描述 r:重启 d:删除 q:退出"
        )

    def _update_desc_panel(self) -> None:
        """更新任务描述显示"""
        try:
            desc_panel = self.query_one("#desc-panel", Static)
        except Exception:
            return
        task = self._get_active_task()
        if not task:
            desc_panel.update("暂无任务")
            return
        description = (task.description or "").strip()
        desc_panel.update(description if description else "暂无描述")

    def _update_cwd_panel(self) -> None:
        """更新左侧目录显示"""
        try:
            cwd_panel = self.query_one("#cwd-panel", Static)
        except Exception:
            return
        cwd_display = self._format_path(self._resolve_status_cwd())
        cwd_panel.update(cwd_display)

    def _update_pane_state(self, task_id: str, pane_content: str) -> tuple[bool, bool, float]:
        """记录 pane 内容变化，用于判断是否有新输出"""
        now = time.time()
        digest = hashlib.md5(pane_content.encode('utf-8')).hexdigest()
        state = self._pane_state.get(task_id)
        if not state:
            self._pane_state[task_id] = {'hash': digest, 'last_change': now}
            return False, False, now
        changed = state['hash'] != digest
        if changed:
            state['hash'] = digest
            state['last_change'] = now
        recent_change = (now - state['last_change']) <= self._pane_change_window
        return changed, recent_change, state['last_change']

    def _strip_ansi(self, text: str) -> str:
        """去除 ANSI 控制序列，便于稳定解析"""
        return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)

    def _update_prompt_state(self, task_id: str, lines: list[str]) -> tuple[bool, bool, float]:
        """记录 prompt 之前的内容变化（用于判断是否有新输出）"""
        now = time.time()
        prompt_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if "❯" in lines[i]:
                prompt_idx = i
                break
        if prompt_idx <= 0:
            return False, False, 0.0
        pre_prompt = "\n".join(l for l in lines[:prompt_idx] if l.strip())
        digest = hashlib.md5(pre_prompt.encode("utf-8")).hexdigest()
        state = self._prompt_state.get(task_id)
        if not state:
            self._prompt_state[task_id] = {"hash": digest, "last_change": now}
            return False, False, now
        changed = state["hash"] != digest
        if changed:
            state["hash"] = digest
            state["last_change"] = now
        recent_change = (now - state["last_change"]) <= self._pane_change_window
        return changed, recent_change, state["last_change"]

    def _has_working_indicator(self, lines: list[str], pane_content: str) -> bool:
        """判断是否有 Claude 工作中的明显提示"""
        for line in lines:
            text = line.strip()
            if text.startswith("* ") and "..." in text:
                return True
        return False

    def _write_status_snapshot(
        self,
        task_id: str,
        current_status: str,
        summary: dict,
        tail_lines: list[str],
        raw_tail_lines: list[str],
    ) -> None:
        """追加保存状态核查快照到日志文件"""
        try:
            log_path = LOG_DIR / "status_debug.log"
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"{ts} | task={task_id} | status={current_status} | {summary}\n")
                for line in tail_lines:
                    f.write(f"  {line}\n")
                if raw_tail_lines:
                    f.write("  [raw]\n")
                    for line in raw_tail_lines:
                        f.write(f"  {line}\n")
                f.write("\n")
        except Exception as e:
            logger.error(f"写入状态快照失败: {e}")

    def _record_debug_state(self, task_id: str, metrics: dict, decision: str) -> None:
        """记录调试状态到内存，并触发 UI 更新"""
        if not self.debug_mode:
            return
        state = dict(metrics)
        state["decision"] = decision
        state["timestamp"] = time.time()
        self._debug_state[task_id] = state
        try:
            self.call_from_thread(self._update_debug_panel)
        except Exception:
            pass

    def _update_debug_panel(self) -> None:
        """更新调试面板"""
        if not self.debug_mode:
            return
        try:
            panel = self.query_one("#debug-panel", Static)
        except Exception:
            return
        if not self.tasks or not self.active_task_id:
            panel.update("暂无任务")
            return
        task = next((t for t in self.tasks if t.task_id == self.active_task_id), None)
        if not task:
            panel.update("暂无任务")
            return
        data = self._debug_state.get(task.task_id)
        if not data:
            panel.update(f"{task.name}\n暂无调试数据")
            return

        def fmt_bool(val):
            if val is None:
                return "-"
            return "Y" if val else "N"

        def fmt_int(val):
            if val is None:
                return "-"
            return str(val)

        lines = [
            f"任务: {task.name}",
            f"状态: {task.status} | 判定: {data.get('decision', '-')}",
            f"prompt={fmt_bool(data.get('prompt'))} confirm={fmt_bool(data.get('confirm'))}",
            f"activity_ago={fmt_int(data.get('activity_ago'))}s",
        ]
        panel.update("\n".join(lines))

    def compose(self) -> ComposeResult:
        with Vertical(id="main-container"):
            yield Static("TASKS", classes="section-title")
            yield ListView(id="tasks-list")
            yield Static("DESC", classes="section-title")
            yield Static("", id="desc-panel")
            yield Static("CWD", classes="section-title")
            yield Static("", id="cwd-panel")
            if self.debug_mode:
                yield Static("DEBUG", classes="section-title")
                yield Static("", id="debug-panel")
        yield Static("n:新建 m:描述 r:重启 d:删除 q:退出", id="status-line")

    def on_mount(self) -> None:
        """启动时初始化"""
        self.tasks = self.data_store.load_tasks()
        self.tmux.configure_global_options()
        for task in self.tasks:
            self.tmux.configure_session(task.task_id)
            if self.tmux.cmd_session_exists(task.task_id):
                self.tmux.configure_session_by_name(self.tmux.get_cmd_session_name(task.task_id))
        self.update_task_list()
        self._update_desc_panel()
        self._update_cwd_panel()
        self._update_status_line()
        # 定时检查 claude 完成状态
        cfg = get_config()
        self.set_interval(cfg.status.check_interval, self.check_task_status_async)

    def update_task_list(self) -> None:
        """更新任务列表 UI"""
        tasks_list = self.query_one("#tasks-list", ListView)
        signature = []
        for task in self.tasks:
            debug_data = self._debug_state.get(task.task_id, {})
            waiting_confirm = debug_data.get('confirm', False)
            signature.append(
                (
                    task.task_id,
                    task.name,
                    task.status,
                    task.task_id == self.active_task_id,
                    bool(waiting_confirm),
                )
            )
        signature_tuple = tuple(signature)
        if self._task_list_signature == signature_tuple:
            self._update_desc_panel()
            self._update_cwd_panel()
            self._update_status_line()
            if self.debug_mode:
                self._update_debug_panel()
            return
        self._task_list_signature = signature_tuple
        self._suppress_highlight = True
        try:
            tasks_list.clear()
            for task in self.tasks:
                is_active = (task.task_id == self.active_task_id)
                # 从 debug_state 获取 waiting_confirm 标志
                debug_data = self._debug_state.get(task.task_id, {})
                waiting_confirm = debug_data.get('confirm', False)
                logger.debug(f"[UI更新] {task.task_id}: confirm={waiting_confirm}, debug_data={debug_data}")
                tasks_list.append(TaskItem(task, is_active, waiting_confirm))
            if self.tasks:
                if self.active_task_id:
                    active_index = next(
                        (i for i, t in enumerate(self.tasks) if t.task_id == self.active_task_id),
                        0,
                    )
                else:
                    active_index = 0
                tasks_list.index = active_index
            tasks_list.refresh()  # 强制刷新显示
        finally:
            self._suppress_highlight = False
        self._update_desc_panel()
        self._update_cwd_panel()
        self._update_status_line()
        if self.debug_mode:
            self._update_debug_panel()

    @work(thread=True, exclusive=True, group="status")
    def check_task_status_async(self) -> None:
        """检查各任务的状态变化

        状态转换：
        - pending → running: 检测到用户开始输入或有输出
        - running → completed: 检测到 Claude 完成回答（提示符 + 有工作输出）
        """
        # 定期打印任务状态摘要（每3次检测，即每15秒）
        self._status_print_counter += 1
        if self._status_print_counter >= 3:
            self._status_print_counter = 0
            self._print_tasks_status()

        changed = False
        for task in self.tasks:
            new_status = self._check_task_status(task.task_id, task.status)
            if new_status != task.status:
                old_status = task.status
                task.status = new_status
                changed = True
                logger.info(f"任务 {task.name} 状态变化: {old_status} → {new_status}")

        if changed:
            self.data_store.save_tasks(self.tasks)

        self._refresh_active_cwd()

        # 每次检测都刷新 UI（因为 confirm 等标志可能变化）
        self.call_from_thread(self.update_task_list)

    def _print_tasks_status(self) -> None:
        """打印所有任务的当前状态摘要"""
        if not self.tasks:
            logger.info("📋 [状态摘要] 当前无任务")
            return

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("📋 [状态摘要] 当前任务状态:")

        status_symbols = {
            'pending': '○',
            'running': '●',
            'completed': '●',
        }

        for i, task in enumerate(self.tasks, 1):
            symbol = status_symbols.get(task.status, '?')
            active_mark = "▶" if task.task_id == self.active_task_id else " "

            # 根据状态选择不同的标记
            if task.status == 'pending':
                status_text = f"{symbol} pending  "
            elif task.status == 'running':
                status_text = f"{symbol} running  "
            elif task.status == 'completed':
                status_text = f"{symbol} completed"
            else:
                status_text = f"{symbol} {task.status}"

            logger.info(f"  {active_mark} {i}. {task.name[:30]:30s} | {status_text} | {task.task_id[:8]}")

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def _check_task_status(self, task_id: str, current_status: str) -> str:
        """检查任务状态，返回新状态（基于 Kitty at_prompt 标志）

        Args:
            task_id: 任务 ID
            current_status: 当前状态

        Returns:
            新状态（可能与当前状态相同）

        状态转换规则（使用 Kitty at_prompt 标志 - 最可靠）：
        - pending → running: 检测到用户输入活动
        - running → completed: Kitty 显示 at_prompt=True（在提示符处）+ 有工作内容
        """
        import subprocess
        session_name = self.tmux.get_session_name(task_id)
        is_active = (task_id == self.active_task_id)

        logger.info(f"[状态检测] 任务 {task_id}, 当前状态: {current_status}, active={is_active}")

        try:
            if current_status == 'failed':
                logger.info(f"[状态恢复] {task_id}: failed → pending")
                current_status = 'pending'

            # 1. 检查 session 和 claude 进程是否存在
            result = subprocess.run(
                ['tmux', 'list-panes', '-t', session_name, '-F', '#{pane_current_command}'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode != 0:
                logger.warning(f"[状态检测] session {session_name} 不存在")
                return 'completed' if current_status == 'completed' else 'pending'  # session 不存在

            commands = result.stdout.strip().split('\n')
            has_claude = any('claude' in cmd.lower() or 'node' in cmd.lower() for cmd in commands)
            if not has_claude:
                logger.warning(f"[状态检测] claude 进程不存在, 继续使用内容/活动判断")

            # 2. 获取活动状态（tmux 活动监控）
            activity_status = self.tmux.get_activity_status(task_id)
            has_activity = activity_status['has_activity']
            activity_time = activity_status.get('activity_time', 0)

            # 3. 内容检测（通过 capture-pane）
            has_prompt = False        # ? for shortcuts - 正常提示符
            waiting_confirm = False   # Esc to cancel - 等待用户确认
            result = subprocess.run(
                ['tmux', 'capture-pane', '-t', session_name, '-p', '-e'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                pane_content = result.stdout
                last_lines = pane_content.strip().split('\n')[-6:]
                last_content = '\n'.join(last_lines)
                has_prompt = '? for shortcuts' in last_content
                waiting_confirm = 'Esc to cancel' in last_content
                # 增强日志：显示检测到的内容特征
                if waiting_confirm:
                    logger.info(f"[内容检测] {task_id}: 检测到确认对话框 (Esc to cancel)")

            # ========== 4. 状态判断（新算法）==========
            # 核心逻辑：
            #   - 任务开始：连续 N 秒内 activity_ago 都 < M（持续有活动）
            #   - 任务完成：曾经是 running + 活动停止
            #
            cfg = get_config()
            activity_ago = int(time.time() - activity_time) if activity_time else None
            now = time.time()

            # 判断是否连续活跃
            if activity_ago is not None and activity_ago < cfg.status.active_threshold:
                # 当前有活动，记录/保持连续活跃开始时间
                if task_id not in self._continuous_active_start:
                    self._continuous_active_start[task_id] = now
            else:
                # 活动停止，清除连续活跃状态
                self._continuous_active_start.pop(task_id, None)

            # 计算连续活跃时长
            active_start = self._continuous_active_start.get(task_id)
            continuous_active_duration = (now - active_start) if active_start else 0
            is_continuously_active = continuous_active_duration >= cfg.status.continuous_duration

            logger.info(f"[状态判断] {task_id}: ago={activity_ago}s, continuous={continuous_active_duration:.1f}s, current={current_status}")

            # 记录调试信息
            metrics = {
                "active": is_active,
                "confirm": waiting_confirm,
                "activity_ago": activity_ago,
                "continuous": round(continuous_active_duration, 1),
            }

            def finish(status: str, reason: str) -> str:
                self._record_debug_state(task_id, metrics, reason)
                return status

            # ========== 5. 状态判断 ==========
            # 1. 等待确认：有确认对话框（优先级最高，不管活动状态）
            if waiting_confirm:
                if current_status != 'running':
                    logger.info(f"[状态转换] {task_id}: {current_status} → running (等待确认)")
                return finish('running', '等待确认')

            # 2. 任务中：连续 2 秒有活动
            if is_continuously_active:
                if current_status != 'running':
                    logger.info(f"[状态转换] {task_id}: {current_status} → running")
                return finish('running', f'任务中 (连续{continuous_active_duration:.1f}s)')

            # 3. 任务完成：曾经是 running + 活动停止
            if current_status == 'running' and not is_continuously_active and activity_ago is not None and activity_ago >= cfg.status.active_threshold:
                logger.info(f"[状态转换] {task_id}: running → completed")
                return finish('completed', '任务完成')

            # 4. 保持 running（活动刚开始但还不到 2 秒）
            if current_status == 'running':
                return finish('running', '保持 running')

            # 5. 已完成的任务：如果被选中，自动重置为 pending
            if current_status == 'completed':
                if is_active:
                    logger.info(f"[状态转换] {task_id}: completed → pending (选中后重置)")
                    return finish('pending', '选中后重置')
                return finish('completed', '保持 completed')

            # 6. 未开始
            return finish('pending', '未开始')

        except Exception as e:
            logger.error(f"检查任务 {task_id} 状态时出错: {e}")
            return current_status

    # ========== 任务操作 ==========

    def action_new_task(self) -> None:
        """新建任务"""
        def on_close(result):
            if result:
                self._create_task_async(
                    result['task_id'],
                    result['name'],
                    result['cwd'],
                    result.get('description', ''),
                )
        self.push_screen(NewTaskDialog(), on_close)

    @work(thread=True, exclusive=True, group="tmux")
    def _create_task_async(self, task_id: str, name: str, cwd: str, description: str) -> None:
        """异步创建任务"""
        # 检查 ID 是否已存在，如果存在则加后缀
        existing_ids = {t.task_id for t in self.tasks}
        original_id = task_id
        suffix = 1
        while task_id in existing_ids:
            task_id = f"{original_id}{suffix}"
            suffix += 1

        # 创建 tmux session（claude + 命令）
        if not self.tmux.create_session(task_id, cwd, "claude"):
            self.call_from_thread(self.notify, "创建 tmux session 失败", severity="error")
            return
        if not self.tmux.create_cmd_session(task_id, cwd):
            self.call_from_thread(self.notify, "创建命令 tmux session 失败", severity="warning")

        # 创建任务（初始状态为 pending，等待用户开始工作）
        task = Task(
            task_id=task_id,
            name=name,
            cwd=cwd,
            description=description,
            status='pending',
        )
        self.tasks.append(task)
        self.data_store.save_tasks(self.tasks)

        # 切换到新任务
        self.active_task_id = task_id
        self._do_switch_session(task_id)

        self.call_from_thread(self.update_task_list)
        self.call_from_thread(self.notify, f"任务 '{name}' 已创建")

    def action_delete_task(self) -> None:
        """删除任务"""
        tasks_list = self.query_one("#tasks-list", ListView)
        idx = tasks_list.index
        if idx is not None and 0 <= idx < len(self.tasks):
            self._delete_task_async(self.tasks[idx])

    def action_edit_description(self) -> None:
        """编辑任务描述"""
        tasks_list = self.query_one("#tasks-list", ListView)
        idx = tasks_list.index
        if idx is None or idx < 0 or idx >= len(self.tasks):
            self.notify("请先选择任务", severity="warning")
            return
        task = self.tasks[idx]

        def on_close(result):
            if result is None:
                return
            task.description = result
            self.data_store.save_tasks(self.tasks)
            self.update_task_list()
            self.notify("任务描述已更新")

        self.push_screen(EditTaskDescriptionDialog(task.name, task.description), on_close)

    @work(thread=True, exclusive=True, group="tmux")
    def _delete_task_async(self, task: Task) -> None:
        """异步删除任务"""
        # 删除 tmux session
        self.tmux.kill_session(task.task_id)

        # 从列表移除
        self.tasks = [t for t in self.tasks if t.task_id != task.task_id]
        self.data_store.save_tasks(self.tasks)

        if self.active_task_id == task.task_id:
            self.active_task_id = None

        self.call_from_thread(self.update_task_list)
        self.call_from_thread(self.notify, f"任务 '{task.name}' 已删除")

    @on(ListView.Highlighted, "#tasks-list")
    def on_task_highlighted(self, event: ListView.Highlighted) -> None:
        """ListView 高亮事件（方向键切换时触发）"""
        if self._suppress_highlight:
            return
        idx = event.list_view.index
        if idx is None or idx >= len(self.tasks):
            return
        task = self.tasks[idx]
        if task.task_id == self.active_task_id:
            return
        logger.info(f"高亮切换任务: {task.name} (id={task.task_id})")
        self._activate_task(task)

    def action_refresh_status(self) -> None:
        """手动刷新所有任务状态"""
        self.notify("刷新任务状态...")
        self.check_task_status_async()

    def action_restart_claude(self) -> None:
        """重启当前任务的 Claude（使用配置文件中的 API 设置）"""
        logger.info("[重启] action_restart_claude 被调用")

        if not self.active_task_id:
            logger.warning("[重启] 没有活跃任务")
            self.notify("请先选择一个任务", severity="warning")
            return

        task = next((t for t in self.tasks if t.task_id == self.active_task_id), None)
        if not task:
            logger.warning(f"[重启] 找不到任务: {self.active_task_id}")
            return

        logger.info(f"[重启] 开始重启任务: {task.name} ({task.task_id})")
        self.notify(f"重启 Claude: {task.name}")

        # 重启 Claude
        success = self.tmux.restart_claude(task.task_id)
        logger.info(f"[重启] 结果: {success}")

        if success:
            task.status = 'pending'
            self.data_store.save_tasks(self.tasks)
            self.update_task_list()
            self.notify("✅ Claude 重启成功", severity="information")
        else:
            self.notify("❌ Claude 重启失败", severity="error")

    def action_move_up(self) -> None:
        """向上移动（循环）"""
        tasks_list = self.query_one("#tasks-list", ListView)
        if not self.tasks:
            return
        idx = tasks_list.index or 0
        new_idx = (idx - 1) % len(self.tasks)
        tasks_list.index = new_idx

    def action_move_down(self) -> None:
        """向下移动（循环）"""
        tasks_list = self.query_one("#tasks-list", ListView)
        if not self.tasks:
            return
        idx = tasks_list.index or 0
        new_idx = (idx + 1) % len(self.tasks)
        tasks_list.index = new_idx

    def _activate_task(self, task: Task) -> None:
        """激活任务"""
        self.active_task_id = task.task_id
        self._active_cwd_task_id = task.task_id
        self._active_cwd = task.cwd or os.getcwd()
        # 如果是已完成状态，重置为 pending（无任务状态）
        if task.status == 'completed':
            task.status = 'pending'
            self.data_store.save_tasks(self.tasks)
        self.update_task_list()
        self._switch_session_async(task)

    @work(thread=True, exclusive=True, group="tmux")
    def _switch_session_async(self, task: Task) -> None:
        """异步切换 tmux session"""
        # 确保 session 存在
        if not self.tmux.session_exists(task.task_id):
            self.tmux.create_session(task.task_id, task.cwd, "claude")
            task.status = 'running'
            self.data_store.save_tasks(self.tasks)
            self.call_from_thread(self.update_task_list)
        if self.tmux_window_ids and self._has_cmd_panel():
            if not self.tmux.cmd_session_exists(task.task_id):
                self.tmux.create_cmd_session(task.task_id, task.cwd)

        # 切换 session
        self._do_switch_session(task.task_id)

    def _do_switch_session(self, task_id: str) -> None:
        """执行 session 切换

        方案：获取右侧窗口的 tty，用 tmux switch-client -c <tty> 切换
        """
        session_name = self.tmux.get_session_name(task_id)
        cmd_session_name = self.tmux.get_cmd_session_name(task_id)
        logger.info(
            f"_do_switch_session: task_id={task_id}, session={session_name}, "
            f"cmd_session={cmd_session_name}, tmux_window_ids={self.tmux_window_ids}"
        )

        import subprocess

        if self.tmux_window_ids:
            switched = False
            attached = False
            clients_by_tty = self.tmux.list_clients_by_tty()
            for window_id, target_session, attach_command, role in self._iter_panel_targets(
                session_name, cmd_session_name
            ):
                tty = self.adapter.get_window_tty(window_id)
                logger.info(
                    f"获取 tty: window_id={window_id}, tty={tty}, "
                    f"target_session={target_session}, role={role}"
                )
                if not tty:
                    if attach_command:
                        logger.info(
                            f"未获取到 tty，直接发送 attach: window_id={window_id}, "
                            f"command={attach_command}"
                        )
                        if self.adapter.send_text(f"{attach_command}\n", window_id):
                            attached = True
                    continue
                current_session = clients_by_tty.get(tty)
                if not current_session:
                    if attach_command:
                        logger.info(
                            f"未检测到 tmux client，发送 attach: window_id={window_id}, "
                            f"command={attach_command}"
                        )
                        if self.adapter.send_text(f"{attach_command}\n", window_id):
                            attached = True
                    continue
                if current_session == target_session:
                    continue
                try:
                    result = subprocess.run(
                        ['tmux', 'switch-client', '-c', tty, '-t', target_session],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    logger.info(
                        f"switch-client 结果: window_id={window_id}, "
                        f"returncode={result.returncode}, stderr={result.stderr}"
                    )
                    if result.returncode == 0:
                        switched = True
                except Exception as e:
                    logger.error(f"switch-client 异常: window_id={window_id}, err={e}")
            # 已有面板时，避免备用方案误切换到错误客户端
            return

        # 备用方案：直接调用（切换最近的 client）
        logger.info("使用备用方案")
        try:
            result = subprocess.run(
                ['tmux', 'switch-client', '-t', session_name],
                capture_output=True,
                text=True,
                timeout=2
            )
            logger.info(f"备用方案结果: returncode={result.returncode}, stderr={result.stderr}")
        except Exception as e:
            logger.error(f"备用方案异常: {e}")

    def action_activate_1(self) -> None:
        self._activate_by_index(0)

    def action_activate_2(self) -> None:
        self._activate_by_index(1)

    def action_activate_3(self) -> None:
        self._activate_by_index(2)

    def action_activate_4(self) -> None:
        self._activate_by_index(3)

    def action_activate_5(self) -> None:
        self._activate_by_index(4)

    def _activate_by_index(self, index: int) -> None:
        """通过索引激活任务"""
        if index < len(self.tasks):
            self._activate_task(self.tasks[index])

    def action_refresh(self) -> None:
        """刷新"""
        self.tasks = self.data_store.load_tasks()
        self.update_task_list()
        self.refresh_processes_async()
        self.notify("已刷新")

    def action_quit(self) -> None:
        """退出应用，同时关闭右侧 tmux 窗口"""
        # 保存当前布局
        self._save_current_layout()

        if self.tmux_window_ids:
            for window_id in self.tmux_window_ids:
                try:
                    closed = self.adapter.close_window(window_id)
                    logger.info(f"关闭右侧窗口: window_id={window_id}, closed={closed}")
                except Exception as e:
                    logger.error(f"关闭右侧窗口失败: window_id={window_id}, err={e}")
        self.exit()

    def _save_current_layout(self) -> None:
        """保存当前窗口布局"""
        try:
            # 使用适配器获取当前会话/Tab 的所有窗口
            windows = self.adapter.list_windows()
            if len(windows) < 2:
                return

            # 获取所有窗口的宽度
            total_columns = sum(w.columns for w in windows)

            if len(windows) >= 3:
                # 三列布局：按顺序应该是 [TUI, 中间tmux, 右侧tmux]
                left_columns = windows[0].columns
                middle_columns = windows[1].columns
                right_columns = windows[2].columns

                save_layout(left_columns, middle_columns, right_columns, total_columns)
                logger.info(
                    f"[布局] 已保存: 左={left_columns}, 中={middle_columns}, "
                    f"右={right_columns}, 总={total_columns}"
                )
            elif len(windows) == 2:
                # 两列布局
                left_columns = windows[0].columns
                middle_columns = windows[1].columns

                save_layout(left_columns, middle_columns, 0, total_columns)
                logger.info(
                    f"[布局] 已保存: 左={left_columns}, 右={middle_columns}, 总={total_columns}"
                )
        except Exception as e:
            logger.warning(f"[布局] 保存失败: {e}")


def run_app(
    tmux_window_id: int = None,
    tmux_window_ids: list[int] | None = None,
    tmux_panel_windows: list[dict] | None = None,
    debug: bool = False,
):
    """运行应用"""
    if tmux_window_ids is None and tmux_window_id is not None:
        tmux_window_ids = [tmux_window_id]
    app = ClaudeManagerApp(
        tmux_window_ids=tmux_window_ids,
        tmux_panel_windows=tmux_panel_windows,
        debug=debug,
    )
    app.run()
