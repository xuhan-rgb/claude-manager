#!/bin/bash
# tab-color-common.sh - Tab 颜色管理公共逻辑
# 被 on-stop.sh / on-notify.sh / on-bell.sh source 使用
# 状态文件：/tmp/kitty-tab-{socket_hash}-{tab_id} 内容为颜色类型（red/yellow）
# 轮询进程：共享单一后台进程，避免多 poller 互相干扰

STATE_DIR="/tmp"
LOG="/tmp/claude-hook.log"
debug() { [ "${CLAUDE_HOOK_DEBUG:-0}" = "1" ] && echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

# 用 socket 路径的 hash 区分不同 kitty 实例
_socket_hash() {
    echo "$1" | md5sum | cut -c1-8
}

# 状态文件路径
_state_file() {
    local socket="$1" tab_id="$2"
    echo "${STATE_DIR}/kitty-tab-$(_socket_hash "$socket")-${tab_id}"
}

# poller PID 文件路径（每个 kitty 实例独立）
_poller_pid_file() {
    echo "${STATE_DIR}/kitty-tab-poller-$(_socket_hash "$1").pid"
}

# 清理聚焦 tab 的颜色 + 恢复非聚焦的 blue-paused tab
cleanup_focused_tabs() {
    local socket="$1"
    local ls_json
    ls_json=$(kitty @ --to "$socket" ls 2>/dev/null) || return

    # 一次 ls 同时输出聚焦和非聚焦 tab（格式："F tab_id" 或 "U tab_id"）
    local tab_list
    tab_list=$(echo "$ls_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for os_win in data:
    os_focused = os_win.get("is_focused", False)
    for tab in os_win.get("tabs", []):
        focused = os_focused and tab.get("is_focused", False)
        kind = "F" if focused else "U"
        print(kind, tab.get("id"))
' 2>/dev/null)

    local hash
    hash=$(_socket_hash "$socket")

    while IFS=' ' read -r kind tid; do
        [ -z "$tid" ] && continue
        local sf="${STATE_DIR}/kitty-tab-${hash}-${tid}"
        [ -f "$sf" ] || continue
        local color
        color=$(cat "$sf")

        if [ "$kind" = "F" ]; then
            # 聚焦 tab：蓝色暂停，红/黄清除
            if [ "$color" = "blue" ]; then
                debug "cleanup: tab $tid blue -> blue-paused"
                kitty @ --to "$socket" set-tab-color --match "id:$tid" \
                    active_bg=NONE active_fg=NONE \
                    inactive_bg=NONE inactive_fg=NONE 2>/dev/null || true
                echo "blue-paused" > "$sf"
            elif [ "$color" != "blue-paused" ]; then
                debug "cleanup: tab $tid focused (was $color), resetting"
                kitty @ --to "$socket" set-tab-color --match "id:$tid" \
                    active_bg=NONE active_fg=NONE \
                    inactive_bg=NONE inactive_fg=NONE 2>/dev/null || true
                rm -f "$sf"
            fi
        else
            # 非聚焦 tab：恢复 blue-paused → blue
            if [ "$color" = "blue-paused" ]; then
                debug "restore: tab $tid blue-paused -> blue"
                kitty @ --to "$socket" set-tab-color --match "id:$tid" \
                    active_bg=#1E90FF active_fg=#FFFFFF \
                    inactive_bg=#1565C0 inactive_fg=#FFFFFF 2>/dev/null || true
                echo "blue" > "$sf"
            fi
        fi
    done <<< "$tab_list"
}

# 查询窗口所在 tab（返回 "tab_id 0/1"）
get_tab_info() {
    local socket="$1" window_id="$2"
    kitty @ --to "$socket" ls 2>/dev/null | python3 -c '
import json, sys
wid = sys.argv[1]
data = json.load(sys.stdin)
for os_win in data:
    os_focused = os_win.get("is_focused", False)
    for tab in os_win.get("tabs", []):
        for win in tab.get("windows", []):
            if str(win.get("id")) == wid:
                focused = os_focused and tab.get("is_focused", False) and win.get("is_focused", False)
                tid = tab.get("id")
                print(f"{tid} {1 if focused else 0}")
                sys.exit(0)
' "$window_id" 2>/dev/null
}

# 设置 tab 颜色并写状态文件（红色优先于黄色）
set_tab_color() {
    local socket="$1" tab_id="$2" color_type="$3"
    local sf
    sf=$(_state_file "$socket" "$tab_id")

    # 优先级：red > yellow > blue
    local current=""
    [ -f "$sf" ] && current=$(cat "$sf")

    if [ "$color_type" = "yellow" ] && [ "$current" = "red" ]; then
        debug "tab $tab_id already red, skip yellow"
        return 0
    fi
    if [ "$color_type" = "blue" ] && { [ "$current" = "red" ] || [ "$current" = "yellow" ]; }; then
        debug "tab $tab_id already $current, skip blue"
        return 0
    fi

    if [ "$color_type" = "red" ]; then
        kitty @ --to "$socket" set-tab-color --match "id:$tab_id" \
            active_bg=#FF0000 active_fg=#FFFFFF \
            inactive_bg=#AA0000 inactive_fg=#FFFFFF 2>/dev/null || true
    elif [ "$color_type" = "yellow" ]; then
        kitty @ --to "$socket" set-tab-color --match "id:$tab_id" \
            active_bg=#FFD700 active_fg=#000000 \
            inactive_bg=#B8960C inactive_fg=#000000 2>/dev/null || true
    elif [ "$color_type" = "blue" ]; then
        kitty @ --to "$socket" set-tab-color --match "id:$tab_id" \
            active_bg=#1E90FF active_fg=#FFFFFF \
            inactive_bg=#1565C0 inactive_fg=#FFFFFF 2>/dev/null || true
    fi

    echo "$color_type" > "$sf"
    debug "set tab $tab_id to $color_type (state: $sf)"
}

# 确保共享后台轮询进程运行（每个 kitty 实例一个）
ensure_poller() {
    local socket="$1"
    local pid_file
    pid_file=$(_poller_pid_file "$socket")

    # 已有 poller 在运行则跳过
    if [ -f "$pid_file" ]; then
        local old_pid
        old_pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
            debug "poller already running (pid $old_pid)"
            return 0
        fi
        rm -f "$pid_file"
    fi

    # 启动共享 poller（后台子进程）
    (
        local sock="$socket"
        local hash pid_f
        hash=$(_socket_hash "$sock")
        pid_f=$(_poller_pid_file "$sock")

        sleep 2

        for _ in $(seq 1 1800); do
            # 没有状态文件则退出
            local has_state=false
            for sf in "${STATE_DIR}"/kitty-tab-"${hash}"-*; do
                [ -f "$sf" ] && { has_state=true; break; }
            done
            if [ "$has_state" = false ]; then
                debug "poller: no state files, exiting"
                rm -f "$pid_f"
                exit 0
            fi

            cleanup_focused_tabs "$sock"
            sleep 1
        done

        # 超时清理所有状态文件
        debug "poller: timeout, cleaning all"
        for sf in "${STATE_DIR}"/kitty-tab-"${hash}"-*; do
            [ -f "$sf" ] && rm -f "$sf"
        done
        rm -f "$pid_f"
    ) >/dev/null 2>&1 &

    echo "$!" > "$pid_file"
    debug "poller launched (pid $!)"
}
