"""Kitty window focus helper."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

FOCUS_TIMEOUT = 3.0


def focus_window(socket: str, window_id: str) -> tuple[bool, str]:
    """Focus a kitty window by id via `kitten @ focus-window`.

    Args:
        socket: kitty socket like "unix:@mykitty-12345"
        window_id: numeric kitty window id as string

    Returns:
        (success, error_message). error_message is empty on success.
    """
    cmd = [
        "kitten", "@", "--to", socket,
        "focus-window", "--match", f"id:{window_id}",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FOCUS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "kitten @ focus-window timed out"
    except FileNotFoundError:
        return False, "kitten command not found"

    if result.returncode != 0:
        err = result.stderr.strip()
        if not err:
            err = f"kitten exited with code {result.returncode}"
        return False, err
    return True, ""
