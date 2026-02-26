#!/bin/bash
# on-stop.sh - Claude Code 完成响应后触发（hooks.Stop）
# 功能：非聚焦 Tab 变红，聚焦后自动恢复
# 红色优先于黄色，共享 tab-color-common.sh 管理状态

COMMON="$(dirname "$(readlink -f "$0")")/tab-color-common.sh"
source "$COMMON"

debug "=== on-stop.sh triggered ==="

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

# 聚焦时不设红色，但必须清除蓝色状态（任务已停止，不应再显示蓝色）
if [ "$WIN_FOCUSED" = "1" ]; then
    local_sf=$(_state_file "$KITTY_SOCKET" "$TAB_ID")
    if [ -f "$local_sf" ]; then
        read -r _cur < "$local_sf"
        case "$_cur" in blue|blue-paused)
            rm -f "$local_sf"
            # 清除快路径缓存
            rm -f "/tmp/kitty-tabcache-${WINDOW_ID}"
            debug "window focused, cleared blue state"
        ;; esac
    fi
    debug "window focused, skip red"
    exit 0
fi

# 设置红色（任务完成）
set_tab_color "$KITTY_SOCKET" "$TAB_ID" "red"

# 清理旧版状态文件（兼容过渡）
rm -f "/tmp/kitty-tab-${TAB_ID}-stop"

# 确保共享 poller 运行
ensure_poller "$KITTY_SOCKET"

exit 0
