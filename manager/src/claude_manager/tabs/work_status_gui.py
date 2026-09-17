#!/usr/bin/env python3
"""Work Status GUI - Kitty 窗口和 Tab 管理器"""

import fcntl
import os
import sys
import subprocess
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QLabel,
    QPushButton, QFrame, QToolButton, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon

from claude_manager.tabs.work_status import (
    OSWindowStatus,
    TabStatus,
    project_name_for_cwd,
    scan_all_windows,
)


_BACKGROUND_ENV = "CLAUDE_MANAGER_WORK_STATUS_BACKGROUND"
_instance_lock = None


_STATUS_LABELS = {
    "working": "处理中",
    "waiting": "待确认",
    "completed": "已完成",
    "idle": "空闲",
}
_STATUS_COLORS = {
    "working": "#63c5e8",
    "waiting": "#f2b966",
    "completed": "#83c98b",
    "idle": "#8b969b",
}


class TaskCard(QFrame):
    """Compact, clickable summary of one Claude/Codex process."""

    clicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, tab, process):
        super().__init__()
        self.tab = tab
        self.process = process
        self.setObjectName("taskCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(102)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        status = process.status if process.status in _STATUS_LABELS else "idle"
        status_label = QLabel(f"● {_STATUS_LABELS[status]}")
        status_label.setStyleSheet(
            f"color: {_STATUS_COLORS[status]}; font-size: 9pt; font-weight: 600;"
        )
        top_row.addWidget(status_label)
        top_row.addStretch(1)

        agent_label = QLabel(process.display_name)
        agent_label.setObjectName("agentLabel")
        top_row.addWidget(agent_label, 0, Qt.AlignRight)
        layout.addLayout(top_row)

        task_label = QLabel(process.task_summary or "未记录任务")
        task_label.setObjectName("taskTitle")
        task_label.setWordWrap(True)
        task_label.setToolTip(process.task_summary or "未记录任务")
        layout.addWidget(task_label)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        directory_label = QLabel(process.short_cwd)
        directory_label.setObjectName("directoryLabel")
        directory_label.setToolTip(process.cwd)
        directory_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        directory_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bottom_row.addWidget(directory_label, 1)

        tab_label = QLabel(f"Tab {tab.tab_id}")
        tab_label.setObjectName("tabLabel")
        bottom_row.addWidget(tab_label, 0, Qt.AlignRight)

        close_button = QToolButton()
        close_button.setText("×")
        close_button.setToolTip("关闭 Tab")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.closed)
        bottom_row.addWidget(close_button, 0, Qt.AlignRight)
        layout.addLayout(bottom_row)

        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        border = "#4aa8c8" if selected else "#39464c"
        background = "#304750" if selected else "#293136"
        self.setStyleSheet(
            "QFrame#taskCard {"
            f"background-color: {background}; border: 1px solid {border}; "
            "border-radius: 8px; }"
            "QLabel#taskTitle { color: #f1f5f6; font-size: 10pt; font-weight: 600; }"
            "QLabel#agentLabel { color: #bdc9ce; font-size: 9pt; }"
            "QLabel#directoryLabel { color: #9ba9ae; font-family: monospace; font-size: 9pt; }"
            "QLabel#tabLabel { color: #89979c; font-size: 9pt; }"
            "QToolButton#closeButton { color: #849196; background: transparent; "
            "border: none; font-size: 15pt; padding: 0 3px; }"
            "QToolButton#closeButton:hover { color: #ef7272; }"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _instance_lock_path() -> Path:
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    return runtime_dir / f"claude-manager-work-status-{os.getuid()}.lock"


def _acquire_instance_lock(lock_path=None):
    """Return an open lock file, or None when another instance owns it."""
    path = Path(lock_path) if lock_path else _instance_lock_path()
    lock_file = path.open("a+")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    return lock_file


def _instance_is_running() -> bool:
    lock_file = _acquire_instance_lock()
    if lock_file is None:
        return True
    lock_file.close()
    return False


def _launch_background() -> int:
    env = os.environ.copy()
    env[_BACKGROUND_ENV] = "1"
    subprocess.Popen(
        [sys.executable, sys.argv[0]],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return 0


class WorkStatusGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.windows = []
        self.current_window = None
        self.dashboard_entries = []
        self.visited_windows = set()  # 记录访问过的窗口 socket
        self.ignored_windows = set()  # 记录忽略的窗口 socket
        self.load_visited_history()  # 加载历史记录
        self.load_ignored_list()  # 加载忽略列表
        self.init_ui()
        self.load_data()

    def init_ui(self):
        """初始化 UI"""
        self.setWindowTitle('Claude / Codex 工作状态')
        self.setGeometry(100, 100, 960, 680)
        self.setMinimumSize(700, 420)

        # 设置窗口图标
        icon_path = Path.home() / '.local/share/icons/work-status.svg'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            self.setWindowIcon(QIcon.fromTheme('utilities-terminal'))

        # 主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部只保留全局摘要，具体信息放进按工程分组的任务卡片。
        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("toolbar")
        toolbar_widget.setFixedHeight(64)
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(18, 10, 16, 8)
        toolbar.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel('工作状态')
        title.setObjectName("pageTitle")
        title_box.addWidget(title)
        hint = QLabel('按工程查看 Claude / Codex 正在处理的任务')
        hint.setObjectName("pageHint")
        title_box.addWidget(hint)
        toolbar.addLayout(title_box)

        toolbar.addStretch(1)

        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.load_data)
        refresh_btn.setFixedSize(64, 32)
        refresh_btn.setToolTip('刷新')
        toolbar.addWidget(refresh_btn)

        self.status_label = QLabel('')
        self.status_label.setObjectName("summaryLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        toolbar.addWidget(self.status_label)

        main_layout.addWidget(toolbar_widget)

        dashboard_label = QLabel('任务看板')
        dashboard_label.setObjectName("sectionTitle")
        main_layout.addWidget(dashboard_label)

        self.dashboard_list = QListWidget()
        self.dashboard_list.setObjectName("dashboardList")
        self.dashboard_list.setSpacing(6)
        self.dashboard_list.setUniformItemSizes(False)
        self.dashboard_list.setSelectionMode(QListWidget.SingleSelection)
        self.dashboard_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.dashboard_list.customContextMenuRequested.connect(
            self.show_dashboard_context_menu
        )
        self.dashboard_list.itemSelectionChanged.connect(self._update_card_selection)
        main_layout.addWidget(self.dashboard_list, 1)

        # 保留旧列表作为内部兼容层，避免破坏已有的键盘/测试调用。
        self.window_list = QListWidget()
        self.window_list.itemClicked.connect(self.on_window_selected)
        self.window_list.currentItemChanged.connect(self.on_window_changed)
        self.window_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.window_list.customContextMenuRequested.connect(self.show_window_context_menu)

        self.tab_list = QTreeWidget()
        self.tab_list.setColumnCount(2)
        self.tab_list.setHeaderHidden(True)
        self.tab_list.setRootIsDecorated(False)
        self.tab_list.setIndentation(0)
        header = self.tab_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.Stretch)
        header.setSectionResizeMode(1, header.Fixed)
        self.tab_list.setColumnWidth(1, 36)
        self.tab_list.itemClicked.connect(self.on_tab_clicked)
        self.window_list.hide()
        self.tab_list.hide()

        # 设置样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #202426;
            }
            QWidget#toolbar {
                background-color: #252b2e;
                border-bottom: 1px solid #354147;
            }
            QLabel#pageTitle {
                color: #ffffff;
                font-size: 15pt;
                font-weight: 700;
            }
            QLabel#pageHint, QLabel#summaryLabel {
                color: #9ba9ae;
                font-size: 9pt;
            }
            QLabel#sectionTitle {
                color: #c2cdd1;
                font-size: 10pt;
                font-weight: 600;
                padding: 10px 18px 4px;
            }
            QPushButton {
                background-color: #2d8ca8;
                color: #f5fbfc;
                border: none;
                border-radius: 5px;
                font-size: 9pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3ba7c5;
            }
            QPushButton:pressed {
                background-color: #25788f;
            }
            QListWidget#dashboardList {
                background-color: #202426;
                border: none;
                padding: 4px 16px 14px;
                outline: none;
            }
            QListWidget#dashboardList::item {
                background: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }
            QListWidget#dashboardList::item:selected {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #202426;
                width: 10px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #4d5a60;
                border-radius: 5px;
                min-height: 28px;
            }
            QScrollBar::handle:vertical:hover {
                background: #65747a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        # 定时刷新（每 5 秒）
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.load_data)
        self.refresh_timer.start(5000)

    def load_visited_history(self):
        """加载访问过的窗口历史"""
        history_file = Path.home() / '.local/share/kitty/work-status-history.txt'
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    self.visited_windows = set(line.strip() for line in f if line.strip())
            except Exception as e:
                print(f"[WARNING] 无法加载历史记录: {e}", file=sys.stderr)

    def save_visited_history(self):
        """保存访问过的窗口历史"""
        history_file = Path.home() / '.local/share/kitty/work-status-history.txt'
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(history_file, 'w') as f:
                for socket in sorted(self.visited_windows):
                    f.write(f"{socket}\n")
        except Exception as e:
            print(f"[WARNING] 无法保存历史记录: {e}", file=sys.stderr)

    def mark_window_visited(self, socket):
        """标记窗口为已访问"""
        self.visited_windows.add(socket)
        self.save_visited_history()

    def load_ignored_list(self):
        """加载忽略的窗口列表"""
        ignored_file = Path.home() / '.local/share/kitty/work-status-ignored.txt'
        if ignored_file.exists():
            try:
                with open(ignored_file, 'r') as f:
                    self.ignored_windows = set(line.strip() for line in f if line.strip())
            except Exception as e:
                print(f"[WARNING] 无法加载忽略列表: {e}", file=sys.stderr)

    def save_ignored_list(self):
        """保存忽略的窗口列表"""
        ignored_file = Path.home() / '.local/share/kitty/work-status-ignored.txt'
        try:
            ignored_file.parent.mkdir(parents=True, exist_ok=True)
            with open(ignored_file, 'w') as f:
                for socket in sorted(self.ignored_windows):
                    f.write(f"{socket}\n")
        except Exception as e:
            print(f"[WARNING] 无法保存忽略列表: {e}", file=sys.stderr)

    def toggle_ignore_window(self, socket):
        """切换窗口的忽略状态"""
        if socket in self.ignored_windows:
            self.ignored_windows.remove(socket)
        else:
            self.ignored_windows.add(socket)
        self.save_ignored_list()
        self.update_window_list()
        self.update_dashboard()

    def load_data(self):
        """加载 Kitty 窗口数据"""
        try:
            self.windows = scan_all_windows()
            self.update_window_list()
            self.update_dashboard()

            total_tabs = sum(len(w.tabs) for w in self.windows)
            processes = [
                process
                for window in self.windows
                for tab in window.tabs
                for process in tab.ai_processes
            ]
            working = sum(process.status == "working" for process in processes)
            waiting = sum(process.status == "waiting" for process in processes)
            projects = len({self._project_name(process.cwd) for process in processes})
            self.status_label.setText(
                f"{projects} 个工程 · {len(processes)} 个任务 · "
                f"{working} 处理中 · {waiting} 待确认"
            )
        except KeyboardInterrupt:
            # 用户按 Ctrl+C，退出程序
            print("\n用户中断，退出程序")
            QApplication.quit()
            sys.exit(0)
        except Exception as e:
            # 其他错误，显示但不退出
            error_msg = f"加载失败: {e}"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            self.status_label.setText(error_msg)

        # 如果有当前窗口，更新 tab 列表
        if self.current_window:
            # 找到更新后的当前窗口
            for win in self.windows:
                if win.socket == self.current_window.socket:
                    self.current_window = win
                    self.update_tab_list()
                    break

    @staticmethod
    def _project_name(cwd: str) -> str:
        """Use the AI process cwd as the project identity shown in the board."""
        return project_name_for_cwd(cwd)

    def update_dashboard(self):
        """Render all AI processes grouped by their actual working directory."""
        self.dashboard_list.clear()
        self.dashboard_entries = []

        groups = {}
        for os_window in self.windows:
            if os_window.socket in self.ignored_windows:
                continue
            for tab in os_window.tabs:
                for process in tab.ai_processes:
                    project = self._project_name(process.cwd)
                    groups.setdefault(project, []).append((os_window, tab, process))

        if not groups:
            item = QListWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            empty = QLabel("没有检测到正在运行的 Claude / Codex 任务")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #849196; padding: 34px; font-size: 10pt;")
            item.setSizeHint(empty.sizeHint())
            self.dashboard_list.addItem(item)
            self.dashboard_list.setItemWidget(item, empty)
            return

        status_order = {"waiting": 0, "working": 1, "completed": 2, "idle": 3}
        sorted_groups = sorted(
            groups.items(),
            key=lambda pair: (
                min(status_order.get(entry[2].status, 3) for entry in pair[1]),
                pair[0].casefold(),
            ),
        )

        for project, entries in sorted_groups:
            entries.sort(
                key=lambda entry: (
                    status_order.get(entry[2].status, 3),
                    entry[2].display_name.casefold(),
                    entry[2].short_cwd.casefold(),
                )
            )

            header_item = QListWidgetItem()
            header_item.setFlags(header_item.flags() & ~Qt.ItemIsSelectable)
            header = QWidget()
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(2, 8, 2, 0)
            header_layout.setSpacing(8)
            project_label = QLabel(f"●  {project}")
            project_label.setStyleSheet(
                "color: #e7eef0; font-size: 11pt; font-weight: 700;"
            )
            header_layout.addWidget(project_label)
            count_label = QLabel(f"{len(entries)} 个任务")
            count_label.setStyleSheet("color: #87969b; font-size: 9pt;")
            header_layout.addWidget(count_label)
            header_layout.addStretch(1)
            header_item.setSizeHint(header.sizeHint())
            self.dashboard_list.addItem(header_item)
            self.dashboard_list.setItemWidget(header_item, header)

            for os_window, tab, process in entries:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, (os_window, tab, process))
                card = TaskCard(tab, process)
                card.clicked.connect(
                    lambda item=item: self._dashboard_jump(item)
                )
                card.closed.connect(
                    lambda item=item: self._dashboard_close(item)
                )
                item.setSizeHint(card.sizeHint())
                self.dashboard_list.addItem(item)
                self.dashboard_list.setItemWidget(item, card)
                self.dashboard_entries.append((item, card))

    def _update_card_selection(self):
        selected = self.dashboard_list.currentItem()
        for item, card in self.dashboard_entries:
            card.set_selected(item is selected)

    def _dashboard_jump(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        os_window, tab, _ = data
        self.dashboard_list.setCurrentItem(item)
        self.jump_to_tab(os_window, tab)

    def _dashboard_close(self, item):
        data = item.data(Qt.UserRole)
        if data:
            os_window, tab, _ = data
            self.close_tab(os_window, tab)

    def show_dashboard_context_menu(self, position):
        """Expose secondary actions without competing with the task summary."""
        item = self.dashboard_list.itemAt(position)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return

        os_window, tab, _ = data
        from PyQt5.QtWidgets import QMenu

        menu = QMenu(self)
        jump_action = menu.addAction("跳转到此任务")
        jump_action.triggered.connect(lambda: self._dashboard_jump(item))
        close_action = menu.addAction("关闭 Tab")
        close_action.triggered.connect(lambda: self._dashboard_close(item))
        menu.addSeparator()
        ignore_action = menu.addAction(
            "取消忽略此窗口" if os_window.socket in self.ignored_windows else "忽略此窗口"
        )
        ignore_action.triggered.connect(lambda: self.toggle_ignore_window(os_window.socket))
        menu.exec_(self.dashboard_list.mapToGlobal(position))

    def update_window_list(self):
        """更新窗口列表"""
        # 保存当前选中的窗口
        old_socket = None
        if self.current_window:
            old_socket = self.current_window.socket

        self.window_list.clear()

        for win in self.windows:
            # 将每个 Kitty window 当前打开的 tab 放在标记前部，避免被截断
            focused_tab = next((tab for tab in win.tabs if tab.is_focused), None)
            if focused_tab:
                title = f"▶ Tab {focused_tab.tab_id} · {win.socket_label}"
            else:
                title = win.socket_label

            # 添加状态标记
            if win.socket in self.ignored_windows:
                title = f"🚫 {title}"  # 忽略标记
            elif win.is_focused:
                title = f"● {title}"
            elif win.socket in self.visited_windows:
                title = f"✓ {title}"  # 访问过的标记

            item = QListWidgetItem(title)
            
            # 设置数据
            item.setData(Qt.UserRole, win)

            # 设置颜色和样式
            if win.socket in self.ignored_windows:
                item.setForeground(QColor('#666'))  # 灰色 - 忽略
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
            elif win.is_focused:
                item.setForeground(QColor('#4fc3f7'))  # 亮蓝色
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            elif win.socket in self.visited_windows:
                item.setForeground(QColor('#81c784'))  # 淡绿色 - 访问过

            self.window_list.addItem(item)

        # 恢复之前选中的窗口，如果不存在则选中第一个
        restored = False
        if old_socket:
            for i, win in enumerate(self.windows):
                if win.socket == old_socket:
                    self.window_list.setCurrentRow(i)
                    self.on_window_selected(self.window_list.item(i))
                    restored = True
                    break

        # 如果没有恢复成功，选中第一个窗口
        if not restored and len(self.windows) > 0:
            self.window_list.setCurrentRow(0)
            self.on_window_selected(self.window_list.item(0))

    def update_tab_list(self):
        """更新 Tab 列表"""
        self.tab_list.clear()

        if not self.current_window:
            return

        for tab in self.current_window.tabs:
            # Tab 标题 - 简化格式
            prefix = "▶ " if tab.is_focused else ""
            title = f"{prefix}Tab {tab.tab_id}: {tab.title}"

            # 添加 AI 进程信息 - 只显示简要信息
            if tab.ai_processes:
                ai_info = "\n".join(
                    f"  ● {proc.display_name} → {proc.short_cwd}"
                    for proc in tab.ai_processes
                )
                title += "\n" + ai_info

            item = QTreeWidgetItem([title, '×'])
            item.setData(0, Qt.UserRole, tab)

            # 高亮当前聚焦的 tab
            if tab.is_focused:
                item.setForeground(0, QColor('#81c784'))  # 亮绿色
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)

            item.setTextAlignment(1, Qt.AlignCenter)
            item.setForeground(1, QColor('#ef5350'))
            self.tab_list.addTopLevelItem(item)

    def on_window_selected(self, item):
        """当选中窗口时"""
        if item:
            self.current_window = item.data(Qt.UserRole)
            self.update_tab_list()

    def on_window_changed(self, current, previous):
        """当窗口列表的当前项改变时（包括键盘导航）"""
        if current:
            self.on_window_selected(current)

    def show_window_context_menu(self, position):
        """显示窗口的右键菜单"""
        item = self.window_list.itemAt(position)
        if not item:
            return

        window = item.data(Qt.UserRole)
        if not window:
            return

        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)

        # 检查窗口是否有 AI 进程
        has_ai = any(len(tab.ai_processes) > 0 for tab in window.tabs)

        if window.socket in self.ignored_windows:
            # 已忽略 - 显示取消忽略
            action = menu.addAction(f"✓ 取消忽略 {window.socket_label}")
            action.triggered.connect(lambda: self.toggle_ignore_window(window.socket))
        else:
            # 未忽略
            if not has_ai:
                # 没有 AI 进程 - 推荐忽略
                action = menu.addAction(f"🚫 忽略 {window.socket_label} (无 AI)")
            else:
                action = menu.addAction(f"🚫 忽略 {window.socket_label}")
            action.triggered.connect(lambda: self.toggle_ignore_window(window.socket))

        menu.exec_(self.window_list.mapToGlobal(position))

    def on_tab_clicked(self, item, column):
        """单击 Tab 内容跳转，单击右侧关闭按钮关闭。"""
        tab = item.data(0, Qt.UserRole)
        if self.current_window and tab:
            if column == 1:
                self.close_tab(self.current_window, tab)
            else:
                self.jump_to_tab(self.current_window, tab)

    def close_tab(self, os_win: OSWindowStatus, tab: TabStatus):
        """关闭指定 tab"""
        try:
            # 使用 kitty @ close-tab 命令
            result = subprocess.run(
                ['kitty', '@', '--to', os_win.socket, 'close-tab', '--match', f'id:{tab.tab_id}'],
                capture_output=True,
                text=True,
                timeout=3,
                check=True
            )
            print(f"[DEBUG] Tab {tab.tab_id} 已关闭")

            # 刷新数据
            self.load_data()

        except subprocess.CalledProcessError as e:
            error_msg = f"关闭失败 (返回码 {e.returncode}): {e.stderr}"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            self.status_label.setText(error_msg)
        except Exception as e:
            error_msg = f"关闭失败: {e}"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            self.status_label.setText(error_msg)

    def jump_to_tab(self, os_win: OSWindowStatus, tab: TabStatus):
        """跳转到指定 tab"""
        try:
            # 获取 Kitty 窗口的 X11 window ID
            ls_result = subprocess.run(
                ['kitty', '@', '--to', os_win.socket, 'ls'],
                capture_output=True,
                text=True,
                timeout=3
            )

            platform_window_id = None
            if ls_result.returncode == 0:
                import json
                ls_data = json.loads(ls_result.stdout)
                if ls_data and len(ls_data) > 0:
                    platform_window_id = ls_data[0].get('platform_window_id')

            # 激活 Kitty 窗口
            if platform_window_id:
                subprocess.run(
                    ['wmctrl', '-i', '-a', str(platform_window_id)],
                    capture_output=True,
                    timeout=2
                )
                print(f"[DEBUG] 系统窗口激活: {platform_window_id}")

            # 给系统一点时间处理窗口切换
            import time
            time.sleep(0.1)

            # 聚焦到指定的 tab
            result = subprocess.run(
                ['kitty', '@', '--to', os_win.socket, 'focus-tab', '--match', f'id:{tab.tab_id}'],
                capture_output=True,
                text=True,
                timeout=3,
                check=True
            )
            print(f"[DEBUG] Tab 聚焦成功: Tab {tab.tab_id}")

            # 标记窗口为已访问
            self.mark_window_visited(os_win.socket)

            # 更新状态栏
            self.status_label.setText(f"已跳转到 Tab {tab.tab_id}")

            # 刷新窗口列表以显示访问标记
            self.update_window_list()

        except subprocess.CalledProcessError as e:
            error_msg = f"跳转失败 (返回码 {e.returncode}): {e.stderr}"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            self.status_label.setText(error_msg)
        except Exception as e:
            error_msg = f"跳转失败: {e}"
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            self.status_label.setText(error_msg)


def _run_gui() -> int:
    import signal

    global _instance_lock
    _instance_lock = _acquire_instance_lock()
    if _instance_lock is None:
        return 0

    app = QApplication(sys.argv)

    # 设置应用样式
    app.setStyle('Fusion')

    window = WorkStatusGUI()
    window.show()

    # 设置信号处理，让 Ctrl+C 能够正确退出
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # 创建一个定时器让 Python 能处理信号
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    try:
        return app.exec_()
    finally:
        _instance_lock.close()
        _instance_lock = None


def main() -> int:
    if os.environ.get(_BACKGROUND_ENV) == "1":
        return _run_gui()
    if _instance_is_running():
        return 0
    return _launch_background()


if __name__ == '__main__':
    raise SystemExit(main())
