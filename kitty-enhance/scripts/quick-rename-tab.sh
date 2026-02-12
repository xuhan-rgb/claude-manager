#!/bin/bash
# quick-rename-tab.sh - 快速重命名（仅名称）

set -e

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"

read -rp "Tab 名称: " NAME
[ -n "$NAME" ] && kitty @ --to "$KITTY_SOCKET" set-tab-title "$NAME"
