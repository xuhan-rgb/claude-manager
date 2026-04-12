#!/bin/bash
# codex-working.sh - Codex 开始处理当前轮次时触发
# 作用：非聚焦 Tab 变蓝，并把 Codex 终端注册为 working

COMMON="$(dirname "$(readlink -f "$0")")/tab-color-common.sh"
if [ -f "$COMMON" ]; then
    source "$COMMON"
    _TAB_COLOR=true
else
    _TAB_COLOR=false
    debug() { :; }
fi

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"
WINDOW_ID="${KITTY_WINDOW_ID:-}"
BRIDGE_DIR="$(dirname "$(readlink -f "$0")")/../feishu-bridge"
[ -z "$WINDOW_ID" ] && exit 0

if [ "$_TAB_COLOR" = true ]; then
    cleanup_focused_tabs "$KITTY_SOCKET"

    TAB_INFO=$(get_tab_info "$KITTY_SOCKET" "$WINDOW_ID")
    if [ -n "$TAB_INFO" ]; then
        TAB_ID="${TAB_INFO%% *}"
        WIN_FOCUSED="${TAB_INFO##* }"
        if [ "$WIN_FOCUSED" != "1" ]; then
            set_tab_color "$KITTY_SOCKET" "$TAB_ID" "blue"
            ensure_poller "$KITTY_SOCKET"
        else
            # Codex 的 working 信号只在 turn 开始时触发一次。
            # 若触发时窗口仍聚焦，先记成 blue-paused，之后切走时由 poller 恢复成蓝色。
            echo "blue-paused" > "$(_state_file "$KITTY_SOCKET" "$TAB_ID")"
            ensure_poller "$KITTY_SOCKET"
        fi
    fi
fi

(
flock -w 1 200 || exit 0
CM_BRIDGE_DIR="$BRIDGE_DIR" python3 <<'PYEOF'
import os
import sys
import time

sys.path.insert(0, os.environ["CM_BRIDGE_DIR"])
from terminal_registry import build_terminal_id, load_registry, save_registry, socket_to_label

window_id = os.environ.get("KITTY_WINDOW_ID", "")
kitty_socket = os.environ.get("KITTY_LISTEN_ON", "")
if not window_id or not kitty_socket:
    raise SystemExit(0)

registry = load_registry()
terminal_id = build_terminal_id(window_id, kitty_socket)
old = registry.get(terminal_id, {})
cwd = os.environ.get("PWD", "")
tab_title = old.get("tab_title") or (cwd.rsplit("/", 1)[-1] if cwd else "")

registry[terminal_id] = {
    "terminal_id": terminal_id,
    "window_id": window_id,
    "kitty_socket": kitty_socket or old.get("kitty_socket", ""),
    "socket_label": socket_to_label(kitty_socket or old.get("kitty_socket", "")),
    "tab_title": tab_title,
    "cwd": cwd or old.get("cwd", ""),
    "registered_at": old.get("registered_at", time.time()),
    "last_activity": time.time(),
    "status": "working",
    "agent_kind": "codex",
    "agent_name": "Codex",
}

save_registry(registry)
PYEOF
) 200>/tmp/feishu-bridge/.registry.lock
