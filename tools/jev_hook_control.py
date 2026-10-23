"""Enable or disable the Codex UserPromptSubmit Jev hook safely."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import stat
import tempfile

import jev_settings
import jev_state


def hooks_path() -> Path:
    configured = os.environ.get("JEV_HOOKS_FILE")
    if configured:
        return Path(configured)
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    return codex_home / "hooks.json"


def hook_command() -> str:
    install = Path(os.environ.get("JEV_INSTALL_DIR",
                                  str(Path.home() / ".local/share/jev-router")))
    return f"{install / 'venv/bin/python'} {install / 'jev_prompt_hook.py'}"


def hook_definition() -> dict:
    return {"type": "command", "command": hook_command(), "timeout": 25,
            "statusMessage": "Jev 正在判断输入路由", "additionalContextLimit": 1500}


def is_jev_hook(value) -> bool:
    return isinstance(value, dict) and "jev_prompt_hook.py" in value.get("command", "")


def remove_jev_hooks(config: dict) -> tuple[dict, bool]:
    updated = copy.deepcopy(config)
    events = updated.setdefault("hooks", {})
    changed = False
    for event, groups in list(events.items()):
        if not isinstance(groups, list):
            continue
        new_groups = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                new_groups.append(group)
                continue
            remaining = [hook for hook in group["hooks"] if not is_jev_hook(hook)]
            changed = changed or len(remaining) != len(group["hooks"])
            if remaining:
                item = copy.deepcopy(group)
                item["hooks"] = remaining
                new_groups.append(item)
        events[event] = new_groups
    return updated, changed


def add_jev_hook(config: dict) -> tuple[dict, bool]:
    updated, _ = remove_jev_hooks(config)
    hooks = updated.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
    hooks.append({"hooks": [hook_definition()]})
    return updated, True


def read_config(path: Path) -> dict:
    if not path.exists():
        return {"hooks": {}}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("hooks.json must contain an object")
    return value


def write_config(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".jev-hooks-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def installed(path: Path) -> bool:
    config = read_config(path)
    return any(is_jev_hook(hook)
               for group in config.get("hooks", {}).get("UserPromptSubmit", [])
               if isinstance(group, dict)
               for hook in group.get("hooks", []) if isinstance(group.get("hooks"), list))


def apply(action: str) -> dict:
    path = hooks_path()
    with jev_state.locked(path):
        config = read_config(path)
        if action == "status":
            data = jev_settings.read_settings()
            data["installed"] = installed(path)
            return data
        if action == "off":
            updated, _ = remove_jev_hooks(config)
            write_config(path, updated)
            data = jev_settings.change("hook", False)
        else:
            updated, _ = add_jev_hook(config)
            write_config(path, updated)
            data = jev_settings.change("hook", True)
    return data | {"installed": action == "on"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="启用或停用 Codex 的 Jev UserPromptSubmit hook")
    parser.add_argument("action", nargs="?", choices=("status", "on", "off"), default="status")
    args = parser.parse_args(argv)
    try:
        data = apply(args.action)
        print(f"Jev hook: {'on' if data.get('installed') else 'off'}")
        print(f"Jev 总开关: {'on' if data['enabled'] else 'off'}")
        print(f"配置: {hooks_path()}")
        if args.action != "status":
            print("配置已原子写入；当前 Codex 是否立即重载取决于宿主，重新启动会话可确保生效。")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Jev hook 配置失败 ({type(error).__name__})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
