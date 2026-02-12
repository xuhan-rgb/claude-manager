#!/bin/bash
# ============================================================
# Kitty 配置一键安装脚本
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$HOME/.config/kitty"

echo "⏳ 安装 Kitty 配置..."

# 创建目标目录
mkdir -p "$TARGET_DIR"

# 备份旧配置
if [ -f "$TARGET_DIR/kitty.conf" ] && [ ! -L "$TARGET_DIR/kitty.conf" ]; then
    BACKUP="$TARGET_DIR/kitty.conf.bak.$(date +%Y%m%d_%H%M%S)"
    mv "$TARGET_DIR/kitty.conf" "$BACKUP"
    echo "📦 已备份旧配置到: $BACKUP"
elif [ -L "$TARGET_DIR/kitty.conf" ]; then
    rm "$TARGET_DIR/kitty.conf"
    echo "🔗 已移除旧软链接"
fi

# 复制配置文件
cp "$SCRIPT_DIR/kitty.conf" "$TARGET_DIR/kitty.conf"
cp "$SCRIPT_DIR/theme.conf" "$TARGET_DIR/theme.conf"
echo "📄 已复制配置到: $TARGET_DIR/"

echo ""
echo "✅ 安装完成！"
echo ""
echo "快捷键速查："
echo "  新建标签:       Alt+Enter"
echo "  新建窗口:       Alt+n"
echo "  同目录新窗口:   Ctrl+Enter"
echo "  窗口切换:       Ctrl+方向键"
echo "  标签切换:       Alt+左/右"
echo "  窗口大小:       Ctrl+Shift+方向键"
echo "  全屏:           Ctrl+Shift+f"
echo "  关闭窗口:       Ctrl+Shift+w"
echo ""
echo "⚠️  需要重启 Kitty 或新开标签页生效"
echo ""
echo "详细文档: $SCRIPT_DIR/README.md"
