#!/bin/bash
# feishu-register.sh - 终端注册公共函数
# 被 on-tool-use.sh / on-stop.sh / on-permission-pending.sh source 使用

_feishu_register() {
    # 参数: $1 = 状态 (working / completed / waiting)
    local STATUS="$1"
    local WINDOW_ID="${KITTY_WINDOW_ID:-}"
    [ -z "$WINDOW_ID" ] && return 0

    local REGISTRY="/tmp/feishu-bridge/registry.json"
    local BRIDGE_DIR="$(dirname "$(readlink -f "$0")")/../feishu-bridge"
    mkdir -p /tmp/feishu-bridge

    # flock 保证并发安全，-w 1 最多等 1 秒
    (
        flock -w 1 200 || return 0
        CM_FEISHU_STATUS="$STATUS" CM_BRIDGE_DIR="$BRIDGE_DIR" python3 - <<'PY'
import os
import sys
import time

sys.path.insert(0, os.environ["CM_BRIDGE_DIR"])
from terminal_registry import build_terminal_id, load_registry, save_registry, socket_to_label

reg_path = '/tmp/feishu-bridge/registry.json'
wid = os.environ.get('KITTY_WINDOW_ID', '')
status = os.environ.get('CM_FEISHU_STATUS', '')
socket = os.environ.get('KITTY_LISTEN_ON', '')
cwd = os.environ.get('PWD', '')
if not wid or not socket:
    raise SystemExit(0)

registry = load_registry()
terminal_id = build_terminal_id(wid, socket)
old = registry.get(terminal_id, {})
registry[terminal_id] = {
    'terminal_id': terminal_id,
    'window_id': wid,
    'kitty_socket': socket or old.get('kitty_socket', ''),
    'socket_label': socket_to_label(socket or old.get('kitty_socket', '')),
    'tab_title': old.get('tab_title', cwd.rsplit('/', 1)[-1] if cwd else ''),
    'cwd': cwd or old.get('cwd', ''),
    'registered_at': old.get('registered_at', time.time()),
    'last_activity': time.time(),
    'status': status,
    'agent_kind': old.get('agent_kind', 'claude'),
    'agent_name': old.get('agent_name', 'Claude'),
}
save_registry(registry)
PY
    ) 200>/tmp/feishu-bridge/.registry.lock
}
