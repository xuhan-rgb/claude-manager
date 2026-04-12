#!/bin/bash
# on-stop.sh - Claude Code 完成响应后触发（hooks.Stop）
# 功能：非聚焦 Tab 变红，聚焦后自动恢复
# 红色优先于黄色，共享 tab-color-common.sh 管理状态

# 条件加载 tab-color（bridge-only 模式下可能不存在）
COMMON="$(dirname "$(readlink -f "$0")")/tab-color-common.sh"
if [ -f "$COMMON" ]; then
    source "$COMMON"
    _TAB_COLOR=true
else
    _TAB_COLOR=false
    debug() { :; }
fi

debug "=== on-stop.sh triggered ==="

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"
WINDOW_ID="${KITTY_WINDOW_ID:-}"
BRIDGE_DIR="$(dirname "$(readlink -f "$0")")/../feishu-bridge"
[ -z "$WINDOW_ID" ] && { debug "no WINDOW_ID, exit"; exit 0; }

# Tab 颜色逻辑（仅在 tab-color 可用时执行）
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
                case "$_cur" in blue|blue-paused|red|yellow)
                    # 聚焦时清除所有颜色状态（包括之前残留的红/黄）
                    kitty @ --to "$KITTY_SOCKET" set-tab-color --match "id:$TAB_ID" \
                        active_bg=NONE active_fg=NONE \
                        inactive_bg=NONE inactive_fg=NONE 2>/dev/null || true
                    rm -f "$local_sf"
                    rm -f "/tmp/kitty-tabcache-${WINDOW_ID}"
                    debug "window focused, cleared $_cur state"
                ;; esac
            fi
            debug "window focused, skip red"
        else
            set_tab_color "$KITTY_SOCKET" "$TAB_ID" "red"
            rm -f "/tmp/kitty-tab-${TAB_ID}-stop"
            ensure_poller "$KITTY_SOCKET"
        fi
    fi
fi

# === 飞书桥接逻辑（始终执行） ===

# 清理 feishu-bridge pending 文件（任务已停止，权限弹窗不再需要）
TERMINAL_ID=$(CM_BRIDGE_DIR="$BRIDGE_DIR" python3 - <<'PY'
import os, sys
sys.path.insert(0, os.environ["CM_BRIDGE_DIR"])
from terminal_registry import build_terminal_id
wid = os.environ.get("KITTY_WINDOW_ID", "")
sock = os.environ.get("KITTY_LISTEN_ON", "")
print(build_terminal_id(wid, sock))
PY
)
rm -f "/tmp/feishu-bridge/${WINDOW_ID}.json" 2>/dev/null
[ -n "$TERMINAL_ID" ] && rm -f "/tmp/feishu-bridge/${TERMINAL_ID}.json" 2>/dev/null

# 终端注册：状态更新为 completed
source "$(dirname "$(readlink -f "$0")")/feishu-register.sh"
_feishu_register "completed"

# 发送完成通知到飞书（让用户可以继续发指令）
export _STOP_SCREEN_TAIL
_STOP_SCREEN_TAIL=$(kitty @ --to "$KITTY_SOCKET" get-text --match "id:$WINDOW_ID" --extent=screen 2>/dev/null | tail -20 || true)

CM_BRIDGE_DIR="$BRIDGE_DIR" python3 -c '
import json, time, sys, os
sys.path.insert(0, os.environ["CM_BRIDGE_DIR"])
from terminal_registry import build_terminal_id

window_id = os.environ.get("KITTY_WINDOW_ID", "")
kitty_socket = os.environ.get("KITTY_LISTEN_ON", "")
screen_tail = os.environ.get("_STOP_SCREEN_TAIL", "")
terminal_id = build_terminal_id(window_id, kitty_socket)

# 获取 Tab 标题
tab_title = ""
try:
    import subprocess
    ls_json = subprocess.run(
        ["kitty", "@", "--to", kitty_socket, "ls"],
        capture_output=True, text=True, timeout=3
    ).stdout
    for os_win in json.loads(ls_json):
        for tab in os_win.get("tabs", []):
            for win in tab.get("windows", []):
                if str(win.get("id")) == window_id:
                    tab_title = tab.get("title", "")
except Exception:
    pass

info = {
    "type": "completed",
    "terminal_id": terminal_id,
    "window_id": window_id,
    "kitty_socket": kitty_socket,
    "tab_title": tab_title,
    "screen_tail": screen_tail,
    "timestamp": time.time(),
}
path = f"/tmp/feishu-bridge/{terminal_id}_completed.json"
legacy_path = f"/tmp/feishu-bridge/{window_id}_completed.json"
os.makedirs("/tmp/feishu-bridge", exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(info, f, ensure_ascii=False, indent=2)
if legacy_path != path:
    try:
        os.remove(legacy_path)
    except FileNotFoundError:
        pass
'

exit 0
