# ========================================
# ========================================
# Kitty Tab 管理函数 (kitty-enhance)
# ========================================
# ========================================

# 基础目录（从本文件位置推导，支持 repo 和安装后两种场景）
_KITTY_ENHANCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# 使用 kitty 环境变量获取 socket
_kitty_socket() {
    echo "${KITTY_LISTEN_ON:-unix:@mykitty}"
}

_codex_monitor_script() {
    echo "$HOME/.config/kitty/scripts/codex-event-monitor.py"
}

_codex_target_cwd() {
    local target="$PWD"
    local expect_value=""
    local arg=""

    for arg in "$@"; do
        if [ -n "$expect_value" ]; then
            target="$arg"
            expect_value=""
            continue
        fi

        case "$arg" in
            -C|--cd)
                expect_value="1"
                ;;
            --cd=*)
                target="${arg#--cd=}"
                ;;
        esac
    done

    if [ -n "$target" ]; then
        python3 - "$target" <<'PY' 2>/dev/null || printf '%s\n' "$target"
import os
import sys

print(os.path.realpath(os.path.expanduser(sys.argv[1])))
PY
    else
        printf '%s\n' "$PWD"
    fi
}

_start_codex_notify_monitor() {
    [ "${KITTY_ENHANCE_CODEX_NOTIFY:-1}" = "1" ] || return 0
    [ -n "${KITTY_WINDOW_ID:-}" ] || return 0

    local monitor
    monitor="$(_codex_monitor_script)"
    [ -f "$monitor" ] || return 0

    local pidfile="/tmp/kitty-codex-monitor-${KITTY_WINDOW_ID}.pid"
    if [ -f "$pidfile" ]; then
        local old_pid=""
        read -r old_pid < "$pidfile"
        if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
            kill "$old_pid" 2>/dev/null || true
        fi
        rm -f "$pidfile"
    fi

    local target_cwd
    target_cwd="$(_codex_target_cwd "$@")"

    python3 "$monitor" \
        --window-id "${KITTY_WINDOW_ID}" \
        --kitty-socket "$(_kitty_socket)" \
        --cwd "$target_cwd" \
        >/dev/null 2>&1 &
    echo "$!" > "$pidfile"
}

# 重命名 tab（完整版）
tab-rename() {
    local name="${1:-}"
    if [ -z "$name" ]; then
        ~/.config/kitty/scripts/rename-tab.sh
    else
        kitty @ --to "$(_kitty_socket)" set-tab-title "$name"
    fi
}

# 快速重命名
tab-quick() {
    ~/.config/kitty/scripts/quick-rename-tab.sh
}

# 自动检测项目名+git分支
tab-project() {
    local name="${1:-$(basename "$PWD")}"
    local branch=$(git branch --show-current 2>/dev/null)
    [ -n "$branch" ] && name="$name ($branch)"
    kitty @ --to "$(_kitty_socket)" set-tab-title "$name"
}

# 重置 tab 颜色
tab-reset() {
    kitty @ --to "$(_kitty_socket)" set-tab-color \
        active_bg=NONE active_fg=NONE \
        inactive_bg=NONE inactive_fg=NONE
}

# 设置 tab 为红色（手动）
tab-alert() {
    kitty @ --to "$(_kitty_socket)" set-tab-color \
        active_bg=#FF0000 active_fg=#FFFFFF
}

# 设置 tab 为黄色（需要注意）
tab-warning() {
    kitty @ --to "$(_kitty_socket)" set-tab-color \
        active_bg=#FFD700 active_fg=#000000
}

# 设置 tab 为绿色（完成）
tab-done() {
    kitty @ --to "$(_kitty_socket)" set-tab-color \
        active_bg=#00FF00 active_fg=#000000
}

codex() {
    _start_codex_notify_monitor "$@"
    command codex "$@"
}

# 开发标记（toggle * 前缀，支持 Kitty Tab 和 tmux 窗口）
tab-dev() {
    if [ -n "$TMUX" ]; then
        # tmux 窗口
        local name
        name=$(tmux display-message -p '#W')
        if [ "${name#\*}" != "$name" ]; then
            tmux rename-window "${name#\*}"
            tmux set-window-option automatic-rename on
        else
            tmux rename-window "*${name}"
            tmux set-window-option automatic-rename off
        fi
    elif [ -n "$KITTY_WINDOW_ID" ]; then
        # Kitty Tab
        local name
        name=$(kitty @ --to "$(_kitty_socket)" ls 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for w in data:
    for t in w['tabs']:
        for win in t['windows']:
            if win['id'] == $KITTY_WINDOW_ID:
                print(t.get('title', ''))
                sys.exit(0)
" 2>/dev/null)
        if [ "${name#\*}" != "$name" ]; then
            kitty @ --to "$(_kitty_socket)" set-tab-title "${name#\*}"
        else
            kitty @ --to "$(_kitty_socket)" set-tab-title "*${name}"
        fi
    else
        echo "不在 Kitty 或 tmux 中"
        return 1
    fi
}

# === Tab 颜色自动清除（precmd hook） ===
# 每次 shell 提示符渲染时检查：如果当前 tab 有红/黄警告色，自动清除
# 纯内建命令快路径，无子进程开销
_kitty_tab_color_precmd() {
    [ -n "${KITTY_WINDOW_ID:-}" ] || return
    local _cache="/tmp/kitty-tabcache-${KITTY_WINDOW_ID}"
    [ -f "$_cache" ] || return
    local _sf
    read -r _sf < "$_cache"
    [ -f "$_sf" ] || return
    local _cur
    read -r _cur < "$_sf"
    case "$_cur" in
        red|yellow)
            # 提取 tab_id：state file 名为 kitty-tab-{hash}-{tab_id}
            local _tab_id="${_sf##*-}"
            kitty @ --to "$(_kitty_socket)" set-tab-color --match "id:$_tab_id" \
                active_bg=NONE active_fg=NONE \
                inactive_bg=NONE inactive_fg=NONE 2>/dev/null || true
            rm -f "$_sf" "$_cache"
            ;;
    esac
}

# 注册 precmd hook（兼容 bash 和 zsh）
if [ -n "${ZSH_VERSION:-}" ]; then
    autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook precmd _kitty_tab_color_precmd
elif [ -n "${BASH_VERSION:-}" ]; then
    if [[ ! "${PROMPT_COMMAND:-}" == *_kitty_tab_color_precmd* ]]; then
        PROMPT_COMMAND="_kitty_tab_color_precmd${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
    fi
fi

# 锁定窗口（禁用关闭按钮 + Alt+F4，只能通过 kill 关闭）
# 用法: win-lock        — 锁定当前窗口
#       win-lock -u     — 解锁当前窗口
#       win-unlock      — 同上
win-lock() {
    [ -n "${WINDOWID:-}" ] || { echo "错误: 无法获取 X11 窗口 ID"; return 1; }
    command -v xprop >/dev/null 2>&1 || { echo "错误: 需要安装 xprop (apt install x11-utils)"; return 1; }

    if [ "${1:-}" = "-u" ] || [ "${1:-}" = "--unlock" ]; then
        # 解锁：恢复所有窗口功能
        xprop -id "$WINDOWID" -f _MOTIF_WM_HINTS 32c \
            -set _MOTIF_WM_HINTS "0x1, 0x1, 0x0, 0x0, 0x0"
        echo "窗口已解锁"
    else
        # 锁定：MWM_FUNC_ALL(0x1) | MWM_FUNC_CLOSE(0x20) = 0x21
        # 含义：启用所有功能，但排除关闭
        xprop -id "$WINDOWID" -f _MOTIF_WM_HINTS 32c \
            -set _MOTIF_WM_HINTS "0x1, 0x21, 0x0, 0x0, 0x0"
        echo "窗口已锁定（只能通过 kill 关闭）"
    fi
}

win-unlock() { win-lock -u; }


# ========================================
# Kitty Tab 会话保存与恢复
# ========================================

_tab_session_dir() {
    echo "${KITTY_ENHANCE_SESSION_DIR:-$HOME/.config/kitty-enhance/sessions}"
}

_tab_snapshot_script() {
    echo "${_KITTY_ENHANCE_DIR}/scripts/session-snapshot.py"
}

# 保存当前 Kitty 全部 Tab
tab-save() {
    local name="${1:-}"
    if [ -z "$name" ]; then
        echo "用法: tab-save <name>"
        echo "示例: tab-save work"
        return 1
    fi

    if [ -z "${KITTY_WINDOW_ID:-}" ]; then
        echo "错误: 不在 Kitty 终端中"
        return 1
    fi

    local dir
    dir="$(_tab_session_dir)"
    mkdir -p "$dir"

    local session_file="$dir/${name}.session"
    local meta_file="$dir/${name}.meta.json"
    local snapshot_script
    snapshot_script="$(_tab_snapshot_script)"

    if [ ! -f "$snapshot_script" ]; then
        echo "错误: 找不到 session-snapshot.py: $snapshot_script"
        return 1
    fi

    local kitty_json
    kitty_json=$(kitty @ --to "$(_kitty_socket)" ls 2>/dev/null)
    if [ $? -ne 0 ] || [ -z "$kitty_json" ]; then
        echo "错误: kitty @ ls 失败（需要 allow_remote_control yes）"
        return 1
    fi

    local overwrite=""
    if [ -f "$session_file" ]; then
        overwrite=" (覆盖)"
    fi

    echo "$kitty_json" | python3 "$snapshot_script" "$name" > "$session_file"
    if [ $? -ne 0 ]; then
        echo "错误: 生成 session 文件失败"
        rm -f "$session_file"
        return 1
    fi

    local tab_count
    tab_count=$(grep -c 'new_tab' "$session_file")
    echo "$kitty_json" | python3 -c "
import json, sys
from datetime import datetime
data = json.load(sys.stdin)
tabs = data[0]['tabs']
windows = sum(len(t['windows']) for t in tabs)
meta = {
    'name': sys.argv[1],
    'saved_at': datetime.now().isoformat(timespec='seconds'),
    'tabs': len(tabs),
    'windows': windows,
}
json.dump(meta, sys.stdout, ensure_ascii=False, indent=2)
print()
" "$name" > "$meta_file"

    echo "已保存${overwrite}: $name ($tab_count tabs)"
    echo "  文件: $session_file"
}

# 恢复 Kitty Tab 会话
tab-restore() {
    local name="${1:-}"
    if [ -z "$name" ]; then
        echo "用法: tab-restore <name>"
        tab-list
        return 1
    fi

    local session_file
    session_file="$(_tab_session_dir)/${name}.session"

    if [ ! -f "$session_file" ]; then
        echo "错误: session '$name' 不存在"
        tab-list
        return 1
    fi

    kitty --session "$session_file" --detach
    echo "已恢复: $name (新 Kitty 窗口)"
}

# 列出所有已保存的 Tab 会话
tab-list() {
    local dir
    dir="$(_tab_session_dir)"

    if [ ! -d "$dir" ] || ! ls "$dir"/*.meta.json >/dev/null 2>&1; then
        echo "没有已保存的 session"
        return 0
    fi

    echo "已保存的 session:"
    echo ""
    for meta in "$dir"/*.meta.json; do
        python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    m = json.load(f)
print(f\"  {m['name']:<16} {m['tabs']} tabs, {m['windows']} windows  ({m['saved_at']})\")
" "$meta" 2>/dev/null
    done
}

# 删除指定 Tab 会话
tab-delete() {
    local name="${1:-}"
    if [ -z "$name" ]; then
        echo "用法: tab-delete <name>"
        tab-list
        return 1
    fi

    local dir
    dir="$(_tab_session_dir)"
    local session_file="$dir/${name}.session"
    local meta_file="$dir/${name}.meta.json"

    if [ ! -f "$session_file" ]; then
        echo "错误: session '$name' 不存在"
        return 1
    fi

    rm -f "$session_file" "$meta_file"
    echo "已删除: $name"
}

# 帮助信息
tab-help() {
    cat <<'HELP'
Kitty Tab 管理命令 (kitty-enhance)

  Tab 操作:
    tab-rename [name]     重命名当前 Tab
    tab-quick             快速重命名（交互式）
    tab-project [name]    自动设为 项目名(分支)
    tab-dev               Toggle 开发标记 (* 前缀)

  Tab 颜色:
    tab-alert             标记为红色
    tab-warning           标记为黄色
    tab-done              标记为绿色
    tab-reset             重置颜色

  Session 管理:
    tab-save <name>       保存所有 Tab 状态
    tab-restore <name>    恢复 Tab（新 Kitty 窗口）
    tab-list              列出已保存的 session
    tab-delete <name>     删除 session

  窗口:
    win-lock              锁定窗口（禁用关闭按钮）
    win-unlock            解锁窗口

  输入 tab-help 查看本帮助
HELP
}

