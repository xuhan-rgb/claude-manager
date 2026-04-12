"""
终端注册表管理

维护 registry.json，记录所有在线 AI 终端的状态。
Hook 写入注册信息，daemon 读取并定期清理。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time

logger = logging.getLogger("feishu-bridge")

REGISTRY_FILE = "/tmp/feishu-bridge/registry.json"
_SOCKET_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")


def socket_to_label(socket: str) -> str:
    """Return a short, file-safe label for a kitty socket."""
    value = (socket or "").strip()
    if value.startswith("unix:"):
        value = value[5:]
    if value.startswith("@"):
        value = value[1:]
    value = _SOCKET_LABEL_RE.sub("_", value).strip("_")
    return value or "kitty"


def build_terminal_id(window_id: str, socket: str) -> str:
    """Build a stable terminal id from kitty socket + window id."""
    wid = str(window_id or "").strip()
    if not wid:
        return ""
    label = socket_to_label(socket)
    return f"{wid}@{label}" if label else wid


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_terminal_entry(entry_key: str, entry: dict) -> tuple[str, dict] | None:
    if not isinstance(entry, dict):
        return None

    window_id = str(entry.get("window_id") or entry_key or "").strip()
    socket = str(entry.get("kitty_socket") or "").strip()
    if not window_id or not socket:
        return None

    terminal_id = str(entry.get("terminal_id") or "").strip() or build_terminal_id(window_id, socket)
    normalized = dict(entry)
    normalized["window_id"] = window_id
    normalized["kitty_socket"] = socket
    normalized["terminal_id"] = terminal_id
    normalized["socket_label"] = socket_to_label(socket)
    return terminal_id, normalized


def _pick_newer_entry(existing: dict, candidate: dict) -> dict:
    existing_score = (_safe_float(existing.get("last_activity")), _safe_float(existing.get("registered_at")))
    candidate_score = (_safe_float(candidate.get("last_activity")), _safe_float(candidate.get("registered_at")))
    return candidate if candidate_score >= existing_score else existing


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
    """读取注册表，返回 {terminal_id: info_dict}"""
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, dict] = {}
    for entry_key, entry in raw.items():
        converted = _normalize_terminal_entry(str(entry_key), entry)
        if not converted:
            continue
        terminal_id, normalized_entry = converted
        if terminal_id in normalized:
            normalized[terminal_id] = _pick_newer_entry(normalized[terminal_id], normalized_entry)
        else:
            normalized[terminal_id] = normalized_entry
    return normalized


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

    active_terminals = _get_supported_terminal_ids(socket)
    if active_terminals is None:
        # kitty 命令失败时不清理，避免误删
        return 0

    to_remove = [terminal_id for terminal_id in registry if terminal_id not in active_terminals]
    for terminal_id in to_remove:
        del registry[terminal_id]
        logger.info("清理终端: terminal=%s", terminal_id)

    if to_remove:
        save_registry(registry)
    return len(to_remove)


def _get_supported_terminal_ids(socket: str) -> set[str] | None:
    """获取所有运行受支持 AI 终端的 terminal_id，失败返回 None"""
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
                    agent_kind = _detect_agent_kind(win)
                    if not agent_kind:
                        continue
                    wid = str(win.get("id", ""))
                    if wid:
                        ids.add(build_terminal_id(wid, socket))
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

    supported_ids = []
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
                terminal_id = build_terminal_id(wid, socket)
                supported_ids.append(f"{terminal_id}:{agent_kind}")
                if terminal_id in registry:
                    # 已注册的更新 tab_title 和 socket（可能变化）
                    if tab_title and registry[terminal_id].get("tab_title") != tab_title:
                        registry[terminal_id]["tab_title"] = tab_title
                    registry[terminal_id]["kitty_socket"] = socket
                    registry[terminal_id]["socket_label"] = socket_to_label(socket)
                    registry[terminal_id]["agent_kind"] = agent_kind
                    registry[terminal_id]["agent_name"] = _agent_name(agent_kind)
                    continue
                cwd = ""
                foreground = win.get("foreground_processes", [])
                if foreground:
                    cwd = foreground[0].get("cwd", "")
                registry[terminal_id] = {
                    "terminal_id": terminal_id,
                    "window_id": wid,
                    "kitty_socket": socket,
                    "socket_label": socket_to_label(socket),
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
                 socket, len(all_wids), supported_ids)
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

    all_supported_terminals: set[str] = set()
    any_success = False
    for sock in sockets:
        terminal_ids = _get_supported_terminal_ids(sock)
        if terminal_ids is not None:
            all_supported_terminals.update(terminal_ids)
            any_success = True

    if not any_success:
        return 0

    to_remove = [terminal_id for terminal_id in registry if terminal_id not in all_supported_terminals]
    for terminal_id in to_remove:
        del registry[terminal_id]
        logger.info("清理终端: terminal=%s", terminal_id)

    if to_remove:
        save_registry(registry)
    return len(to_remove)


def resolve_terminal_selector(selector: str, registry: dict | None = None) -> tuple[dict | None, list[dict]]:
    """Resolve terminal_id or legacy window_id to a registry entry.

    Returns `(entry, ambiguous_matches)`.
    """
    selector = (selector or "").strip()
    if not selector:
        return None, []

    registry = registry or load_registry()
    if selector in registry:
        return registry[selector], []

    matches = [entry for entry in registry.values() if entry.get("window_id") == selector]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        matches.sort(key=lambda item: item.get("terminal_id") or "")
        return None, matches
    return None, []


def get_terminal_info(selector: str) -> dict | None:
    """获取单个终端信息，支持 terminal_id 或唯一的 window_id。"""
    terminal, _ = resolve_terminal_selector(selector)
    return terminal


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
