"""进程监控模块"""

import psutil
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Optional


@dataclass
class ProcessInfo:
    """进程信息"""
    pid: int
    name: str
    cmdline: list[str]
    cwd: str
    create_time: datetime
    status: str
    cpu_percent: float
    memory_percent: float

    @property
    def running_time(self) -> str:
        """获取运行时长的友好显示"""
        delta = datetime.now() - self.create_time
        total_seconds = int(delta.total_seconds())

        if total_seconds < 60:
            return f"{total_seconds}秒"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes}分钟"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}小时{minutes}分钟"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days}天{hours}小时"

    @property
    def command_display(self) -> str:
        """获取命令的简短显示"""
        if not self.cmdline:
            return self.name
        cmd = ' '.join(self.cmdline)
        if len(cmd) > 50:
            return cmd[:47] + '...'
        return cmd


class ProcessMonitor:
    """进程监控器

    监控系统中运行的 Claude、ROS2、rqt 等进程。
    """

    # 要监控的进程名称模式
    MONITORED_PATTERNS = [
        'claude',
        'ros2',
        'rqt',
        'rviz2',
        'gazebo',
    ]

    def __init__(self, patterns: Optional[list[str]] = None):
        """初始化监控器

        Args:
            patterns: 要监控的进程名称模式列表
        """
        self.patterns = patterns or self.MONITORED_PATTERNS

    def find_processes(self, pattern: Optional[str] = None) -> Iterator[ProcessInfo]:
        """查找匹配的进程

        Args:
            pattern: 进程名称模式，None 表示使用所有默认模式

        Yields:
            匹配的进程信息
        """
        patterns = [pattern] if pattern else self.patterns

        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'create_time', 'status']):
            try:
                info = proc.info
                name = info.get('name', '').lower()
                cmdline = info.get('cmdline') or []
                cmdline_str = ' '.join(cmdline).lower()

                # 检查是否匹配任一模式
                matched = False
                for p in patterns:
                    p_lower = p.lower()
                    if p_lower in name or p_lower in cmdline_str:
                        matched = True
                        break

                if matched:
                    # 获取额外信息（不阻塞）
                    try:
                        # 使用 interval=None 避免阻塞，返回上次调用以来的 CPU 使用率
                        cpu = proc.cpu_percent(interval=None)
                        mem = proc.memory_percent()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        cpu = 0.0
                        mem = 0.0

                    create_time = info.get('create_time')
                    if create_time:
                        create_time = datetime.fromtimestamp(create_time)
                    else:
                        create_time = datetime.now()

                    yield ProcessInfo(
                        pid=info['pid'],
                        name=info.get('name', 'unknown'),
                        cmdline=cmdline,
                        cwd=info.get('cwd', ''),
                        create_time=create_time,
                        status=info.get('status', 'unknown'),
                        cpu_percent=cpu,
                        memory_percent=mem,
                    )

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    def find_claude_processes(self) -> list[ProcessInfo]:
        """查找所有 Claude 进程"""
        return list(self.find_processes('claude'))

    def find_ros2_processes(self) -> list[ProcessInfo]:
        """查找所有 ROS2 相关进程"""
        processes = []
        for pattern in ['ros2', 'rqt', 'rviz2', 'gazebo']:
            processes.extend(self.find_processes(pattern))
        # 去重
        seen_pids = set()
        unique = []
        for p in processes:
            if p.pid not in seen_pids:
                seen_pids.add(p.pid)
                unique.append(p)
        return unique

    def get_all_monitored(self) -> list[ProcessInfo]:
        """获取所有被监控的进程"""
        processes = list(self.find_processes())
        # 按创建时间排序
        processes.sort(key=lambda p: p.create_time, reverse=True)
        return processes

    def is_process_alive(self, pid: int) -> bool:
        """检查进程是否存活"""
        return psutil.pid_exists(pid)

    def kill_process(self, pid: int, force: bool = False) -> bool:
        """终止进程

        Args:
            pid: 进程 ID
            force: 是否强制终止 (SIGKILL)

        Returns:
            是否成功
        """
        try:
            proc = psutil.Process(pid)
            if force:
                proc.kill()
            else:
                proc.terminate()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def get_process_info(self, pid: int) -> Optional[ProcessInfo]:
        """获取指定进程的信息"""
        try:
            proc = psutil.Process(pid)
            info = proc.as_dict(['pid', 'name', 'cmdline', 'cwd', 'create_time', 'status'])

            create_time = info.get('create_time')
            if create_time:
                create_time = datetime.fromtimestamp(create_time)
            else:
                create_time = datetime.now()

            return ProcessInfo(
                pid=info['pid'],
                name=info.get('name', 'unknown'),
                cmdline=info.get('cmdline') or [],
                cwd=info.get('cwd', ''),
                create_time=create_time,
                status=info.get('status', 'unknown'),
                cpu_percent=proc.cpu_percent(interval=0.1),
                memory_percent=proc.memory_percent(),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
