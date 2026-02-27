#!/bin/bash
# feishu-register.sh - 终端注册公共函数
# 被 on-tool-use.sh / on-stop.sh / on-permission-pending.sh source 使用

_feishu_register() {
    # 参数: $1 = 状态 (working / completed / waiting)
    local STATUS="$1"
    local WINDOW_ID="${KITTY_WINDOW_ID:-}"
    [ -z "$WINDOW_ID" ] && return 0

    local REGISTRY="/tmp/feishu-bridge/registry.json"
    mkdir -p /tmp/feishu-bridge

    # flock 保证并发安全，-w 1 最多等 1 秒
    (
        flock -w 1 200 || return 0
        python3 -c "
import json, time, os
reg_path = '$REGISTRY'
wid = '$WINDOW_ID'
status = '$STATUS'
socket = os.environ.get('KITTY_LISTEN_ON', '')
cwd = os.environ.get('PWD', '')
try:
    with open(reg_path, 'r') as f: reg = json.load(f)
except: reg = {}
old = reg.get(wid, {})
reg[wid] = {
    'window_id': wid,
    'kitty_socket': socket or old.get('kitty_socket', ''),
    'tab_title': old.get('tab_title', cwd.rsplit('/', 1)[-1] if cwd else ''),
    'cwd': cwd or old.get('cwd', ''),
    'registered_at': old.get('registered_at', time.time()),
    'last_activity': time.time(),
    'status': status,
}
with open(reg_path, 'w') as f: json.dump(reg, f, ensure_ascii=False, indent=2)
" 2>/dev/null
    ) 200>/tmp/feishu-bridge/.registry.lock
}
