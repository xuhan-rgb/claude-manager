#!/usr/bin/env bash
# Install only codex-yolo; no Kitty or Claude configuration changes.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
command -v python3 >/dev/null || { echo 'python3 is required' >&2; exit 1; }
command -v codex >/dev/null || { echo 'Install Codex CLI and configure login first.' >&2; exit 1; }
codex_help=$(env -u KITTY_WINDOW_ID -u KITTY_LISTEN_ON codex --help)
if [[ $codex_help != *--remote* ]]; then
    echo 'Update Codex CLI: this installation requires --remote support.' >&2
    exit 1
fi
env -u KITTY_WINDOW_ID -u KITTY_LISTEN_ON codex app-server daemon start --help >/dev/null

mkdir -p "$HOME/.local/bin" "${CODEX_HOME:-$HOME/.codex}"
target="$HOME/.local/bin/codex-yolo"
if [[ -e $target ]] && ! cmp -s "$script_dir/bin/codex-yolo" "$target"; then
    cp -p "$target" "$target.bak.$(date +%Y%m%d_%H%M%S)"
fi
install -m 755 "$script_dir/bin/codex-yolo" "$target"
profile="${CODEX_HOME:-$HOME/.codex}/yolo.config.toml"
if [[ ! -e $profile ]]; then
    install -m 600 "$script_dir/config/codex/yolo.config.toml" "$profile"
fi

# Migrate permissions and place the managed block after old aliases/functions.
python3 - <<'PY'
import os
import re
import shutil
from pathlib import Path

home = Path.home()
codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))


def write_config(path, old, new):
    if new != old:
        backup = path.with_name(path.name + ".before-codex-yolo")
        if path.exists() and not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(new)
        path.chmod(0o600)


# Edit only root settings; keep models, providers, tools and table contents intact.
config = codex_home / "config.toml"
old = config.read_text() if config.exists() else ""
table = re.search(r"(?m)^\s*\[", old)
head, tail = (old[:table.start()], old[table.start():]) if table else (old, "")
for key, value in [("approval_policy", "never"), ("sandbox_mode", "danger-full-access")]:
    pattern = rf'(?m)^(\s*{key}\s*=\s*)(?:"[^"\n]*"|\x27[^\x27\n]*\x27)'
    head, count = re.subn(pattern, lambda match: match[1] + f'"{value}"', head)
    if not count:
        head = f'{key} = "{value}"\n' + head
write_config(config, old, head + tail)

# Profiles count as explicit overrides during remote resume, including permission tables.
profile = codex_home / "yolo.config.toml"
old = profile.read_text()
permission_keys = (
    "approval_policy|approvals_reviewer|sandbox_mode|default_permissions|"
    "permissions|network|sandbox_workspace_write"
)
root_key = rf'(?:"(?:{permission_keys})"|\x27(?:{permission_keys})\x27|(?:{permission_keys}))'
new = re.sub(
    rf'(?ms)^\s*\[\[?\s*{root_key}(?=[.\s\]]).*?(?=^\s*\[|\Z)', "", old,
)
table = re.search(r"(?m)^\s*\[", new)
head, tail = (new[:table.start()], new[table.start():]) if table else (new, "")
head = re.sub(
    rf'(?ms)^[ \t]*{root_key}(?=[.\s=])[^\n]*=.*?(?=^[ \t]*[\w"\x27][^\n]*=|\Z)',
    "", head,
)
write_config(profile, old, head + tail)

block = '''# >>> kitty-enhance codex-yolo >>>
export PATH="$HOME/.local/bin:$PATH"
unalias codex-yolo 2>/dev/null || true
unset -f codex-yolo 2>/dev/null || true
# <<< kitty-enhance codex-yolo <<<
'''
rc_paths = [home / ".bashrc"]
if (home / ".zshrc").exists() or Path(os.environ.get("SHELL", "")).name == "zsh":
    rc_paths.append(home / ".zshrc")
for rc in rc_paths:
    old = rc.read_text() if rc.exists() else ""
    clean = re.sub(
        r"(?m)^# >>> kitty-enhance codex-yolo >>>\n.*?^# <<< kitty-enhance codex-yolo <<<\n?",
        "", old, flags=re.S,
    )
    new = clean.rstrip("\n") + "\n\n" + block
    if new != old:
        if rc.exists():
            backup = rc.with_name(rc.name + ".before-codex-yolo")
            if not backup.exists():
                shutil.copy2(rc, backup)
        rc.write_text(new)
print("Installed ~/.local/bin/codex-yolo; YOLO defaults set in base config for remote resume.")
print("Other profile settings preserved; ordinary Codex also inherits YOLO defaults.")
print("Open a new terminal, or source ~/.bashrc (zsh: source ~/.zshrc).")
PY
