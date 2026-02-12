"""数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4


@dataclass
class Task:
    """任务模型

    每个任务对应一个独立的 tmux 会话，会话名为 cm-{task_id}
    """
    task_id: str  # 用户指定的短 ID，如 "ml"、"test"
    name: str
    cwd: str
    description: str = ""
    status: Literal['pending', 'running', 'completed', 'failed'] = 'pending'
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def session_name(self) -> str:
        """tmux 会话名"""
        return f"cm-{self.task_id}"

    def to_dict(self) -> dict:
        return {
            'task_id': self.task_id,
            'name': self.name,
            'status': self.status,
            'cwd': self.cwd,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Task':
        return cls(
            task_id=data['task_id'],
            name=data['name'],
            status=data.get('status', 'pending'),
            cwd=data['cwd'],
            description=data.get('description', ''),
            created_at=datetime.fromisoformat(data['created_at']),
        )


@dataclass
class Terminal:
    """终端模型"""
    name: str
    type: Literal['claude', 'shell', 'ros2', 'rqt', 'custom']
    command: str
    cwd: str
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    kitty_window_id: Optional[int] = None
    pid: Optional[int] = None
    status: Literal['running', 'stopped', 'error'] = 'stopped'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'command': self.command,
            'cwd': self.cwd,
            'kitty_window_id': self.kitty_window_id,
            'pid': self.pid,
            'status': self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Terminal':
        return cls(
            id=data['id'],
            name=data['name'],
            type=data['type'],
            command=data['command'],
            cwd=data['cwd'],
            kitty_window_id=data.get('kitty_window_id'),
            pid=data.get('pid'),
            status=data.get('status', 'stopped'),
        )


@dataclass
class TerminalConfig:
    """终端配置（用于布局预设）"""
    type: str
    command: str
    name: str = ""
    split: Literal['vsplit', 'hsplit', 'none'] = 'none'
    ratio: float = 0.5


@dataclass
class Layout:
    """布局预设"""
    name: str
    description: str = ""
    terminals: list[TerminalConfig] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'description': self.description,
            'terminals': [
                {
                    'type': t.type,
                    'command': t.command,
                    'name': t.name,
                    'split': t.split,
                    'ratio': t.ratio,
                }
                for t in self.terminals
            ],
        }


# 终端预设模板
TERMINAL_PRESETS = {
    'claude': TerminalConfig(type='claude', command='claude', name='Claude'),
    'shell': TerminalConfig(type='shell', command='bash', name='Shell'),
    'ros2_bag': TerminalConfig(type='ros2', command='ros2 bag play', name='ROS2 Bag'),
    'ros2_topic': TerminalConfig(type='ros2', command='ros2 topic echo', name='Topic Echo'),
    'rqt': TerminalConfig(type='rqt', command='rqt', name='RQT'),
    'rviz2': TerminalConfig(type='ros2', command='rviz2', name='RViz2'),
}

# 布局预设
DEFAULT_LAYOUTS = {
    'focus': Layout(
        name='专注模式',
        description='左侧面板 + 单终端',
        terminals=[
            TerminalConfig(type='claude', command='claude', name='Claude', split='none'),
        ]
    ),
    'develop': Layout(
        name='开发模式',
        description='左侧面板 + Claude + Shell',
        terminals=[
            TerminalConfig(type='claude', command='claude', name='Claude', split='none'),
            TerminalConfig(type='shell', command='bash', name='Shell', split='hsplit', ratio=0.3),
        ]
    ),
    'test': Layout(
        name='测试模式',
        description='左侧面板 + Claude + Bag + Viz',
        terminals=[
            TerminalConfig(type='claude', command='claude', name='Claude', split='none'),
            TerminalConfig(type='ros2', command='ros2 bag play', name='Bag', split='hsplit', ratio=0.5),
            TerminalConfig(type='ros2', command='rqt', name='RQT', split='vsplit', ratio=0.5),
        ]
    ),
    'monitor': Layout(
        name='监控模式',
        description='左侧面板 + 4终端网格',
        terminals=[
            TerminalConfig(type='shell', command='bash', name='Term 1', split='none'),
            TerminalConfig(type='shell', command='bash', name='Term 2', split='vsplit', ratio=0.5),
            TerminalConfig(type='shell', command='bash', name='Term 3', split='hsplit', ratio=0.5),
            TerminalConfig(type='shell', command='bash', name='Term 4', split='vsplit', ratio=0.5),
        ]
    ),
}
