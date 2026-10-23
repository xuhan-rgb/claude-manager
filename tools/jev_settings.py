"""Live Jev switches shared by hooks and verification tools."""

import argparse
import json
import os
from pathlib import Path

import jev_state

DEFAULTS = {"enabled": True, "entry": True, "print": True, "hook": True}
HELP = "命令：jev status | jev on | jev off | jev entry on/off | jev print on/off"


def settings_path():
    return Path(os.environ.get("JEV_SETTINGS_FILE", str(Path.home() / ".config/jev-router/settings.json")))


def read_settings():
    path = settings_path()
    result = dict(DEFAULTS)
    # Environment values are startup defaults; persisted live switches win.
    for key, variable in (("enabled", "JEV_ENABLED"), ("entry", "JEV_ENTRY"),
                          ("print", "JEV_PRINT_JUDGMENTS"), ("hook", "JEV_HOOK")):
        if variable in os.environ:
            result[key] = os.environ[variable] != "0"
    if path.exists():
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or any(type(v) is not bool for k, v in data.items() if k in DEFAULTS):
            raise ValueError("invalid Jev settings")
        result.update({k: data[k] for k in DEFAULTS if k in data})
    return result


def change(key, value):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with jev_state.locked(path):
        data = read_settings()
        data[key] = value
        jev_state.save(path, data)
    return data


def describe(data):
    lines = [f"{label}: {'on' if data[key] else 'off'}" for key, label in
             (("enabled", "Jev 总开关"), ("entry", "输入路由"),
              ("print", "判断打印"), ("hook", "Jev hook"))]
    lines += ["委派后审核判断: " + ("Jev 按证据判断" if data["enabled"] else "交由当前模型负责"),
              "配置: " + str(settings_path()), HELP,
              "每次调用读取；后续判断即时生效，已经开始的调用不取消。",
              "物理 hook 开关：jev-hook on/off（修改 hooks.json）。"]
    return "\n".join(lines)


def control(words):
    if not words or words == ["status"]:
        return describe(read_settings())
    if words in (["on"], ["off"]):
        return describe(change("enabled", words[0] == "on"))
    if len(words) == 2 and words[0] in ("entry", "print") and words[1] in ("on", "off"):
        return describe(change(words[0], words[1] == "on"))
    raise ValueError(HELP)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jev 热配置：总开关、入口路由、判断打印")
    parser.add_argument("command", nargs="?", default="status", choices=["status", "on", "off", "entry", "print"])
    parser.add_argument("value", nargs="?", choices=["on", "off"])
    args = parser.parse_args(argv)
    if (args.command in ("entry", "print")) != (args.value is not None):
        parser.error("用法：jev on|off|status 或 jev entry|print on|off")
    try:
        print(control([args.command] + ([args.value] if args.value else [])))
        return 0
    except (OSError, ValueError) as error:
        print(f"Jev 配置不可用 ({type(error).__name__})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
