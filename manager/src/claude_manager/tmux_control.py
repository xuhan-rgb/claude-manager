"""Tmux 会话管理 - 每个任务一个独立会话"""

import subprocess
import os
import logging
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Claude API 配置
CLAUDE_ENV = {
    'ANTHROPIC_BASE_URL': 'http://localhost:3000/api',
    'ANTHROPIC_AUTH_TOKEN': 'cr_d8897e6489ff64846fa44c2a831dbcd242eeef5583b6e12d70ab382ba3b7b88c',
}

def get_claude_env_config() -> dict:
    """获取 Claude 环境变量配置

    优先从配置文件读取，否则使用默认值
    支持格式：
      KEY=value
      KEY="value"
      export KEY=value
      export KEY="value"
    """
    config_file = Path.home() / '.config' / 'claude-manager' / 'claude_env.conf'
    env = CLAUDE_ENV.copy()

    if config_file.exists():
        try:
            for line in config_file.read_text().strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # 去掉 export 前缀
                    if line.startswith('export '):
                        line = line[7:]
                    key, value = line.split('=', 1)
                    # 去掉引号
                    value = value.strip().strip('"\'')
                    env[key.strip()] = value
                    logger.info(f"[配置] {key.strip()} = {value[:20]}...")
        except Exception as e:
            logger.error(f"[配置] 读取失败: {e}")

    return env


@dataclass
class TmuxSession:
    """Tmux 会话信息"""
    name: str
    attached: bool
    windows: int


class TmuxController:
    """Tmux 控制器 - 任务会话管理

    每个任务对应一个独立的 tmux 会话，会话名格式：cm-{task_id}
    切换任务 = 切换 tmux 会话（tab）
    """

    SESSION_PREFIX = "cm-"
    CMD_SESSION_SUFFIX = "-cmd"

    def _run(self, *args, timeout: float = 2.0) -> subprocess.CompletedProcess:
        """执行 tmux 命令"""
        cmd = ['tmux'] + list(args)
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 1, '', 'timeout')

    def is_available(self) -> bool:
        """检查 tmux 是否可用"""
        return self._run('-V').returncode == 0

    def configure_global_options(self) -> None:
        """配置 tmux 全局选项"""
        # 启用鼠标并绑定滚轮直接进入 copy-mode（避免滚轮触发命令历史）
        self._run('set-option', '-g', 'mouse', 'on')
        self._run(
            'bind-key',
            '-n',
            'WheelUpPane',
            'if-shell',
            '-F',
            '#{mouse_any_flag}',
            'send-keys -M',
            'copy-mode -e; send-keys -M',
        )
        self._run(
            'bind-key',
            '-n',
            'WheelDownPane',
            'if-shell',
            '-F',
            '#{mouse_any_flag}',
            'send-keys -M',
            'send-keys -M',
        )
        # 提高历史输出上限（用于滚轮/复制）
        self._run('set-option', '-g', 'history-limit', '50000')

    # ========== 任务会话管理 ==========

    def get_session_name(self, task_id: str) -> str:
        """获取任务对应的 tmux 会话名"""
        return f"{self.SESSION_PREFIX}{task_id}"

    def get_cmd_session_name(self, task_id: str) -> str:
        """获取任务命令窗口对应的 tmux 会话名"""
        return f"{self.SESSION_PREFIX}{task_id}{self.CMD_SESSION_SUFFIX}"

    def session_exists_by_name(self, session_name: str) -> bool:
        """检查指定会话是否存在"""
        return self._run('has-session', '-t', session_name).returncode == 0

    def session_exists(self, task_id: str) -> bool:
        """检查任务会话是否存在"""
        session = self.get_session_name(task_id)
        return self.session_exists_by_name(session)

    def cmd_session_exists(self, task_id: str) -> bool:
        """检查命令会话是否存在"""
        session = self.get_cmd_session_name(task_id)
        return self.session_exists_by_name(session)

    def enable_activity_monitoring(self, task_id: str) -> bool:
        """为 session 启用活动监控

        Args:
            task_id: 任务 ID

        Returns:
            是否成功
        """
        session = self.get_session_name(task_id)
        # 启用活动监控和沉默监控
        result1 = self._run('set-window-option', '-t', session, 'monitor-activity', 'on')
        result2 = self._run('set-window-option', '-t', session, 'monitor-silence', '10')  # 10秒沉默
        return result1.returncode == 0 and result2.returncode == 0

    def get_activity_status(self, task_id: str) -> dict:
        """获取 session 的活动状态

        Args:
            task_id: 任务 ID

        Returns:
            活动状态字典：{
                'has_activity': bool,  # 是否有活动
                'is_silent': bool,     # 是否沉默
                'activity_time': int,  # 最后活动时间戳
            }
        """
        session = self.get_session_name(task_id)
        result = self._run(
            'list-windows', '-t', session,
            '-F', '#{window_activity_flag}:#{window_silence_flag}:#{window_activity}'
        )

        if result.returncode != 0:
            return {'has_activity': False, 'is_silent': False, 'activity_time': 0}

        output = result.stdout.strip()
        if not output:
            return {'has_activity': False, 'is_silent': False, 'activity_time': 0}

        parts = output.split(':')
        return {
            'has_activity': parts[0] == '1' if len(parts) > 0 else False,
            'is_silent': parts[1] == '1' if len(parts) > 1 else False,
            'activity_time': int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
        }

    def configure_session_by_name(self, session: str) -> None:
        """配置会话的滚动与历史输出"""
        # 使用全局鼠标设置（支持滚轮直接滚动）
        self._run('set-option', '-t', session, 'history-limit', '50000')

    def configure_session(self, task_id: str) -> None:
        """配置任务会话的滚动与历史输出"""
        session = self.get_session_name(task_id)
        self.configure_session_by_name(session)

    def ensure_cmd_layout(self, task_id: str) -> None:
        """确保命令会话有水平分屏（上下两块）"""
        session = self.get_cmd_session_name(task_id)
        result = self._run('list-panes', '-t', session, '-F', '#{pane_id}')
        if result.returncode != 0:
            return
        panes = [line for line in result.stdout.strip().split('\n') if line]
        if len(panes) >= 2:
            return
        # 水平分屏（上下两块）
        self._run('split-window', '-v', '-t', session)

    def get_active_pane_path(self, task_id: str) -> Optional[str]:
        """获取任务会话当前活动 pane 的工作目录"""
        session = self.get_session_name(task_id)
        result = self._run('list-panes', '-t', session, '-F', '#{pane_active}:#{pane_current_path}')
        if result.returncode != 0:
            return None

        lines = [line for line in result.stdout.strip().split('\n') if line]
        for line in lines:
            parts = line.split(':', 1)
            if len(parts) == 2 and parts[0] == '1':
                return parts[1].strip() or None

        for line in lines:
            parts = line.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        return None

    def create_session(self, task_id: str, cwd: str, command: str = "claude") -> bool:
        """创建任务会话

        Args:
            task_id: 任务 ID
            cwd: 工作目录
            command: 启动命令（默认 claude）

        Returns:
            是否成功
        """
        import time
        session = self.get_session_name(task_id)
        if self.session_exists(task_id):
            self.configure_session(task_id)
            return True

        # 创建 session（只启动交互式 bash）
        result = self._run(
            'new-session',
            '-d',  # detached
            '-s', session,
            '-c', cwd,
        )

        if result.returncode != 0:
            return False

        self.configure_session(task_id)

        # 获取 Claude 环境变量并发送
        claude_env = get_claude_env_config()
        for k, v in claude_env.items():
            self._run('send-keys', '-t', session, f'export {k}="{v}"')
            self._run('send-keys', '-t', session, 'Enter')
            time.sleep(0.05)

        # 启动 claude
        self._run('send-keys', '-t', session, command)
        self._run('send-keys', '-t', session, 'Enter')

        # 启用活动监控和 aggressive-resize（让窗口独立调整大小）
        self.enable_activity_monitoring(task_id)
        self._run('set-window-option', '-t', session, 'aggressive-resize', 'on')
        return True

    def create_cmd_session(self, task_id: str, cwd: str, command: str = "bash") -> bool:
        """创建命令会话（用于执行命令）"""
        session = self.get_cmd_session_name(task_id)
        if self.cmd_session_exists(task_id):
            self.configure_session_by_name(session)
            self.ensure_cmd_layout(task_id)
            return True

        result = self._run(
            'new-session',
            '-d',
            '-s', session,
            '-c', cwd,
            command,
        )
        if result.returncode != 0:
            return False

        self.configure_session_by_name(session)
        self._run('set-window-option', '-t', session, 'aggressive-resize', 'on')
        self.ensure_cmd_layout(task_id)
        return True

    def kill_session(self, task_id: str) -> bool:
        """删除任务会话"""
        session = self.get_session_name(task_id)
        return self._run('kill-session', '-t', session).returncode == 0

    def restart_claude(self, task_id: str, command: str = "claude") -> bool:
        """重启 Claude

        使用 respawn-pane -k 强制杀死当前进程并启动新的 Claude
        环境变量通过 shell 命令前缀设置
        """
        session = self.get_session_name(task_id)
        logger.info(f"[restart] task_id={task_id}, session={session}")

        if not self.session_exists(task_id):
            logger.error(f"[restart] session {session} 不存在")
            return False

        logger.info(f"[restart] session {session} 存在，开始重启")

        # 获取最新的 Claude 环境变量配置
        claude_env = get_claude_env_config()
        logger.info(f"[restart] 环境变量: {list(claude_env.keys())}")

        # 构建带环境变量的启动命令
        env_exports = '; '.join(f'export {k}="{v}"' for k, v in claude_env.items())
        full_command = f'{env_exports}; {command}'
        logger.info(f"[restart] 命令: {full_command[:80]}...")

        # 使用 respawn-pane -k 强制重启
        logger.info(f"[restart] 执行: tmux respawn-pane -k -t {session}")
        result = self._run('respawn-pane', '-k', '-t', session, full_command, timeout=5.0)

        logger.info(f"[restart] returncode={result.returncode}")
        if result.stdout:
            logger.info(f"[restart] stdout: {result.stdout}")
        if result.stderr:
            logger.info(f"[restart] stderr: {result.stderr}")

        if result.returncode != 0:
            logger.error(f"[restart] respawn-pane 失败")
            return False

        # 启用 aggressive-resize 让窗口独立调整大小
        self._run('set-window-option', '-t', session, 'aggressive-resize', 'on')

        logger.info(f"[restart] Claude 重启成功: {session}")
        return True

    def switch_session(self, task_id: str) -> bool:
        """切换到任务会话

        使用 switch-client 切换当前 attached 的客户端到目标会话
        """
        session = self.get_session_name(task_id)
        result = self._run('switch-client', '-t', session)
        return result.returncode == 0

    def list_sessions(self) -> list[TmuxSession]:
        """列出所有任务会话（cm-* 开头的）"""
        result = self._run(
            'list-sessions',
            '-F', '#{session_name}:#{session_attached}:#{session_windows}'
        )
        if result.returncode != 0:
            return []

        sessions = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split(':')
            if len(parts) >= 3 and parts[0].startswith(self.SESSION_PREFIX):
                sessions.append(TmuxSession(
                    name=parts[0],
                    attached=parts[1] == '1',
                    windows=int(parts[2])
                ))
        return sessions

    def list_clients_by_tty(self) -> dict[str, str]:
        """列出所有 tmux 客户端（按 tty 映射到 session）"""
        result = self._run('list-clients', '-F', '#{client_tty}:#{session_name}')
        if result.returncode != 0:
            return {}
        clients: dict[str, str] = {}
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            tty, session = line.split(':', 1)
            tty = tty.strip()
            session = session.strip()
            if tty:
                clients[tty] = session
        return clients

    def get_task_id_from_session(self, session_name: str) -> Optional[str]:
        """从会话名提取任务 ID"""
        if session_name.startswith(self.SESSION_PREFIX):
            task_id = session_name[len(self.SESSION_PREFIX):]
            if task_id.endswith(self.CMD_SESSION_SUFFIX):
                task_id = task_id[: -len(self.CMD_SESSION_SUFFIX)]
            return task_id
        return None

    # ========== 辅助方法 ==========

    def get_current_session(self) -> Optional[str]:
        """获取当前 attached 的会话名"""
        result = self._run('display-message', '-p', '#{session_name}')
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def has_any_client(self) -> bool:
        """检查是否有任何 tmux 客户端"""
        result = self._run('list-clients')
        return result.returncode == 0 and bool(result.stdout.strip())


def check_tmux() -> tuple[bool, str]:
    """检查 tmux 是否可用"""
    try:
        result = subprocess.run(['tmux', '-V'], capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "tmux 命令执行失败"
    except FileNotFoundError:
        return False, "未找到 tmux，请安装: sudo apt install tmux"
