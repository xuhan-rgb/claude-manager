"""模型测试"""

import pytest
from datetime import datetime

from claude_manager.models import Task, Terminal, Layout, TerminalConfig


class TestTask:
    """Task 模型测试"""

    def test_create_task(self):
        task = Task(task_id="test", name="测试任务", cwd="/tmp")
        assert task.name == "测试任务"
        assert task.cwd == "/tmp"
        assert task.status == "pending"
        assert task.task_id == "test"

    def test_task_to_dict(self):
        task = Task(task_id="t1", name="测试", cwd="/tmp", description="说明")
        data = task.to_dict()
        assert data["name"] == "测试"
        assert data["cwd"] == "/tmp"
        assert data["status"] == "pending"
        assert data["description"] == "说明"

    def test_task_from_dict(self):
        data = {
            "task_id": "abc123",
            "name": "测试",
            "status": "running",
            "cwd": "/tmp",
            "description": "描述",
            "created_at": datetime.now().isoformat(),
        }
        task = Task.from_dict(data)
        assert task.task_id == "abc123"
        assert task.name == "测试"
        assert task.status == "running"
        assert task.description == "描述"


class TestTerminal:
    """Terminal 模型测试"""

    def test_create_terminal(self):
        terminal = Terminal(
            name="Claude",
            type="claude",
            command="claude",
            cwd="/tmp",
        )
        assert terminal.name == "Claude"
        assert terminal.type == "claude"
        assert terminal.status == "stopped"

    def test_terminal_to_dict(self):
        terminal = Terminal(
            name="Shell",
            type="shell",
            command="bash",
            cwd="/home",
        )
        data = terminal.to_dict()
        assert data["name"] == "Shell"
        assert data["type"] == "shell"
        assert data["command"] == "bash"


class TestLayout:
    """Layout 模型测试"""

    def test_create_layout(self):
        layout = Layout(
            name="测试布局",
            description="用于测试",
            terminals=[
                TerminalConfig(type="claude", command="claude", name="Claude"),
            ],
        )
        assert layout.name == "测试布局"
        assert len(layout.terminals) == 1

    def test_layout_to_dict(self):
        layout = Layout(
            name="开发",
            terminals=[
                TerminalConfig(type="shell", command="bash", name="Shell"),
            ],
        )
        data = layout.to_dict()
        assert data["name"] == "开发"
        assert len(data["terminals"]) == 1
