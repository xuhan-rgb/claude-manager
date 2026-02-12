# ========================================
# ========================================
# Kitty Tab 管理函数 (kitty-enhance)
# ========================================
# ========================================

# 使用 kitty 环境变量获取 socket
_kitty_socket() {
    echo "${KITTY_LISTEN_ON:-unix:@mykitty}"
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

# 别名
alias tr='tab-rename'
alias tq='tab-quick'
alias tp='tab-project'
alias tc='tab-reset'
alias ta='tab-alert'
