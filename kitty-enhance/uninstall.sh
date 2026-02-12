#!/bin/bash
# uninstall.sh - 卸载 kitty-enhance
set -e

KITTY_SCRIPTS_DIR="$HOME/.config/kitty/scripts"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"
KITTY_CONF="$HOME/.config/kitty/kitty.conf"

echo "=========================================="
echo "  卸载 kitty-enhance"
echo "=========================================="

# 1. 删除 Kitty 脚本
echo "[1/5] 删除 Kitty 脚本..."
rm -f "$KITTY_SCRIPTS_DIR/rename-tab.sh"
rm -f "$KITTY_SCRIPTS_DIR/quick-rename-tab.sh"
rm -f "$KITTY_SCRIPTS_DIR/reset-tab-color.sh"
rm -f "$KITTY_SCRIPTS_DIR/on-bell.sh"
rm -f "$KITTY_SCRIPTS_DIR/tab-color-common.sh"
echo "  -> 已删除"

# 2. 删除 Claude Hook 链接
echo "[2/5] 删除 Claude Hooks..."
rm -f "$CLAUDE_HOOKS_DIR/on-stop.sh"
rm -f "$CLAUDE_HOOKS_DIR/on-notify.sh"
rm -f "$CLAUDE_HOOKS_DIR/on-bell.sh"
rm -f "$CLAUDE_HOOKS_DIR/tab-color-common.sh"
echo "  -> 已删除"

# 3. 清理 Tab 颜色状态文件和 poller
echo "[3/5] 清理运行时状态..."
rm -f /tmp/kitty-tab-*
echo "  -> 已清理"

# 4. 清理 kitty.conf
echo "[4/5] 清理 Kitty 配置..."
if [ -f "$KITTY_CONF" ]; then
    sed -i '/# === claude-manager ===/,/# === end claude-manager ===/d' "$KITTY_CONF"
    echo "  -> 已清理"
fi

# 5. 清理 shell 配置（兼容 bashrc 和 zshrc）
echo "[5/5] 清理 Shell 配置..."
for rc_file in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.zshrc_custom"; do
    if [ -f "$rc_file" ]; then
        sed -i '/# Kitty Tab.*kitty-enhance\|# source claude-manager/d' "$rc_file"
        sed -i '\|kitty-enhance/shell-functions.sh\|d' "$rc_file"
        sed -i '\|claude-manager/shell-functions.sh\|d' "$rc_file"
    fi
done
echo "  -> 已清理"

echo ""
echo "=========================================="
echo "  卸载完成!"
echo "=========================================="
echo ""
echo "注意: Claude settings.json 中的 hooks 配置未删除"
echo "如需手动删除，请编辑 ~/.claude/settings.json"
echo ""
echo "请执行以下命令使配置生效:"
echo "  source ~/.bashrc  # 或 source ~/.zshrc"
echo "  kitty @ load-config"
