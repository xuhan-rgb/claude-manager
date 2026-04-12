#!/bin/bash
# Claude Manager 安装脚本
# 使用 uv 创建 Python 3.10 虚拟环境并安装

set -euo pipefail

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✅${NC} $*"; }
warning() { echo -e "${YELLOW}⚠️${NC}  $*"; }
error() { echo -e "${RED}❌${NC} $*"; }

VENV_DIR="${CLAUDE_MANAGER_VENV:-$HOME/.local/share/claude-manager-venv}"
BIN_DIR="$HOME/.local/bin"
PYTHON_VERSION="3.10"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

print_help() {
    echo "用法: ./install.sh [选项]"
    echo ""
    echo "选项："
    echo "  --venv PATH    自定义虚拟环境路径 (默认: $VENV_DIR)"
    echo "  --uninstall    卸载 claude-manager"
    echo "  -h, --help     显示帮助"
}

check_dependencies() {
    info "检查依赖..."

    if ! command -v uv &>/dev/null; then
        error "需要 uv 包管理器"
        echo ""
        echo "安装方法："
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    success "uv $(uv --version | awk '{print $2}')"

    # 确保 uv 有 Python 3.10+
    if ! uv python list 2>/dev/null | grep -q "cpython-3\.1[0-9]"; then
        info "安装 Python $PYTHON_VERSION..."
        uv python install "$PYTHON_VERSION"
    fi
    success "Python $PYTHON_VERSION 可用"
}

create_venv() {
    if [ -d "$VENV_DIR" ]; then
        info "虚拟环境已存在: $VENV_DIR"
        return
    fi

    info "创建虚拟环境: $VENV_DIR"
    uv venv "$VENV_DIR" --python "$PYTHON_VERSION"
    success "虚拟环境已创建"
}

install_package() {
    info "安装 claude-manager (editable)..."
    uv pip install -e "$SCRIPT_DIR" --python "$VENV_DIR/bin/python"
    success "claude-manager 已安装"
}

create_symlink() {
    mkdir -p "$BIN_DIR"

    local src="$VENV_DIR/bin/claude-manager"
    local dst="$BIN_DIR/claude-manager"

    if [ ! -f "$src" ]; then
        error "入口脚本不存在: $src"
        exit 1
    fi

    if [ -L "$dst" ] || [ -f "$dst" ]; then
        rm -f "$dst"
    fi
    ln -sf "$src" "$dst"
    success "已链接 claude-manager → $dst"

    # 检查 PATH
    if ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
        warning "$BIN_DIR 不在 PATH 中"
        echo "  请添加到 ~/.bashrc 或 ~/.zshrc:"
        echo "    export PATH=\"$BIN_DIR:\$PATH\""
    fi
}

verify_installation() {
    info "验证安装..."

    local errors=0

    # 检查命令可用
    if command -v claude-manager &>/dev/null; then
        success "claude-manager 命令可用"
    else
        error "claude-manager 命令不在 PATH 中"
        ((errors++))
    fi

    # 检查 tabs 子命令
    if "$VENV_DIR/bin/claude-manager" tabs list --help &>/dev/null; then
        success "tabs list 子命令正常"
    else
        error "tabs list 子命令失败"
        ((errors++))
    fi

    if "$VENV_DIR/bin/claude-manager" tabs focus --help &>/dev/null; then
        success "tabs focus 子命令正常"
    else
        error "tabs focus 子命令失败"
        ((errors++))
    fi

    if [ $errors -gt 0 ]; then
        error "验证失败 ($errors 个错误)"
        return 1
    fi
    success "安装验证通过"
    return 0
}

do_uninstall() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  卸载 Claude Manager"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if [ -L "$BIN_DIR/claude-manager" ]; then
        rm "$BIN_DIR/claude-manager"
        success "已删除 $BIN_DIR/claude-manager"
    else
        info "未找到 $BIN_DIR/claude-manager"
    fi

    if [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR"
        success "已删除虚拟环境: $VENV_DIR"
    else
        info "未找到虚拟环境: $VENV_DIR"
    fi

    success "卸载完成"
}

print_usage() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Claude Manager 安装完成"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "可用命令："
    echo ""
    echo "  claude-manager tabs list            列出所有 Claude/Codex 终端"
    echo "  claude-manager tabs list --active   只看 working/waiting"
    echo "  claude-manager tabs list --json     JSON 格式输出"
    echo "  claude-manager tabs focus <id>      跳转到指定终端"
    echo ""
    echo "  claude-manager                      启动 TUI 面板（需 kitty）"
    echo "  claude-manager --check              检查环境"
    echo ""
    echo "安装信息："
    echo "  虚拟环境: $VENV_DIR"
    echo "  命令路径: $BIN_DIR/claude-manager"
    echo "  代码路径: $SCRIPT_DIR (editable，修改即生效)"
    echo ""
    echo "卸载: ./install.sh --uninstall"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

main() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --venv)      VENV_DIR="$2"; shift 2 ;;
            --uninstall) do_uninstall; exit 0 ;;
            -h|--help)   print_help; exit 0 ;;
            *)           error "未知参数: $1"; print_help; exit 1 ;;
        esac
    done

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Claude Manager 安装脚本"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    check_dependencies
    echo ""
    create_venv
    install_package
    echo ""
    create_symlink
    echo ""

    if verify_installation; then
        print_usage
        exit 0
    else
        echo ""
        error "安装未完全成功，请检查上述错误"
        exit 1
    fi
}

main "$@"
