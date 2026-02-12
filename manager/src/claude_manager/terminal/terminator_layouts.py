"""Terminator layout helpers."""

import os
import tempfile
import uuid


def build_layout_config(columns: float = 0.68, width: int = 1200, height: int = 800) -> tuple[str, str]:
    """Create a temporary Terminator config with a CM layout.

    Returns:
        (layout_id, config_path)
    """
    layout_id = f"cm-{uuid.uuid4().hex[:8]}"
    config_path = os.path.join(tempfile.gettempdir(), f"cm-terminator-{layout_id}.conf")
    # Inline config for Terminator layout. Use a horizontal split (left/right).
    left_cmd = f"\"bash -lc 'tty > /tmp/cm-tty-{layout_id}-main 2>/dev/null; exec bash'\""
    right_cmd = f"\"bash -lc 'tty > /tmp/cm-tty-{layout_id}-cmd 2>/dev/null; exec bash'\""

    layout = f"""
[global_config]
  enabled_plugins = TerminatorConfig

[keybindings]

[profiles]
  [[default]]

[layouts]
  [[{layout_id}]]
    [[[root]]]
      type = Window
      parent = ""
      position = 0:0
      size = {width}, {height}
    [[[col1]]]
      type = HPaned
      parent = root
      position = {columns}
    [[[left]]]
      type = Terminal
      parent = col1
      profile = default
      command = {left_cmd}
    [[[right]]]
      type = Terminal
      parent = col1
      profile = default
      command = {right_cmd}
"""
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(layout.strip() + "\n")
    return layout_id, config_path
