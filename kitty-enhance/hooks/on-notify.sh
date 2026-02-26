#!/bin/bash
# on-notify.sh - Claude Code 需要用户确认时触发（hooks.Notification）
# 功能：非聚焦 Tab 变黄，聚焦后自动恢复（不覆盖红色）

COMMON="$(dirname "$(readlink -f "$0")")/tab-color-common.sh"
source "$COMMON"

debug "=== on-notify.sh triggered ==="

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"
WINDOW_ID="${KITTY_WINDOW_ID:-}"
[ -z "$WINDOW_ID" ] && { debug "no WINDOW_ID, exit"; exit 0; }

# 先清理已聚焦的 tab（恢复颜色）
cleanup_focused_tabs "$KITTY_SOCKET"

# 查询当前窗口的 tab 信息
TAB_INFO=$(get_tab_info "$KITTY_SOCKET" "$WINDOW_ID")
[ -z "$TAB_INFO" ] && { debug "TAB_INFO empty, exit"; exit 0; }

TAB_ID="${TAB_INFO%% *}"
WIN_FOCUSED="${TAB_INFO##* }"

# 聚焦时不设黄色，但清除蓝色（Esc 中断时 Notification 会触发，蓝色已无意义）
if [ "$WIN_FOCUSED" = "1" ]; then
    local_sf=$(_state_file "$KITTY_SOCKET" "$TAB_ID")
    if [ -f "$local_sf" ]; then
        read -r _cur < "$local_sf"
        case "$_cur" in blue|blue-paused)
            debug "window focused, clearing blue state"
            rm -f "$local_sf"
            rm -f "/tmp/kitty-tabcache-${WINDOW_ID}"
        ;; esac
    fi
    debug "window focused, skip yellow"
    exit 0
fi

# 设置黄色（等待确认，不会覆盖已有的红色）
set_tab_color "$KITTY_SOCKET" "$TAB_ID" "yellow"

# 确保共享 poller 运行
ensure_poller "$KITTY_SOCKET"

exit 0
