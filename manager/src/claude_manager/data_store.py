"""数据存储模块"""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

from .models import Task, Terminal, Layout, TerminalConfig


class DataStore:
    """数据存储管理

    使用 JSON 文件存储任务、终端、会话数据。
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """初始化数据存储

        Args:
            data_dir: 数据目录，默认为 ~/.local/share/claude-manager/data
        """
        if data_dir is None:
            data_dir = Path.home() / '.local' / 'share' / 'claude-manager' / 'data'

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.tasks_file = self.data_dir / 'tasks.json'
        self.terminals_file = self.data_dir / 'terminals.json'
        self.session_file = self.data_dir / 'session.json'

    # ==================== 任务管理 ====================

    def load_tasks(self) -> list[Task]:
        """加载所有任务"""
        if not self.tasks_file.exists():
            return []

        try:
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [Task.from_dict(t) for t in data]
        except (json.JSONDecodeError, KeyError):
            return []

    def save_tasks(self, tasks: list[Task]) -> None:
        """保存所有任务"""
        data = [t.to_dict() for t in tasks]
        with open(self.tasks_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_task(self, task: Task) -> None:
        """添加任务"""
        tasks = self.load_tasks()
        tasks.append(task)
        self.save_tasks(tasks)

    def update_task(self, task: Task) -> bool:
        """更新任务"""
        tasks = self.load_tasks()
        for i, t in enumerate(tasks):
            if t.task_id == task.task_id:
                tasks[i] = task
                self.save_tasks(tasks)
                return True
        return False

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        tasks = self.load_tasks()
        original_len = len(tasks)
        tasks = [t for t in tasks if t.task_id != task_id]
        if len(tasks) < original_len:
            self.save_tasks(tasks)
            return True
        return False

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取单个任务"""
        for task in self.load_tasks():
            if task.task_id == task_id:
                return task
        return None

    # ==================== 终端管理 ====================

    def load_terminals(self) -> list[Terminal]:
        """加载所有终端配置"""
        if not self.terminals_file.exists():
            return []

        try:
            with open(self.terminals_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [Terminal.from_dict(t) for t in data]
        except (json.JSONDecodeError, KeyError):
            return []

    def save_terminals(self, terminals: list[Terminal]) -> None:
        """保存所有终端配置"""
        data = [t.to_dict() for t in terminals]
        with open(self.terminals_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_terminal(self, terminal: Terminal) -> None:
        """添加终端"""
        terminals = self.load_terminals()
        terminals.append(terminal)
        self.save_terminals(terminals)

    def update_terminal(self, terminal: Terminal) -> bool:
        """更新终端"""
        terminals = self.load_terminals()
        for i, t in enumerate(terminals):
            if t.id == terminal.id:
                terminals[i] = terminal
                self.save_terminals(terminals)
                return True
        return False

    def delete_terminal(self, terminal_id: str) -> bool:
        """删除终端"""
        terminals = self.load_terminals()
        original_len = len(terminals)
        terminals = [t for t in terminals if t.id != terminal_id]
        if len(terminals) < original_len:
            self.save_terminals(terminals)
            return True
        return False

    def get_terminal(self, terminal_id: str) -> Optional[Terminal]:
        """获取单个终端"""
        for terminal in self.load_terminals():
            if terminal.id == terminal_id:
                return terminal
        return None

    # ==================== 会话管理 ====================

    def save_session(self, session_data: dict) -> None:
        """保存会话状态"""
        session_data['saved_at'] = datetime.now().isoformat()
        with open(self.session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

    def load_session(self) -> Optional[dict]:
        """加载上次会话状态"""
        if not self.session_file.exists():
            return None

        try:
            with open(self.session_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return None

    def clear_session(self) -> None:
        """清除会话状态"""
        if self.session_file.exists():
            self.session_file.unlink()

    # ==================== 布局管理 ====================

    def get_layouts_dir(self) -> Path:
        """获取布局配置目录"""
        layouts_dir = self.data_dir.parent / 'config' / 'layouts'
        layouts_dir.mkdir(parents=True, exist_ok=True)
        return layouts_dir

    def save_layout(self, layout: Layout) -> None:
        """保存布局预设"""
        import yaml
        layout_file = self.get_layouts_dir() / f"{layout.name}.yaml"
        with open(layout_file, 'w', encoding='utf-8') as f:
            yaml.dump(layout.to_dict(), f, allow_unicode=True)

    def load_layout(self, name: str) -> Optional[Layout]:
        """加载布局预设"""
        import yaml
        layout_file = self.get_layouts_dir() / f"{name}.yaml"
        if not layout_file.exists():
            return None

        try:
            with open(layout_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                terminals = [
                    TerminalConfig(**t) for t in data.get('terminals', [])
                ]
                return Layout(
                    name=data['name'],
                    description=data.get('description', ''),
                    terminals=terminals,
                )
        except (yaml.YAMLError, KeyError):
            return None

    def list_layouts(self) -> list[str]:
        """列出所有布局预设"""
        layouts_dir = self.get_layouts_dir()
        return [f.stem for f in layouts_dir.glob('*.yaml')]
