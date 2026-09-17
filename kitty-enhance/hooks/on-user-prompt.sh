#!/bin/bash
# Record the latest Claude prompt against this exact Kitty window.

WINDOW_ID="${KITTY_WINDOW_ID:-}"
[ -z "$WINDOW_ID" ] && exit 0

TASK_SUMMARY=$(python3 -c '
import json
import sys

try:
    prompt = str((json.load(sys.stdin) or {}).get("prompt", ""))
except Exception:
    prompt = ""

for raw_line in prompt.splitlines():
    line = " ".join(raw_line.strip().split())
    if line:
        print(line[:72])
        break
')

[ -z "$TASK_SUMMARY" ] && exit 0

source "$(dirname "$(readlink -f "$0")")/feishu-register.sh"
_feishu_register "working" "$TASK_SUMMARY"

exit 0
