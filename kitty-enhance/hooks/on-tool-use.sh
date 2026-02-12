#!/bin/bash
# on-tool-use.sh - Claude Code 调用工具时触发（hooks.PreToolUse）
# 功能：非聚焦 Tab 变蓝（不覆盖红色和黄色）
# 性能：快路径零子进程（纯 bash 内建命令）

WINDOW_ID="${KITTY_WINDOW_ID:-}"
[ -z "$WINDOW_ID" ] && exit 0

# === 快路径：缓存了状态文件路径，纯内建命令，零 fork ===
_cache="/tmp/kitty-tabcache-${WINDOW_ID}"
if [ -f "$_cache" ]; then
    read -r _sf < "$_cache"
    if [ -f "$_sf" ]; then
        read -r _cur < "$_sf"
        case "$_cur" in blue|red|yellow) exit 0 ;; esac
    fi
fi

# === 慢路径：首次或状态重置后，后台异步设蓝色 ===
source "$(dirname "$(readlink -f "$0")")/tab-color-common.sh"
KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"

(
    TAB_INFO=$(get_tab_info "$KITTY_SOCKET" "$WINDOW_ID")
    [ -z "$TAB_INFO" ] && exit 0

    TAB_ID="${TAB_INFO%% *}"
    WIN_FOCUSED="${TAB_INFO##* }"
    [ "$WIN_FOCUSED" = "1" ] && exit 0

    sf=$(_state_file "$KITTY_SOCKET" "$TAB_ID")

    # 缓存状态文件路径（后续快路径直接用）
    echo "$sf" > "$_cache"

    current=""
    [ -f "$sf" ] && read -r current < "$sf"
    case "$current" in blue|red|yellow) exit 0 ;; esac

    sleep 0.3

    current=""
    [ -f "$sf" ] && read -r current < "$sf"
    case "$current" in red|yellow) exit 0 ;; esac

    set_tab_color "$KITTY_SOCKET" "$TAB_ID" "blue"
    ensure_poller "$KITTY_SOCKET"
) </dev/null >/dev/null 2>&1 &
disown

exit 0
