#!/bin/bash
# reset-tab-color.sh - 重置 tab 颜色为默认

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"

kitty @ --to "$KITTY_SOCKET" set-tab-color \
    active_bg=NONE \
    active_fg=NONE \
    inactive_bg=NONE \
    inactive_fg=NONE
