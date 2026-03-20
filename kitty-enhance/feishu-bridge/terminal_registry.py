"""
终端注册表管理

维护 registry.json，记录所有在线 AI 终端的状态。
Hook 写入注册信息，daemon 读取并定期清理。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time

logger = logging.getLogger("feishu-bridge")

REGISTRY_FILE = "/tmp/feishu-bridge/registry.json"


def discover_kitty_sockets() -> list[str]:
    """发现所有运行中的 kitty socket"""
    try:
        result = subprocess.run(
            ["ss", "-lx"], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return []
        sockets = []
        for line in result.stdout.splitlines():
            # 匹配 @mykitty-PID 格式
            idx = line.find("@mykitty-")
            if idx == -1:
                continue
            # 提取 socket 名（到空格为止）
            rest = line[idx:]
            name = rest.split()[0]
            sockets.append(f"unix:{name}")
        return sockets
    except Exception:
        return []


def load_registry() -> dict:
    """读取注册表，返回 {window_id: info_dict}"""
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_registry(registry: dict):
    """写入注册表"""
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def get_active_window_ids(socket: str) -> set[str]:
    """通过 kitty @ ls 获取当前所有窗口 ID"""
    cmd = ["kitty", "@", "--to", socket, "ls"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return set()
        data = json.loads(result.stdout)
        ids = set()
        for os_win in data:
            for tab in os_win.get("tabs", []):
                for win in tab.get("windows", []):
                    ids.add(str(win.get("id", "")))
        return ids
    except Exception:
        logger.debug("获取窗口列表失败")
        return set()


def _agent_name(kind: str) -> str:
    if kind == "codex":
        return "Codex"
    return "Claude"


def _detect_agent_kind(win: dict) -> str | None:
    """判断窗口是否运行受支持的 AI 终端"""
    for proc in win.get("foreground_processes", []):
        cmdline = proc.get("cmdline", [])
        tokens = [os.path.basename(str(token)).lower() for token in cmdline if token]
        if any("claude" in token for token in tokens):
            return "claude"
        if any(token == "codex" or token.startswith("codex-") for token in tokens):
            return "codex"
    return None


def cleanup_registry(socket: str) -> int:
    """清理已关闭或不再运行受支持终端的窗口，返回移除数量"""
    registry = load_registry()
    if not registry:
        return 0

    active_windows = _get_supported_window_ids(socket)
    if active_windows is None:
        # kitty 命令失败时不清理，避免误删
        return 0

    to_remove = [wid for wid in registry if wid not in active_windows]
    for wid in to_remove:
        del registry[wid]
        logger.info("清理终端: window=%s", wid)

    if to_remove:
        save_registry(registry)
    return len(to_remove)


def _get_supported_window_ids(socket: str) -> set[str] | None:
    """获取所有运行受支持 AI 终端的窗口 ID，失败返回 None"""
    cmd = ["kitty", "@", "--to", socket, "ls"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        ids = set()
        for os_win in data:
            for tab in os_win.get("tabs", []):
                for win in tab.get("windows", []):
                    if _detect_agent_kind(win):
                        ids.add(str(win.get("id", "")))
        return ids
    except Exception:
        return None


def scan_and_register(socket: str) -> int:
    """扫描单个 kitty socket，将运行受支持 AI 终端的窗口自动注册，返回新注册数量"""
    cmd = ["kitty", "@", "--to", socket, "ls"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            logger.warning("kitty ls 失败: socket=%s, rc=%d", socket, result.returncode)
            return 0
        data = json.loads(result.stdout)
    except Exception:
        logger.debug("扫描窗口失败: socket=%s", socket)
        return 0

    registry = load_registry()
    new_count = 0
    now = time.time()

    supported_wids = []
    all_wids = []
    for os_win in data:
        for tab in os_win.get("tabs", []):
            tab_title = tab.get("title", "")
            for win in tab.get("windows", []):
                wid = str(win.get("id", ""))
                if not wid:
                    continue
                all_wids.append(wid)
                agent_kind = _detect_agent_kind(win)
                if not agent_kind:
                    continue
                supported_wids.append(f"{wid}:{agent_kind}")
                if wid in registry:
                    # 已注册的更新 tab_title 和 socket（可能变化）
                    if tab_title and registry[wid].get("tab_title") != tab_title:
                        registry[wid]["tab_title"] = tab_title
                    registry[wid]["kitty_socket"] = socket
                    registry[wid]["agent_kind"] = agent_kind
                    registry[wid]["agent_name"] = _agent_name(agent_kind)
                    continue
                cwd = ""
                foreground = win.get("foreground_processes", [])
                if foreground:
                    cwd = foreground[0].get("cwd", "")
                registry[wid] = {
                    "window_id": wid,
                    "kitty_socket": socket,
                    "tab_title": tab_title,
                    "cwd": cwd,
                    "registered_at": now,
                    "last_activity": now,
                    "status": "idle",
                    "agent_kind": agent_kind,
                    "agent_name": _agent_name(agent_kind),
                }
                new_count += 1

    if new_count:
        save_registry(registry)
    if new_count:
        logger.info("扫描注册: socket=%s, 新增 %d 个终端", socket, new_count)
    logger.debug("扫描结果: socket=%s, 总窗口=%d, 受支持终端=%s",
                 socket, len(all_wids), supported_wids)
    return new_count


# 缓存上次发现的 socket 列表，避免频繁调 ss
_cached_sockets: list[str] = []
_cached_sockets_time: float = 0
_SOCKET_CACHE_TTL = 60  # 60 秒刷新一次 socket 发现


def _get_sockets() -> list[str]:
    """获取 kitty socket 列表（带缓存）"""
    global _cached_sockets, _cached_sockets_time
    now = time.time()
    if now - _cached_sockets_time < _SOCKET_CACHE_TTL and _cached_sockets:
        return _cached_sockets
    _cached_sockets = discover_kitty_sockets()
    _cached_sockets_time = now
    return _cached_sockets


def scan_all_kitty() -> int:
    """发现所有 kitty socket，逐个扫描注册，返回总新增数量"""
    sockets = _get_sockets()
    if not sockets:
        return 0
    total = 0
    for sock in sockets:
        total += scan_and_register(sock)
    if total:
        logger.info("多实例扫描: %d 个 kitty, 新增 %d 个终端", len(sockets), total)
    return total


def cleanup_all_kitty() -> int:
    """跨所有 kitty socket 清理注册表，返回移除数量"""
    registry = load_registry()
    if not registry:
        return 0

    sockets = _get_sockets()
    if not sockets:
        return 0

    all_supported_windows: set[str] = set()
    any_success = False
    for sock in sockets:
        wids = _get_supported_window_ids(sock)
        if wids is not None:
            all_supported_windows.update(wids)
            any_success = True

    if not any_success:
        return 0

    to_remove = [wid for wid in registry if wid not in all_supported_windows]
    for wid in to_remove:
        del registry[wid]
        logger.info("清理终端: window=%s", wid)

    if to_remove:
        save_registry(registry)
    return len(to_remove)


def get_terminal_info(window_id: str) -> dict | None:
    """获取单个终端信息"""
    registry = load_registry()
    return registry.get(window_id)


def format_time_ago(ts: float) -> str:
    """格式化时间差为可读字符串"""
    ago = time.time() - ts
    if ago < 60:
        return "刚刚"
    if ago < 3600:
        return f"{int(ago // 60)} 分钟前"
    if ago < 86400:
        return f"{int(ago // 3600)} 小时前"
    return f"{int(ago // 86400)} 天前"


STATUS_ICON = {
    "working": "🟢",
    "completed": "🔴",
    "waiting": "🟡",
    "idle": "⚪",
}

STATUS_TEXT = {
    "working": "工作中",
    "completed": "已完成",
    "waiting": "等待确认",
    "idle": "空闲",
}
