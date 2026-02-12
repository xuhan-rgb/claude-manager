"""命令行入口 - 终端分屏 + tmux session 管理"""

import argparse
import sys

from .terminal import check_environment as check_terminal_environment
from .tmux_control import check_tmux


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description='Claude Manager - 终端分屏 + tmux session 管理',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
架构:
  ┌─────────────┬─────────────────────┬─────────────────────┐
  │  TUI 面板   │  tmux 工作区         │  tmux 工作区         │
  │  (Window 1) │  (Window 2 tmux)    │  (Window 3 tmux)    │
  │             │                     │                     │
  │  任务列表   │  每个任务 = tmux     │  多客户端同步切换    │
  │  进程监控   │  session             │                     │
  └─────────────┴─────────────────────┴─────────────────────┘

支持的终端:
  - Kitty (推荐，需启用 allow_remote_control)
  - tmux (纯 tmux 模式，在任何终端内运行)

快捷键:
  n     新建任务（创建 tmux session）
  m     编辑任务描述
  d     删除任务（关闭 tmux session）
  1-5   快速切换任务
  q     退出

使用方式:
  claude-manager           # 启动（自动检测终端并创建分屏）
  claude-manager --check   # 检查环境
  claude-manager --debug   # 启用调试面板
        """
    )

    parser.add_argument('--check', '-c', action='store_true', help='检查环境')
    parser.add_argument('--version', '-v', action='store_true', help='显示版本')
    parser.add_argument('--debug', action='store_true',
                        help='启用调试面板（显示状态判断依据）')

    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(f"Claude Manager v{__version__}")
        return 0

    if args.check:
        return check_environment()

    # 检查是否在终端中
    if not sys.stdout.isatty():
        print("错误: 需要在终端中运行", file=sys.stderr)
        return 1

    # 启动分屏布局
    from .launcher import launch_tui_with_split
    launch_tui_with_split(debug=args.debug)

    return 0


def check_environment():
    """检查环境"""
    print("检查环境...\n")
    all_ok = True

    # 检查终端（自动检测类型）
    ok, msg, adapter = check_terminal_environment()
    if ok:
        print(f"✅ 终端: {msg}")
    else:
        print(f"❌ 终端: {msg}")
        all_ok = False

    # 检查 tmux
    ok, msg = check_tmux()
    if ok:
        print(f"✅ tmux: {msg}")
    else:
        print(f"❌ tmux: {msg}")
        all_ok = False

    # 检查 Textual
    try:
        import textual
        print(f"✅ Textual: {textual.__version__}")
    except ImportError:
        print("❌ Textual: 未安装")
        all_ok = False

    print()
    if all_ok:
        print("✓ 所有检查通过")
    else:
        print("✗ 部分检查失败，请查看上方信息")

    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
