"""CLI subjects run without the owner's customizations (CLI-D-01, CLI-D-02); offline, with stand-in commands."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "cli_subjects"))

import cli_isolation as iso  # noqa: E402
import codex_exec_client  # noqa: E402

SHOW = "import json, os; print(json.dumps({'cwd': os.getcwd(), 'home': os.environ.get('HOME'), " \
       "'codex_home': os.environ.get('CODEX_HOME'), 'auth_link': os.path.islink(os.path.join(os.environ.get('CODEX_HOME') or '/nonexistent', 'auth.json'))}))"


def _show(runner):
    code, out, _ = asyncio.run(runner((sys.executable, "-c", SHOW), b""))
    assert code == 0
    return json.loads(out)


def test_a_claude_call_runs_in_a_fresh_neutral_directory_that_is_removed() -> None:
    seen = _show(iso.isolated_command_runner)
    directory = Path(seen["cwd"])
    assert not directory.exists()
    assert str(Path.cwd()) != seen["cwd"]
    assert "aeread" not in seen["cwd"].lower() and str(iso.REAL_HOME) not in seen["cwd"]


def test_a_codex_call_gets_a_fresh_home_holding_only_the_login_link(tmp_path, monkeypatch) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    monkeypatch.setattr(iso, "CODEX_AUTH", auth)
    seen = _show(iso.codex_run_isolated)
    assert seen["home"] != str(iso.REAL_HOME)
    assert seen["codex_home"] == str(Path(seen["home"]) / ".codex")
    assert seen["auth_link"] is True
    assert not Path(seen["home"]).exists()
    assert auth.read_text() == "{}"  # removing the fresh home leaves the login file alone
    assert "aeread" not in seen["home"].lower()


def test_a_missing_login_file_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(iso, "CODEX_AUTH", tmp_path / "absent.json")
    with pytest.raises(codex_exec_client.ProviderFailure, match="login file is missing"):
        asyncio.run(iso.codex_run_isolated((sys.executable, "-c", "pass"), b""))


def test_install_routes_every_codex_call_through_the_isolated_run(monkeypatch) -> None:
    monkeypatch.setattr(codex_exec_client, "_run", codex_exec_client._run)
    declaration = iso.install_codex_isolation()
    assert codex_exec_client._run is iso.codex_run_isolated
    assert set(declaration) == {"claude_code", "codex_cli", "probe"}


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        ({"cli": "claude_code", "tools": ["StructuredOutput"], "mcp_servers": [], "output_style": "default",
          "working_directory": "/private/tmp/w_abc"}, []),
        ({"cli": "claude_code", "tools": ["StructuredOutput", "Bash"], "mcp_servers": [],
          "working_directory": "/private/tmp/w_abc"}, ["tools"]),
        ({"cli": "claude_code", "tools": ["StructuredOutput"], "mcp_servers": ["github"],
          "working_directory": "/private/tmp/w_abc"}, ["MCP servers"]),
        ({"cli": "claude_code", "tools": ["StructuredOutput"], "mcp_servers": [],
          "working_directory": "/Users/someone/AERead-worktrees/dc-agreement"}, ["names 'aeread'"]),
        ({"cli": "codex_cli", "skills": ["imagegen", "openai-docs", "skill-creator", "skill-installer"],
          "working_directory": "/private/tmp/h_x"}, []),
        ({"cli": "codex_cli", "skills": ["imagegen", "mercor-benchmark-assistant"],
          "working_directory": "/private/tmp/h_x"}, ["beyond the built-in"]),
    ],
)
def test_a_probe_that_shows_customizations_refuses_the_freeze(probe, expected) -> None:
    found = iso.isolation_violations(probe)
    assert len(found) == len(expected)
    for text, fragment in zip(found, expected):
        assert fragment in text
