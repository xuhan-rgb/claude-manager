"""Tests for feishu-bridge terminal registry helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "feishu-bridge"
sys.path.insert(0, str(ROOT))

import terminal_registry as registry  # noqa: E402


def test_load_registry_normalizes_legacy_window_id_keys(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({
        "1": {
            "window_id": "1",
            "kitty_socket": "unix:@mykitty-111",
            "tab_title": "demo",
            "status": "working",
        }
    }), encoding="utf-8")
    monkeypatch.setattr(registry, "REGISTRY_FILE", str(path))

    data = registry.load_registry()

    assert list(data) == ["1@mykitty-111"]
    assert data["1@mykitty-111"]["terminal_id"] == "1@mykitty-111"
    assert data["1@mykitty-111"]["socket_label"] == "mykitty-111"


def test_resolve_terminal_selector_requires_full_id_when_ambiguous():
    registry_data = {
        "1@mykitty-a": {
            "terminal_id": "1@mykitty-a",
            "window_id": "1",
            "kitty_socket": "unix:@mykitty-a",
        },
        "1@mykitty-b": {
            "terminal_id": "1@mykitty-b",
            "window_id": "1",
            "kitty_socket": "unix:@mykitty-b",
        },
    }

    resolved, ambiguous = registry.resolve_terminal_selector("1", registry=registry_data)

    assert resolved is None
    assert [item["terminal_id"] for item in ambiguous] == ["1@mykitty-a", "1@mykitty-b"]
