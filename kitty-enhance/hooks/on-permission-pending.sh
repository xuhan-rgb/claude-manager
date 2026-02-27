#!/bin/bash
# on-permission-pending.sh - Claude Code 权限弹窗出现时触发（hooks.Notification）
# 功能：写 pending 文件到 /tmp/feishu-bridge/，供飞书桥接守护进程监控
# 抓取终端屏幕内容 + Tab 标题，提供完整上下文

WINDOW_ID="${KITTY_WINDOW_ID:-}"
[ -z "$WINDOW_ID" ] && exit 0

STATE_DIR="/tmp/feishu-bridge"
mkdir -p "$STATE_DIR"

KITTY_SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"

# 读取 stdin JSON（Notification Hook 提供的上下文信息）
INPUT=$(cat)

# 过滤非权限弹窗的通知（如"等待输入"、"任务完成"）
# 只有真正的权限请求才需要写 pending 文件
MSG=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('message',''))" 2>/dev/null || true)

# 抓取终端屏幕内容（权限弹窗的完整信息）
SCREEN_TEXT=$(kitty @ --to "$KITTY_SOCKET" get-text --match "id:$WINDOW_ID" --extent=screen 2>/dev/null || true)

# 获取 Tab 标题（通常是项目名/任务名）
TAB_TITLE=$(kitty @ --to "$KITTY_SOCKET" ls 2>/dev/null | python3 -c "
import json, sys
wid = '$WINDOW_ID'
try:
    data = json.load(sys.stdin)
    for os_win in data:
        for tab in os_win.get('tabs', []):
            for win in tab.get('windows', []):
                if str(win.get('id')) == wid:
                    print(tab.get('title', ''))
                    sys.exit(0)
except: pass
" 2>/dev/null || true)

# 通过环境变量传递给 Python
export SCREEN_TEXT TAB_TITLE
export HOOK_INPUT="$INPUT"

# 写入 pending 文件
python3 << 'PYEOF'
import json, time, sys, os

# 读取环境变量和外部数据
window_id = os.environ.get('KITTY_WINDOW_ID', '')
kitty_socket = os.environ.get('KITTY_LISTEN_ON', '')

# 读取 hook stdin JSON
try:
    hook_data = json.loads(os.environ.get('HOOK_INPUT', '{}'))
except Exception:
    hook_data = {}

# 获取屏幕内容，取最后 25 行（权限弹窗通常在底部）
screen = os.environ.get('SCREEN_TEXT', '')
lines = [l for l in screen.strip().split('\n') if l.strip()] if screen else []
screen_tail = '\n'.join(lines[-25:]) if lines else ''

pending = {
    'window_id': window_id,
    'kitty_socket': kitty_socket,
    'tab_title': os.environ.get('TAB_TITLE', ''),
    'message': hook_data.get('message', ''),
    'screen_tail': screen_tail,
    'timestamp': time.time(),
    'notified': False,
    'feishu_msg_id': None,
}

state_dir = '/tmp/feishu-bridge'
path = os.path.join(state_dir, f'{window_id}.json')
with open(path, 'w') as f:
    json.dump(pending, f, ensure_ascii=False, indent=2)
PYEOF

# 终端注册：状态更新为 waiting
source "$(dirname "$(readlink -f "$0")")/feishu-register.sh"
_feishu_register "waiting"

exit 0
