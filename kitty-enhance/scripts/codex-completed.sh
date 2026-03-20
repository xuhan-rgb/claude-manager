#!/bin/bash
# codex-completed.sh - Codex 当前轮次完成时触发
# 作用：非聚焦 Tab 变红，写完成通知文件，并把终端注册为 completed

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

        if [ "$WIN_FOCUSED" = "1" ]; then
            local_sf=$(_state_file "$KITTY_SOCKET" "$TAB_ID")
            if [ -f "$local_sf" ]; then
                read -r _cur < "$local_sf"
                case "$_cur" in
                    blue|blue-paused)
                        rm -f "$local_sf"
                        rm -f "/tmp/kitty-tabcache-${WINDOW_ID}"
                    ;;
                esac
            fi
        else
            set_tab_color "$KITTY_SOCKET" "$TAB_ID" "red"
            ensure_poller "$KITTY_SOCKET"
        fi
    fi
fi

TAB_TITLE=$(kitty @ --to "$KITTY_SOCKET" ls 2>/dev/null | python3 -c "
import json, sys
wid = '$WINDOW_ID'
try:
    data = json.load(sys.stdin)
    for os_win in data:
        for tab in os_win.get('tabs', []):
            for win in tab.get('windows', []):
                if str(win.get('id')) == wid:
                    print(tab.get('title', ''))
                    sys.exit(0)
except: pass
" 2>/dev/null || true)

SCREEN_TAIL=$(kitty @ --to "$KITTY_SOCKET" get-text --match "id:$WINDOW_ID" --extent=screen 2>/dev/null | tail -20 || true)

export CM_CODEX_TAB_TITLE="$TAB_TITLE"
export CM_CODEX_SCREEN_TAIL="$SCREEN_TAIL"
export CM_COMPLETED_MESSAGE="${CM_COMPLETED_MESSAGE:-}"

(
python3 <<'PYEOF'
import json
import os
import time
from pathlib import Path

state_dir = Path("/tmp/feishu-bridge")
state_dir.mkdir(parents=True, exist_ok=True)

window_id = os.environ.get("KITTY_WINDOW_ID", "")
if not window_id:
    raise SystemExit(0)

registry_path = state_dir / "registry.json"
try:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
except Exception:
    registry = {}

old = registry.get(window_id, {})
cwd = os.environ.get("PWD", "")
tab_title = os.environ.get("CM_CODEX_TAB_TITLE", "") or old.get("tab_title") or (cwd.rsplit("/", 1)[-1] if cwd else "")

registry[window_id] = {
    "window_id": window_id,
    "kitty_socket": os.environ.get("KITTY_LISTEN_ON", "") or old.get("kitty_socket", ""),
    "tab_title": tab_title,
    "cwd": cwd or old.get("cwd", ""),
    "registered_at": old.get("registered_at", time.time()),
    "last_activity": time.time(),
    "status": "completed",
    "agent_kind": "codex",
    "agent_name": "Codex",
}
registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

completed = {
    "type": "completed",
    "window_id": window_id,
    "kitty_socket": os.environ.get("KITTY_LISTEN_ON", ""),
    "tab_title": tab_title,
    "screen_tail": os.environ.get("CM_CODEX_SCREEN_TAIL", ""),
    "last_agent_message": os.environ.get("CM_COMPLETED_MESSAGE", ""),
    "agent_kind": "codex",
    "agent_name": "Codex",
    "timestamp": time.time(),
}

path = state_dir / f"{window_id}_completed.json"
path.write_text(json.dumps(completed, ensure_ascii=False, indent=2), encoding="utf-8")
PYEOF
) 200>/tmp/feishu-bridge/.registry.lock
