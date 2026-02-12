#!/bin/bash
# on-bell.sh - 终端 bell 响铃时触发（由 kitty command_on_bell 调用）
# 功能：非聚焦 Tab 变红，聚焦后自动恢复
# 通知由 Kitty 原生处理，此脚本只负责 Tab 颜色

COMMON="$(dirname "$0")/tab-color-common.sh"
source "$COMMON"

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"
WINDOW_ID="${KITTY_WINDOW_ID:-}"
[ -z "$WINDOW_ID" ] && exit 0

# 先清理已聚焦的 tab（恢复颜色）
cleanup_focused_tabs "$KITTY_SOCKET"

# 查询 bell 窗口的 tab 信息
TAB_INFO=$(get_tab_info "$KITTY_SOCKET" "$WINDOW_ID")
[ -z "$TAB_INFO" ] && exit 0

TAB_ID="${TAB_INFO%% *}"
WIN_FOCUSED="${TAB_INFO##* }"

[ "$WIN_FOCUSED" = "1" ] && exit 0

# 设置红色（bell 通知）
set_tab_color "$KITTY_SOCKET" "$TAB_ID" "red"

# 确保共享 poller 运行
ensure_poller "$KITTY_SOCKET"

exit 0
