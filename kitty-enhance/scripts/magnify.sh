#!/usr/bin/env bash
# magnify.sh — 将当前焦点 kitty window 实时镜像到一个独立 OS 窗口
# 原 window 完全不受影响（只读镜像，基于 `kitten @ get-text` 轮询）
#
# 用法 (kitty.conf):
#   map kitty_mod+m launch --type=background --copy-env ~/.config/kitty/scripts/magnify.sh
#
# 手动调试:
#   bash ~/.config/kitty/scripts/magnify.sh
#   tail -f /tmp/kitty-magnify.log

set -uo pipefail

LOG=/tmp/kitty-magnify.log
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >>"$LOG"; }
log "=== start (pid=$$, ppid=$PPID) ==="
log "env: KITTY_LISTEN_ON=${KITTY_LISTEN_ON:-<unset>} KITTY_PID=${KITTY_PID:-<unset>} PATH=${PATH}"

die() {
    notify-send "kitty-magnify" "$1" 2>/dev/null || echo "[magnify] $1" >&2
    log "FATAL: $1"
    exit 1
}

# 选 CLI：优先 kitten，其次 kitty
if command -v kitten >/dev/null 2>&1; then
    KCLI=(kitten @)
elif command -v kitty >/dev/null 2>&1; then
    KCLI=(kitty @)
else
    die "找不到 kitten/kitty 命令"
fi
log "Using CLI: ${KCLI[*]}"

# 选 socket：env 优先，回退到 kitty-enhance 默认的 unix:@mykitty
SOCKET="${KITTY_LISTEN_ON:-unix:@mykitty}"
log "Trying socket: $SOCKET"

# 连接 + ls
if ! ls_out=$("${KCLI[@]}" --to "$SOCKET" ls 2>>"$LOG"); then
    die "remote control 不通 (socket=$SOCKET, 详见 $LOG)"
fi
log "ls OK (${#ls_out} bytes)"

# 解析焦点 window id
focused_id=$(printf '%s' "$ls_out" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception as e:
    print(f"json: {e}", file=sys.stderr); sys.exit(1)
for o in data:
    for t in o.get("tabs", []):
        for w in t.get("windows", []):
            if w.get("is_focused"):
                print(w["id"]); sys.exit(0)
print("no is_focused window in ls output", file=sys.stderr)
sys.exit(1)
' 2>>"$LOG") || true

if [ -z "${focused_id:-}" ]; then
    die "未定位到焦点 window（详见 $LOG）"
fi
log "focused_id=$focused_id"

# 提前解析尺寸（外层 env 才能读到用户 export 的 MAGNIFY_COLS/ROWS）
MAG_COLS="${MAGNIFY_COLS:-70}"
MAG_ROWS="${MAGNIFY_ROWS:-28}"
log "Target size: ${MAG_COLS}c x ${MAG_ROWS}r"

# 拉起镜像 OS 窗口（用 --env 把所有需要的变量透传给内层 bash）
"${KCLI[@]}" --to "$SOCKET" launch \
    --type=os-window \
    --os-window-class=kitty-magnify \
    --os-window-title="Magnify: kitty win ${focused_id}" \
    --env="KITTY_MAGNIFY_SRC=${focused_id}" \
    --env="KITTY_MAGNIFY_SOCKET=${SOCKET}" \
    --env="KITTY_MAGNIFY_COLS=${MAG_COLS}" \
    --env="KITTY_MAGNIFY_ROWS=${MAG_ROWS}" \
    bash -c '
set -u
src_id="${KITTY_MAGNIFY_SRC}"
sock="${KITTY_MAGNIFY_SOCKET}"
cols="${KITTY_MAGNIFY_COLS}"
rows="${KITTY_MAGNIFY_ROWS}"
KCLI=(kitten @); command -v kitten >/dev/null 2>&1 || KCLI=(kitty @)
trap "exit 0" INT TERM
if "${KCLI[@]}" --to "$sock" resize-os-window --self --action=resize --unit=cells --width="$cols" --height="$rows" >>/tmp/kitty-magnify.log 2>&1; then
    echo "[$(date +%H:%M:%S)] mirror resize OK -> ${cols}c x ${rows}r" >>/tmp/kitty-magnify.log
else
    echo "[$(date +%H:%M:%S)] mirror resize FAILED (rc=$?)" >>/tmp/kitty-magnify.log
fi
printf "\033[2J\033[H"
last=""
while out=$("${KCLI[@]}" --to "$sock" get-text --match "id:${src_id}" --extent screen --ansi 2>/dev/null); do
    if [ "$out" != "$last" ]; then
        printf "\033[H"; printf "%s" "$out"; printf "\033[J"
        last="$out"
    fi
    sleep 0.3
done
printf "\n\n\033[1;31m── source window %s closed ──\033[0m\n" "$src_id"
read -r -p "press enter to close: " _
' >>"$LOG" 2>&1

log "launch exit=$?, done"
