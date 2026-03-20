# ========================================
# ========================================
# Kitty Tab 管理函数 (kitty-enhance)
# ========================================
# ========================================

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

# 别名
alias tr='tab-rename'
alias tq='tab-quick'
alias tp='tab-project'
alias tc='tab-reset'
alias ta='tab-alert'
