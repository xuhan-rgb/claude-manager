#!/bin/bash
# 实时查看 Claude Manager 日志

LOG_FILE="$HOME/.config/claude-manager/logs/app.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ 日志文件不存在: $LOG_FILE"
    echo ""
    echo "💡 请先启动 claude-manager"
    exit 1
fi

echo "📋 实时日志查看"
echo "   日志文件: $LOG_FILE"
echo "   按 Ctrl+C 停止"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 实时跟踪日志，高亮关键信息
tail -f "$LOG_FILE" | grep --line-buffered -E "\[状态摘要\]|\[状态检测\]|\[活动监控\]|\[内容分析\]|\[状态转换\]|\[状态保持\]|━━━" | while read line; do
    # 高亮不同的日志类型
    if echo "$line" | grep -q "\[状态转换\]"; then
        echo -e "\033[1;32m$line\033[0m"  # 绿色加粗
    elif echo "$line" | grep -q "\[状态摘要\]"; then
        echo -e "\033[1;34m$line\033[0m"  # 蓝色加粗
    elif echo "$line" | grep -q "━━━"; then
        echo -e "\033[1;34m$line\033[0m"  # 蓝色加粗（分隔线）
    elif echo "$line" | grep -q "\[状态检测\]"; then
        echo -e "\033[1;36m$line\033[0m"  # 青色加粗
    elif echo "$line" | grep -q "\[活动监控\]"; then
        echo -e "\033[1;33m$line\033[0m"  # 黄色加粗
    elif echo "$line" | grep -q "\[内容分析\]"; then
        echo -e "\033[0;35m$line\033[0m"  # 紫色
    else
        echo "$line"
    fi
done
