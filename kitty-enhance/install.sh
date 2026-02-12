#!/bin/bash
# Kitty 优化安装脚本
# 功能：配置文件、脚本、hooks、shell 函数一键安装

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✅${NC} $*"; }
warning() { echo -e "${YELLOW}⚠️${NC}  $*"; }
error() { echo -e "${RED}❌${NC} $*"; }

# 检查依赖
check_dependencies() {
    info "检查依赖..."

    local missing=()

    if ! command -v kitty &>/dev/null; then
        missing+=("kitty")
    fi

    if ! command -v python3 &>/dev/null; then
        missing+=("python3")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        error "缺少依赖: ${missing[*]}"
        echo ""
        echo "安装方法："
        for dep in "${missing[@]}"; do
            case "$dep" in
                kitty)
                    echo "  Ubuntu/Debian: sudo apt install kitty"
                    echo "  Arch: sudo pacman -S kitty"
                    ;;
                python3)
                    echo "  Ubuntu/Debian: sudo apt install python3"
                    ;;
            esac
        done
        exit 1
    fi

    success "依赖检查通过"
}

# 安装 Kitty 配置
install_kitty_config() {
    info "安装 Kitty 配置..."

    local kitty_config_dir="$HOME/.config/kitty"
    mkdir -p "$kitty_config_dir"

    # 备份旧配置
    if [ -f "$kitty_config_dir/kitty.conf" ]; then
        local backup="$kitty_config_dir/kitty.conf.bak.$(date +%Y%m%d_%H%M%S)"
        cp "$kitty_config_dir/kitty.conf" "$backup"
        info "已备份旧配置到: $backup"
    fi

    # 复制配置
    cp config/kitty/kitty.conf "$kitty_config_dir/"
    cp config/kitty/theme.conf "$kitty_config_dir/"

    success "Kitty 配置已安装"
}

# 安装 Kitty 脚本
install_kitty_scripts() {
    info "安装 Kitty 脚本..."

    local scripts_dir="$HOME/.config/kitty/scripts"
    mkdir -p "$scripts_dir"

    # 复制脚本（先删除旧的，避免同文件错误）
    for script in scripts/*.sh; do
        local name=$(basename "$script")
        rm -f "$scripts_dir/$name"
        cp "$script" "$scripts_dir/"
    done

    # 复制公共模块（on-bell.sh 需要同目录的 tab-color-common.sh）
    if [ -f "hooks/tab-color-common.sh" ]; then
        rm -f "$scripts_dir/tab-color-common.sh"
        cp "hooks/tab-color-common.sh" "$scripts_dir/"
    fi

    chmod +x "$scripts_dir"/*.sh

    success "Kitty 脚本已安装到: $scripts_dir"
}

# 安装 Shell 函数
install_shell_functions() {
    info "安装 Shell 函数..."

    local src="$(pwd)/shell-functions.sh"
    local added=false

    # 按文件是否存在来决定写入哪个 rc（两个都存在则两个都写）
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$rc" ] || continue

        if grep -q "shell-functions.sh" "$rc" 2>/dev/null; then
            info "Shell 函数已在 $(basename "$rc") 中配置"
        else
            echo "" >> "$rc"
            echo "# Kitty Tab 管理函数 (kitty-enhance)" >> "$rc"
            echo "[ -f \"$src\" ] && source \"$src\"" >> "$rc"
            success "已添加 shell 函数到 $rc"
            added=true
        fi
    done

    if [ "$added" = true ]; then
        warning "请运行 'source ~/.bashrc' 或重启终端生效"
    fi
}

# 安装 Claude Code Hooks
install_claude_hooks() {
    info "安装 Claude Code Hooks..."

    local hook_dir="$HOME/.claude/hooks"
    mkdir -p "$hook_dir"

    # 安装每个 hook 脚本
    for hook in hooks/*.sh; do
        [ -f "$hook" ] || continue
        local name=$(basename "$hook")
        local src="$(pwd)/$hook"
        local dst="$hook_dir/$name"

        if [ -L "$dst" ]; then
            rm "$dst"
        elif [ -f "$dst" ]; then
            mv "$dst" "$dst.bak.$(date +%Y%m%d_%H%M%S)"
        fi

        ln -sf "$src" "$dst"
        chmod +x "$src"
        success "  $name → $dst"
    done
}

# 配置 Claude Code settings.json 中的 hooks
configure_claude_hooks() {
    info "配置 Claude Code Hooks（settings.json）..."

    local settings="$HOME/.claude/settings.json"
    local hook_dir="$HOME/.claude/hooks"

    python3 - "$settings" "$hook_dir" << 'PY'
import json, os, shutil, sys, time

settings_path = sys.argv[1]
hook_dir = sys.argv[2]
data = {}

# 要注册的 hook 映射：事件名 → 脚本名
HOOK_MAP = {
    "Stop": "on-stop.sh",
    "Notification": "on-notify.sh",
    "PreToolUse": "on-tool-use.sh",
}

if os.path.exists(settings_path):
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        print("  -> settings.json 解析失败，未做修改（请手动检查）")
        sys.exit(0)

hooks = data.setdefault("hooks", {})
if not isinstance(hooks, dict):
    print("  -> hooks 不是对象，未做修改")
    sys.exit(0)

changed = False
for event, script in HOOK_MAP.items():
    cmd = os.path.join(hook_dir, script)
    event_hooks = hooks.get(event)
    if not isinstance(event_hooks, list):
        event_hooks = []
        hooks[event] = event_hooks

    # 检查是否已存在
    exists = False
    for entry in event_hooks:
        for item in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
            if isinstance(item, dict) and item.get("command") == cmd:
                exists = True
                break
    if not exists:
        event_hooks.append({"hooks": [{"type": "command", "command": cmd}]})
        changed = True
        print(f"  -> 已配置 hooks.{event}: {script}")
    else:
        print(f"  -> hooks.{event} 已包含 {script}，跳过")

if changed:
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    if os.path.exists(settings_path):
        backup = settings_path + ".bak." + time.strftime("%Y%m%d_%H%M%S")
        try:
            shutil.copy2(settings_path, backup)
        except Exception:
            pass
    tmp_path = settings_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, settings_path)

PY

    success "Claude Code Hooks 配置完成"
}

# 验证安装
verify_installation() {
    info "验证安装..."

    local errors=0

    # 检查 Kitty 配置
    if [ ! -f "$HOME/.config/kitty/kitty.conf" ]; then
        error "Kitty 配置未找到"
        ((errors++))
    else
        # 检查 remote control 是否启用
        if grep -q "allow_remote_control.*yes" "$HOME/.config/kitty/kitty.conf"; then
            success "Kitty Remote Control 已启用"
        else
            warning "Kitty Remote Control 未启用"
        fi
    fi

    # 检查脚本
    if [ ! -d "$HOME/.config/kitty/scripts" ]; then
        error "Kitty 脚本目录未找到"
        ((errors++))
    else
        success "Kitty 脚本已安装"
    fi

    # 检查 hooks
    local hook_ok=true
    for h in on-stop.sh on-notify.sh on-tool-use.sh tab-color-common.sh; do
        if [ ! -f "$HOME/.claude/hooks/$h" ]; then
            error "Claude Hook $h 未找到"
            hook_ok=false
            ((errors++))
        fi
    done
    [ "$hook_ok" = true ] && success "Claude Hooks 已安装"

    # 检查 on-bell.sh 公共模块
    if [ ! -f "$HOME/.config/kitty/scripts/tab-color-common.sh" ]; then
        error "tab-color-common.sh 未安装到 scripts 目录"
        ((errors++))
    fi

    # 测试 Kitty Remote Control
    local kitty_sock="${KITTY_LISTEN_ON:-unix:@mykitty}"
    if timeout 2 kitty @ --to "$kitty_sock" ls &>/dev/null; then
        success "Kitty Remote Control 可用"
    else
        warning "Kitty Remote Control 测试失败（可能需要重启 Kitty）"
    fi

    if [ $errors -gt 0 ]; then
        error "安装验证失败 ($errors 个错误)"
        return 1
    else
        success "安装验证通过"
        return 0
    fi
}

# 打印使用说明
print_usage() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Kitty 优化安装完成"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📌 下一步操作："
    echo ""
    echo "  1. 重启 Kitty 终端"
    echo "     （让新配置生效）"
    echo ""
    echo "  2. 重新加载 Shell 配置"
    if [ -n "${BASH_VERSION:-}" ]; then
        echo "     source ~/.bashrc"
    elif [ -n "${ZSH_VERSION:-}" ]; then
        echo "     source ~/.zshrc"
    fi
    echo ""
    echo "📦 可用功能："
    echo ""
    echo "  Tab 管理命令："
    echo "    tab-rename (tr)   - 完整重命名（含 git 分支）"
    echo "    tab-quick (tq)    - 快速重命名"
    echo "    tab-project (tp)  - 自动项目名 + 分支"
    echo "    tab-alert (ta)    - 标记为红色（需注意）"
    echo "    tab-warning       - 标记为黄色"
    echo "    tab-done          - 标记为绿色（完成）"
    echo "    tab-reset (tc)    - 重置颜色"
    echo ""
    echo "  Claude Code 集成："
    echo "    🔵 Claude 正在工作 → tab 变蓝"
    echo "    🔴 Claude 完成响应 → tab 变红"
    echo "    🟡 Claude 等待确认 → tab 变黄"
    echo "    ✅ 切回 tab 后自动恢复颜色"
    echo ""
    echo "  调试："
    echo "    export CLAUDE_HOOK_DEBUG=1  # 启用调试日志"
    echo "    tail -f /tmp/claude-hook.log  # 查看日志"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# 主流程
main() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Kitty 优化安装脚本"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    check_dependencies
    echo ""

    install_kitty_config
    install_kitty_scripts
    install_shell_functions
    echo ""

    install_claude_hooks
    configure_claude_hooks
    echo ""

    if verify_installation; then
        echo ""
        print_usage
        exit 0
    else
        echo ""
        error "安装未完全成功，请检查上述错误"
        exit 1
    fi
}

# 运行
main
