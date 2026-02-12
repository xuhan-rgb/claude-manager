"""配置管理模块"""

import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# 默认配置文件路径
DEFAULT_CONFIG_PATH = Path.home() / '.config' / 'claude-manager' / 'config.yaml'
TERMINAL_CONFIG_PATH = Path.home() / '.config' / 'claude-manager' / 'terminal.yaml'


@dataclass
class StatusConfig:
    """状态检测配置"""
    check_interval: float = 1.0          # 状态检测间隔（秒）
    active_threshold: float = 1.0        # activity_ago < 此值判断为活跃
    continuous_duration: float = 2.0     # 连续活跃多少秒后判断为 running


@dataclass
class UIConfig:
    """界面配置"""
    left_panel_columns: int = 35         # 左侧面板宽度（列）
    min_right_columns: int = 80          # 右侧最小宽度（列）


# ========== 终端配置 ==========

@dataclass
class PanelConfig:
    """面板配置

    Attributes:
        name: 面板名称（如 tui, main_tmux, cmd_tmux）
        ratio: 宽度比例（0.0 ~ 1.0）
        min_columns: 最小列数
        max_columns: 最大列数（0 表示无限制）
        command: 启动命令（支持 {session}, {cmd_session} 占位符）
        optional: 是否可选（终端宽度不足时可跳过）
    """
    name: str
    ratio: float = 0.33
    min_columns: int = 20
    max_columns: int = 0
    command: str = "bash"
    optional: bool = False


@dataclass
class TerminalLayoutConfig:
    """终端布局配置

    Attributes:
        direction: 分屏方向（vertical=左右, horizontal=上下）
        panels: 面板配置列表
    """
    direction: str = "vertical"
    panels: List[PanelConfig] = field(default_factory=list)


@dataclass
class TerminalConfig:
    """终端配置

    Attributes:
        terminal: 终端类型（auto, kitty, iterm, xterm, terminator）
        layout: 布局配置
        term_map: TERM 到终端类型的映射
        terminator: Terminator 配置
    """
    terminal: str = "auto"
    layout: TerminalLayoutConfig = field(default_factory=TerminalLayoutConfig)
    term_map: dict = field(default_factory=dict)
    terminator: dict = field(default_factory=dict)


# 默认面板配置
DEFAULT_PANELS = [
    PanelConfig(
        name="tui",
        ratio=0.20,
        min_columns=30,
        max_columns=50,
        command="",  # TUI 在当前窗口运行
        optional=False,
    ),
    PanelConfig(
        name="main_tmux",
        ratio=0.53,
        min_columns=60,
        max_columns=0,
        command="tmux attach -d -t {session}",
        optional=False,
    ),
    PanelConfig(
        name="cmd_tmux",
        ratio=0.27,
        min_columns=40,
        max_columns=0,
        command="tmux attach -t {cmd_session}",
        optional=True,
    ),
]


def load_terminal_config(config_path: Path = None) -> TerminalConfig:
    """加载终端配置

    Args:
        config_path: 配置文件路径，默认 ~/.config/claude-manager/terminal.yaml

    Returns:
        TerminalConfig 对象
    """
    path = config_path or TERMINAL_CONFIG_PATH
    config = TerminalConfig(
        layout=TerminalLayoutConfig(
            direction="vertical",
            panels=DEFAULT_PANELS.copy(),
        )
    )

    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            # 解析终端类型
            config.terminal = data.get('terminal', 'auto')
            config.term_map = data.get('term_map', {}) or {}
            config.terminator = data.get('terminator', {}) or {}

            # 解析布局配置
            if 'layout' in data:
                layout_data = data['layout']
                config.layout.direction = layout_data.get('direction', 'vertical')

                if 'panels' in layout_data:
                    panels = []
                    for panel_data in layout_data['panels']:
                        panels.append(PanelConfig(
                            name=panel_data.get('name', 'unknown'),
                            ratio=panel_data.get('ratio', 0.33),
                            min_columns=panel_data.get('min_columns', 20),
                            max_columns=panel_data.get('max_columns', 0),
                            command=panel_data.get('command', 'bash'),
                            optional=panel_data.get('optional', False),
                        ))
                    config.layout.panels = panels

            logger.info(f"[终端配置] 已加载: {path}")
        except Exception as e:
            logger.warning(f"[终端配置] 加载失败，使用默认值: {e}")
    else:
        logger.info(f"[终端配置] 文件不存在，使用默认值: {path}")

    return config


def save_terminal_config(config: TerminalConfig, config_path: Path = None) -> None:
    """保存终端配置

    Args:
        config: TerminalConfig 对象
        config_path: 配置文件路径
    """
    path = config_path or TERMINAL_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        'terminal': config.terminal,
        'term_map': config.term_map or {},
        'terminator': config.terminator or {},
        'layout': {
            'direction': config.layout.direction,
            'panels': [
                {
                    'name': p.name,
                    'ratio': p.ratio,
                    'min_columns': p.min_columns,
                    'max_columns': p.max_columns,
                    'command': p.command,
                    'optional': p.optional,
                }
                for p in config.layout.panels
            ],
        },
    }

    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"[终端配置] 已保存: {path}")


def save_default_terminal_config(config_path: Path = None) -> None:
    """保存默认终端配置文件

    Args:
        config_path: 配置文件路径
    """
    path = config_path or TERMINAL_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    default_yaml = """# Claude Manager 终端配置

# 终端类型：auto（自动检测）, kitty, iterm, xterm, terminator
terminal: auto

# TERM 映射（可选，用于覆盖自动检测）
term_map:
  xterm-kitty: kitty
  xterm-256color: xterm

# Terminator 配置
terminator:
  # layout: auto 表示自动生成并使用内部分屏布局
  # layout: <name> 表示使用你已有的 Terminator 布局名
  layout: auto
  # columns: 左侧面板占比（0.0 ~ 1.0）
  columns: 0.68
  # 窗口初始宽高（像素）
  width: 1200
  height: 800

# 分屏布局配置
layout:
  # 分屏方向：vertical（左右）, horizontal（上下）
  direction: vertical

  # 面板配置列表
  panels:
    # TUI 面板（管理器界面）
    - name: tui
      ratio: 0.20           # 20% 宽度
      min_columns: 30
      max_columns: 50
      command: ""           # TUI 在当前窗口运行，无需命令
      optional: false

    # 主 tmux 窗口（Claude 工作区）
    - name: main_tmux
      ratio: 0.53           # 53% 宽度
      min_columns: 60
      command: "tmux attach -d -t {session}"
      optional: false

    # 命令 tmux 窗口（可选）
    - name: cmd_tmux
      ratio: 0.27           # 27% 宽度
      min_columns: 40
      command: "tmux attach -t {cmd_session}"
      optional: true        # 终端宽度不足时可跳过
"""

    with open(path, 'w', encoding='utf-8') as f:
        f.write(default_yaml)

    logger.info(f"[终端配置] 已生成默认配置: {path}")


# 全局终端配置实例
_terminal_config: TerminalConfig = None


def get_terminal_config() -> TerminalConfig:
    """获取全局终端配置（懒加载）"""
    global _terminal_config
    if _terminal_config is None:
        _terminal_config = load_terminal_config()
    return _terminal_config


def reload_terminal_config() -> TerminalConfig:
    """重新加载终端配置"""
    global _terminal_config
    _terminal_config = load_terminal_config()
    return _terminal_config


@dataclass
class LayoutConfig:
    """窗口布局配置（记住上次的宽度）"""
    left_columns: int = 35               # 左侧 TUI 面板宽度
    middle_columns: int = 0              # 中间 tmux 窗口宽度（0 表示自动计算）
    right_columns: int = 0               # 右侧 tmux 窗口宽度（0 表示自动计算）
    total_columns: int = 0               # 总宽度（用于检测终端大小变化）


@dataclass
class Config:
    """主配置"""
    status: StatusConfig = field(default_factory=StatusConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def load_config(config_path: Path = None) -> Config:
    """加载配置文件

    Args:
        config_path: 配置文件路径，默认 ~/.config/claude-manager/config.yaml

    Returns:
        Config 对象
    """
    path = config_path or DEFAULT_CONFIG_PATH
    config = Config()

    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            # 解析 status 配置
            if 'status' in data:
                status_data = data['status']
                config.status = StatusConfig(
                    check_interval=status_data.get('check_interval', 1.0),
                    active_threshold=status_data.get('active_threshold', 1.0),
                    continuous_duration=status_data.get('continuous_duration', 2.0),
                )

            # 解析 ui 配置
            if 'ui' in data:
                ui_data = data['ui']
                config.ui = UIConfig(
                    left_panel_columns=ui_data.get('left_panel_columns', 35),
                    min_right_columns=ui_data.get('min_right_columns', 80),
                )

            logger.info(f"[配置] 已加载: {path}")
        except Exception as e:
            logger.warning(f"[配置] 加载失败，使用默认值: {e}")
    else:
        logger.info(f"[配置] 文件不存在，使用默认值: {path}")

    return config


def save_default_config(config_path: Path = None) -> None:
    """保存默认配置文件（用于生成示例）

    Args:
        config_path: 配置文件路径
    """
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    default_yaml = """# Claude Manager 配置文件

# 状态检测配置
status:
  check_interval: 1.0        # 状态检测间隔（秒）
  active_threshold: 1.0      # activity_ago < 此值判断为活跃
  continuous_duration: 2.0   # 连续活跃多少秒后判断为 running

# 界面配置
ui:
  left_panel_columns: 35     # 左侧面板宽度（列）
  min_right_columns: 80      # 右侧最小宽度（列）
"""

    with open(path, 'w', encoding='utf-8') as f:
        f.write(default_yaml)

    logger.info(f"[配置] 已生成默认配置: {path}")


# 全局配置实例
_config: Config = None


def get_config() -> Config:
    """获取全局配置（懒加载）"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """重新加载配置"""
    global _config
    _config = load_config()
    return _config


# 布局配置文件路径
LAYOUT_CONFIG_PATH = Path.home() / '.config' / 'claude-manager' / 'layout.yaml'


def load_layout() -> LayoutConfig:
    """加载窗口布局配置

    Returns:
        LayoutConfig 对象
    """
    layout = LayoutConfig()

    if LAYOUT_CONFIG_PATH.exists():
        try:
            with open(LAYOUT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            layout = LayoutConfig(
                left_columns=data.get('left_columns', 35),
                middle_columns=data.get('middle_columns', 0),
                right_columns=data.get('right_columns', 0),
                total_columns=data.get('total_columns', 0),
            )
            logger.debug(f"[布局] 已加载: {LAYOUT_CONFIG_PATH}")
        except Exception as e:
            logger.warning(f"[布局] 加载失败，使用默认值: {e}")

    return layout


def save_layout(left: int, middle: int, right: int, total: int) -> None:
    """保存窗口布局配置

    Args:
        left: 左侧宽度
        middle: 中间宽度
        right: 右侧宽度
        total: 总宽度
    """
    LAYOUT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    data = {
        'left_columns': left,
        'middle_columns': middle,
        'right_columns': right,
        'total_columns': total,
    }

    with open(LAYOUT_CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False)

    logger.debug(f"[布局] 已保存: 左={left}, 中={middle}, 右={right}, 总={total}")
