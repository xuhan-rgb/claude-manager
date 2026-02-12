"""终端适配器抽象接口

定义终端操作的统一接口，支持不同终端（Kitty、iTerm2、纯 tmux）的适配。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class WindowInfo:
    """窗口信息（通用）

    Attributes:
        id: 窗口标识符（各终端格式不同：Kitty 用 int，tmux 用 pane ID）
        columns: 列数（宽度）
        lines: 行数（高度）
        tty: TTY 设备路径（如 /dev/pts/0）
        is_focused: 是否聚焦
        title: 窗口标题
        pid: 进程 ID
        cwd: 当前工作目录
    """
    id: str
    columns: int = 0
    lines: int = 0
    tty: Optional[str] = None
    is_focused: bool = False
    title: str = ""
    pid: int = 0
    cwd: str = ""


@dataclass
class SplitResult:
    """分屏操作结果

    Attributes:
        success: 是否成功
        window_id: 新窗口的 ID
        error: 错误信息
    """
    success: bool
    window_id: Optional[str] = None
    error: Optional[str] = None


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
class LayoutConfig:
    """布局配置

    Attributes:
        direction: 分屏方向（vertical=左右, horizontal=上下）
        panels: 面板配置列表
    """
    direction: str = "vertical"
    panels: List[PanelConfig] = field(default_factory=list)


class TerminalAdapter(ABC):
    """终端适配器抽象接口

    所有终端适配器（Kitty、iTerm2、纯 tmux）必须实现此接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """适配器名称（如 'kitty', 'iterm', 'tmux'）"""
        pass

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """检查终端是否可用

        Returns:
            (是否可用, 错误信息或版本信息)
        """
        pass

    # ========== 窗口操作 ==========

    @abstractmethod
    def create_split(
        self,
        direction: str = "vertical",
        command: str = "bash",
        cwd: Optional[str] = None
    ) -> SplitResult:
        """创建分屏窗口

        Args:
            direction: 分屏方向
                - "vertical": 垂直分屏（左右排列）
                - "horizontal": 水平分屏（上下排列）
            command: 新窗口要执行的命令
            cwd: 工作目录

        Returns:
            SplitResult 包含成功状态和新窗口 ID
        """
        pass

    @abstractmethod
    def close_window(self, window_id: str) -> bool:
        """关闭窗口

        Args:
            window_id: 窗口 ID

        Returns:
            是否成功
        """
        pass

    @abstractmethod
    def focus_window(self, window_id: str) -> bool:
        """聚焦窗口

        Args:
            window_id: 窗口 ID

        Returns:
            是否成功
        """
        pass

    @abstractmethod
    def resize_window(
        self,
        window_id: str,
        columns: Optional[int] = None,
        increment: Optional[int] = None,
        axis: str = "horizontal"
    ) -> bool:
        """调整窗口大小

        Args:
            window_id: 窗口 ID
            columns: 目标列数（绝对值）
            increment: 增量（正数增大，负数减小）
            axis: 调整轴向（horizontal=宽度, vertical=高度）

        Returns:
            是否成功

        Note:
            columns 和 increment 二选一，优先使用 columns
        """
        pass

    @abstractmethod
    def send_text(self, text: str, window_id: Optional[str] = None) -> bool:
        """向窗口发送文本

        Args:
            text: 要发送的文本
            window_id: 窗口 ID，None 表示当前窗口

        Returns:
            是否成功
        """
        pass

    # ========== 信息获取 ==========

    @abstractmethod
    def get_window_info(self, window_id: str) -> Optional[WindowInfo]:
        """获取窗口信息

        Args:
            window_id: 窗口 ID

        Returns:
            WindowInfo 或 None
        """
        pass

    @abstractmethod
    def get_current_window(self) -> Optional[WindowInfo]:
        """获取当前聚焦的窗口

        Returns:
            WindowInfo 或 None
        """
        pass

    @abstractmethod
    def list_windows(self) -> List[WindowInfo]:
        """列出当前 Tab/会话中的所有窗口

        Returns:
            WindowInfo 列表
        """
        pass

    @abstractmethod
    def get_total_columns(self) -> int:
        """获取当前 Tab/会话的总列数

        Returns:
            总列数
        """
        pass

    # ========== 布局管理 ==========

    @abstractmethod
    def set_layout(self, layout: str) -> bool:
        """设置布局模式

        Args:
            layout: 布局名称（如 'splits', 'stack', 'tall'）
                   不同终端支持的布局不同

        Returns:
            是否成功
        """
        pass

    @abstractmethod
    def lock_layout(self, layouts: List[str]) -> bool:
        """锁定可用布局

        Args:
            layouts: 允许的布局列表

        Returns:
            是否成功

        Note:
            某些终端可能不支持此功能，返回 True 表示忽略
        """
        pass

    # ========== 辅助方法 ==========

    def get_window_tty(self, window_id: str) -> Optional[str]:
        """获取窗口的 TTY 设备路径

        Args:
            window_id: 窗口 ID

        Returns:
            TTY 路径（如 /dev/pts/0）或 None
        """
        info = self.get_window_info(window_id)
        return info.tty if info else None

    def get_window_columns(self, window_id: str) -> int:
        """获取窗口列数

        Args:
            window_id: 窗口 ID

        Returns:
            列数，失败返回 0
        """
        info = self.get_window_info(window_id)
        return info.columns if info else 0
