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
python3 <<'PYEOF'
import json
import os
import time
from pathlib import Path

registry_path = Path("/tmp/feishu-bridge/registry.json")
registry_path.parent.mkdir(parents=True, exist_ok=True)

window_id = os.environ.get("KITTY_WINDOW_ID", "")
if not window_id:
    raise SystemExit(0)

try:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
except Exception:
    registry = {}

old = registry.get(window_id, {})
cwd = os.environ.get("PWD", "")
tab_title = old.get("tab_title") or (cwd.rsplit("/", 1)[-1] if cwd else "")

registry[window_id] = {
    "window_id": window_id,
    "kitty_socket": os.environ.get("KITTY_LISTEN_ON", "") or old.get("kitty_socket", ""),
    "tab_title": tab_title,
    "cwd": cwd or old.get("cwd", ""),
    "registered_at": old.get("registered_at", time.time()),
    "last_activity": time.time(),
    "status": "working",
    "agent_kind": "codex",
    "agent_name": "Codex",
}

registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
PYEOF
) 200>/tmp/feishu-bridge/.registry.lock
