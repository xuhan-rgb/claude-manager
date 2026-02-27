#!/bin/bash
set -euo pipefail

# ── 飞书桥接一键配置 ──────────────────────────────────
# 用途：新用户快速配置飞书权限桥接
# 流程：检查依赖 → 获取凭据 → 自动获取 open_id → 写入环境变量

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASHRC="$HOME/.bashrc"

echo ""
echo "⏳ 飞书权限桥接 - 配置向导"
echo "=========================================="
echo ""

# ── 1. 检查 Python 依赖 ──────────────────────────────

echo "⏳ 检查 Python 依赖..."
if python3 -c "import lark_oapi, yaml" 2>/dev/null; then
    echo "✅ lark-oapi 和 pyyaml 已安装"
else
    echo "⏳ 安装依赖..."
    pip install lark-oapi pyyaml -q
    echo "✅ 依赖安装完成"
fi
echo ""

# ── 2. 获取飞书应用凭据 ──────────────────────────────

# 优先从已有环境变量读取
EXISTING_APP_ID="${FEISHU_APP_ID:-}"
EXISTING_APP_SECRET="${FEISHU_APP_SECRET:-}"

echo "── 飞书应用凭据 ──"
echo "（团队共用同一个飞书应用，向管理员获取 App ID 和 App Secret）"
echo ""

if [ -n "$EXISTING_APP_ID" ]; then
    echo "检测到已有环境变量: FEISHU_APP_ID=$EXISTING_APP_ID"
    read -rp "使用现有凭据？(Y/n): " USE_EXISTING
    if [ "${USE_EXISTING,,}" != "n" ]; then
        APP_ID="$EXISTING_APP_ID"
        APP_SECRET="$EXISTING_APP_SECRET"
    else
        read -rp "App ID: " APP_ID
        read -rp "App Secret: " APP_SECRET
    fi
else
    read -rp "App ID: " APP_ID
    read -rp "App Secret: " APP_SECRET
fi

if [ -z "$APP_ID" ] || [ -z "$APP_SECRET" ]; then
    echo "❌ App ID 和 App Secret 不能为空"
    exit 1
fi
echo ""

# ── 3. 自动获取 open_id ──────────────────────────────

EXISTING_USER_ID="${FEISHU_USER_ID:-}"

if [ -n "$EXISTING_USER_ID" ]; then
    echo "检测到已有 FEISHU_USER_ID=$EXISTING_USER_ID"
    read -rp "使用现有 open_id？(Y/n): " USE_EXISTING_UID
    if [ "${USE_EXISTING_UID,,}" != "n" ]; then
        OPEN_ID="$EXISTING_USER_ID"
    else
        OPEN_ID=""
    fi
else
    OPEN_ID=""
fi

if [ -z "$OPEN_ID" ]; then
    echo "── 获取你的 open_id ──"
    echo ""
    echo "接下来会启动飞书连接，请在飞书中搜索机器人并发一条消息。"
    echo "脚本会自动捕获你的 open_id。"
    echo ""
    read -rp "准备好了按 Enter 继续..."
    echo ""
    echo "⏳ 连接飞书中... 请在飞书给机器人发一条消息（随便发什么都行）"
    echo ""

    OPEN_ID=$(timeout 120 python3 -c "
import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
import os

def on_msg(data: P2ImMessageReceiveV1):
    oid = data.event.sender.sender_id.open_id
    print(oid, flush=True)
    os._exit(0)

handler = lark.EventDispatcherHandler.builder('', '') \
    .register_p2_im_message_receive_v1(on_msg) \
    .build()

cli = lark.ws.Client(
    '$APP_ID', '$APP_SECRET',
    event_handler=handler,
    log_level=lark.LogLevel.WARNING,
)
cli.start()
" 2>/dev/null || true)

    if [ -z "$OPEN_ID" ]; then
        echo ""
        echo "⚠️  未收到消息（超时 120 秒）"
        echo "你可以手动输入 open_id（格式: ou_xxxxxxxx）"
        read -rp "open_id: " OPEN_ID
        if [ -z "$OPEN_ID" ]; then
            echo "❌ open_id 不能为空"
            exit 1
        fi
    else
        echo "✅ 捕获到 open_id: $OPEN_ID"
    fi
fi
echo ""

# ── 4. 写入配置 ──────────────────────────────────────

# app_id / app_secret → 环境变量（团队共用）
sed -i '/^# 飞书权限桥接配置$/,/^export FEISHU_APP_SECRET=/d' "$BASHRC" 2>/dev/null || true
sed -i '/^export FEISHU_APP_ID=/d' "$BASHRC" 2>/dev/null || true
sed -i '/^export FEISHU_APP_SECRET=/d' "$BASHRC" 2>/dev/null || true

cat >> "$BASHRC" << EOF

# 飞书权限桥接配置
export FEISHU_APP_ID="$APP_ID"
export FEISHU_APP_SECRET="$APP_SECRET"
EOF

echo "✅ 环境变量已写入 $BASHRC (APP_ID, APP_SECRET)"

# 立即导出到当前 shell
export FEISHU_APP_ID="$APP_ID"
export FEISHU_APP_SECRET="$APP_SECRET"

# user_id → config.yaml（每人不同）
CONFIG_FILE="$SCRIPT_DIR/config.yaml"
cat > "$CONFIG_FILE" << EOF
feishu:
  user_id: "$OPEN_ID"

bridge:
  wait_minutes: 5      # 等待多久后发飞书通知
  poll_interval: 2     # 扫描 pending 文件间隔（秒）
  expire_minutes: 30   # pending 文件过期清理时间
EOF

echo "✅ user_id 已写入 $CONFIG_FILE"

echo ""

# ── 5. 安装 Hook ─────────────────────────────────────

HOOK_DIR="$HOME/.claude/hooks"
mkdir -p "$HOOK_DIR"

HOOK_SRC="$SCRIPT_DIR/../hooks/on-permission-pending.sh"
HOOK_DST="$HOOK_DIR/on-permission-pending.sh"

if [ -L "$HOOK_DST" ] || [ -f "$HOOK_DST" ]; then
    echo "✅ Hook 已存在: $HOOK_DST"
else
    ln -sf "$HOOK_SRC" "$HOOK_DST"
    echo "✅ Hook 已安装: $HOOK_DST"
fi

# 检查 settings.json 是否已注册
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    if grep -q "on-permission-pending.sh" "$SETTINGS"; then
        echo "✅ Hook 已在 settings.json 中注册"
    else
        echo ""
        echo "⚠️  需要手动在 ~/.claude/settings.json 的 Notification hooks 中添加:"
        echo '  {"type": "command", "command": "'$HOOK_DST'"}'
        echo ""
    fi
fi

echo ""
echo "=========================================="
echo "✅ 配置完成！"
echo ""
echo "请先执行:"
echo "  source ~/.bashrc"
echo ""
echo "然后启动守护进程:"
echo "  cd $SCRIPT_DIR && python daemon.py"
echo ""
echo "查看状态:"
echo "  python daemon.py status"
echo ""
echo "停止:"
echo "  python daemon.py stop"
echo "=========================================="
