import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "ai-run"


def write_skill(
    root: Path,
    name: str,
    *,
    declared_name: str | None = None,
    model_invocable: bool = True,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    disabled = "" if model_invocable else "disable-model-invocation: true\n"
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {declared_name or name}\ndescription: Test skill.\n{disabled}---\n",
        encoding="utf-8",
    )
    return path


def write_fake_client(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

payload = {"argv": sys.argv[1:], "disable_bundled": os.environ.get("CLAUDE_CODE_DISABLE_BUNDLED_SKILLS")}
mcp_arg = next((arg for arg in sys.argv if arg.startswith("--mcp-config=")), None)
if mcp_arg:
    mcp_path = Path(mcp_arg.split("=", 1)[1])
    payload["mcp"] = json.loads(mcp_path.read_text())
Path(os.environ["AI_RUN_CAPTURE"]).write_text(json.dumps(payload))
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def run_ai(script_args, tmp_path: Path, client: str):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    fake_client = tmp_path / f"fake-{client}"
    write_fake_client(fake_client)
    capture = tmp_path / "capture.json"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            f"AI_RUN_{client.upper()}_BIN": str(fake_client),
            "AI_RUN_CAPTURE": str(capture),
        }
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), client, *script_args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(capture.read_text()) if capture.exists() else None
    return result, payload, home


def test_claude_selects_custom_skills_and_mcp_without_changing_global_config(tmp_path):
    home = tmp_path / "home"
    write_skill(home / ".claude" / "skills", "alpha")
    write_skill(home / ".claude" / "skills", "beta")
    mcp_config = home / ".claude" / "mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "docs": {"type": "http", "url": "https://example.test/mcp"},
                    "other": {"type": "http", "url": "https://other.test/mcp"},
                }
            }
        ),
        encoding="utf-8",
    )
    before = mcp_config.read_text()

    result, payload, _ = run_ai(
        [
            "--skills",
            "alpha",
            "--bundled-skills",
            "hide",
            "--mcp",
            "docs",
            "--yolo",
        ],
        tmp_path,
        "claude",
    )

    assert result.returncode == 0, result.stderr
    assert "--dangerously-skip-permissions" in payload["argv"]
    assert "--strict-mcp-config" in payload["argv"]
    assert any(arg.startswith("--mcp-config=") for arg in payload["argv"])
    settings = json.loads(payload["argv"][payload["argv"].index("--settings") + 1])
    assert settings["skillOverrides"] == {"alpha": "on", "beta": "off"}
    assert set(payload["mcp"]["mcpServers"]) == {"docs"}
    assert payload["disable_bundled"] == "1"
    assert mcp_config.read_text() == before


def test_claude_none_disables_all_skills_and_mcp(tmp_path):
    result, payload, _ = run_ai(
        ["--skills", "none", "--mcp", "none"], tmp_path, "claude"
    )

    assert result.returncode == 0, result.stderr
    assert "--disable-slash-commands" in payload["argv"]
    assert payload["mcp"] == {"mcpServers": {}}


def test_skill_directory_name_can_select_a_different_declared_name(tmp_path):
    home = tmp_path / "home"
    write_skill(
        home / ".claude" / "skills",
        "knowledge-query",
        declared_name="knowledge",
    )

    result, payload, _ = run_ai(
        ["--skills", "knowledge-query", "--mcp", "default"], tmp_path, "claude"
    )

    assert result.returncode == 0, result.stderr
    settings = json.loads(payload["argv"][payload["argv"].index("--settings") + 1])
    assert settings["skillOverrides"] == {"knowledge": "on"}


def test_codex_selects_one_skill_and_one_mcp(tmp_path):
    home = tmp_path / "home"
    alpha = write_skill(home / ".agents" / "skills", "alpha")
    beta = write_skill(home / ".agents" / "skills", "beta")
    beta_legacy = write_skill(home / ".claude" / "skills", "beta")
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True)
    config = codex_dir / "config.toml"
    config.write_text(
        "\n".join(
            [
                "[mcp_servers.docs]",
                'url = "https://example.test/mcp"',
                "enabled = false",
                "",
                "[mcp_servers.other]",
                'url = "https://other.test/mcp"',
                "enabled = true",
                "",
                "[[skills.config]]",
                f'path = {json.dumps(str(alpha))}',
                "enabled = true",
                "",
                "[[skills.config]]",
                f'path = {json.dumps(str(beta))}',
                "enabled = false",
                "",
                "[[skills.config]]",
                f'path = {json.dumps(str(beta_legacy))}',
                "enabled = false",
            ]
        ),
        encoding="utf-8",
    )
    before = config.read_text()

    result, payload, _ = run_ai(
        ["--skills", "beta", "--mcp", "docs", "--yolo"], tmp_path, "codex"
    )

    assert result.returncode == 0, result.stderr
    argv = payload["argv"]
    skill_override = next(item for item in argv if item.startswith("skills.config=["))
    assert f'path={json.dumps(str(alpha))},enabled=false' in skill_override
    assert f'path={json.dumps(str(beta))},enabled=true' in skill_override
    assert skill_override.index(str(beta_legacy)) < skill_override.index(str(beta))
    assert "mcp_servers.docs.enabled=true" in argv
    assert "mcp_servers.other.enabled=false" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert config.read_text() == before
