#!/bin/bash
# ============================================================
# Tmux 配置一键安装脚本
# ============================================================

set -euo pipefail

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/tmux.conf"
TARGET="$HOME/.tmux.conf"

echo "⏳ 安装 Tmux 配置..."

# 检查配置文件是否存在
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ 配置文件不存在: $CONFIG_FILE"
    exit 1
fi

# 处理旧配置
if [ -L "$TARGET" ]; then
    # 如果是软链接，直接删除
    rm "$TARGET"
    echo "🔗 已移除旧软链接"
elif [ -f "$TARGET" ]; then
    # 如果是普通文件，备份
    BACKUP="$TARGET.bak.$(date +%Y%m%d_%H%M%S)"
    mv "$TARGET" "$BACKUP"
    echo "📦 已备份旧配置到: $BACKUP"
fi

# 复制配置文件
cp "$CONFIG_FILE" "$TARGET"
echo "📄 已复制配置到: $TARGET"

# 重载配置（如果 tmux 正在运行）
if tmux list-sessions &>/dev/null; then
    tmux source-file "$TARGET"
    echo "🔄 已重载 tmux 配置"
fi

echo ""
echo "✅ 安装完成！"
echo ""
echo "快捷键速查："
echo "  前缀键:     Ctrl+a"
echo "  左右分屏:   前缀 + h"
echo "  上下分屏:   前缀 + v"
echo "  面板切换:   Alt + h/j/k/l"
echo "  滚轮翻页:   滚动查看历史，打字自动退出"
echo "  重载配置:   前缀 + r"
echo ""
echo "详细文档: $SCRIPT_DIR/README.md"
