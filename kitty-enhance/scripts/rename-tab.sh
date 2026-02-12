#!/bin/bash
# rename-tab.sh - 完整版 tab 重命名（名称 + 任务描述 + 自动 git）

set -e

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"

# 获取 tab 名称
read -rp "Tab 名称: " NAME
[ -z "$NAME" ] && exit 0

# 获取任务描述（可选）
read -rp "任务描述 (可选，回车跳过): " TASK

# 自动检测 git 分支
GIT_BRANCH=$(git branch --show-current 2>/dev/null) || true
DIR_NAME=$(basename "$PWD")

# 组合标题：有 git 仓库时追加 [目录:分支]，否则只用名称
TITLE="$NAME"
if [ -n "$GIT_BRANCH" ]; then
    TITLE="$TITLE [$DIR_NAME:$GIT_BRANCH]"
fi
[ -n "$TASK" ] && TITLE="$TITLE | $TASK"

kitty @ --to "$KITTY_SOCKET" set-tab-title "$TITLE"
