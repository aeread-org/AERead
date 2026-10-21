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


def test_the_codex_working_directory_the_model_sees_is_replaced(tmp_path, monkeypatch) -> None:
    """CLI-D-03: the hashed client names ``-C <tmp>/aeread_codex_call_<random>/cwd``; the isolated call replaces it."""
    auth = tmp_path / "auth.json"
    auth.write_text("{}")
    monkeypatch.setattr(iso, "CODEX_AUTH", auth)
    named = tmp_path / "aeread_codex_call_x" / "cwd"
    named.mkdir(parents=True)
    show = "import json, sys, os; print(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}))"
    code, out, _ = asyncio.run(iso.codex_run_isolated((sys.executable, "-c", show, "exec", "-C", str(named), "-"), b""))
    assert code == 0
    seen = json.loads(out)
    given = seen["argv"][seen["argv"].index("-C") + 1]
    assert given == seen["cwd"]
    assert "aeread" not in given.lower() and str(iso.REAL_HOME) not in given
    assert not Path(given).exists()


def test_neutral_workdir_leaves_arguments_without_a_directory_alone() -> None:
    assert iso._neutral_workdir(("codex", "--version"), Path("/x")) == ("codex", "--version")
    assert iso._neutral_workdir(("codex", "--cd", "/a", "-"), Path("/x")) == ("codex", "--cd", "/x", "-")


@pytest.mark.parametrize(
    ("probe", "fragment"),
    [
        ({"cli": "codex_cli", "skills": [], "working_directory": "/private/tmp/w_a",
          "other_context_blocks": ["<environment_context><cwd>/var/T/aeread_codex_call_1/cwd</cwd>"]}, "context the subject reports"),
        ({"cli": "codex_cli", "skills": [], "working_directory": "/private/tmp/w_a", "isolated_run": False}, "without the isolated"),
        ({"cli": "claude_code", "tools": ["StructuredOutput"], "mcp_servers": [], "working_directory": "/private/tmp/w_a",
          "context_tokens": 67906}, "probe context 67906"),
        ({"cli": "claude_code", "tools": ["StructuredOutput"], "mcp_servers": [], "working_directory": "/private/tmp/w_a",
          "skills_in_context": ["superpowers"]}, "skills in context"),
    ],
)
def test_context_blocks_and_unisolated_probes_refuse_the_freeze(probe, fragment) -> None:
    found = iso.isolation_violations(probe)
    assert len(found) == 1 and fragment in found[0]


def test_probe_request_is_hashed_and_asks_for_the_four_items() -> None:
    request = iso.probe_request(provider="codex_cli", model="m", reasoning_effort="low", provider_metadata={"a": "b"})
    assert request.request_sha256 and request.output_schema["required"] == [
        "skills", "tools", "working_directory", "other_context_blocks"]
    assert request.revision == request.model == "m"


def test_the_input_is_on_stdin_before_the_cli_starts_even_when_the_loop_is_busy() -> None:
    """CLI-T-01: a CLI that gives up on stdin after a short wait still gets its input while the loop is blocked."""
    impatient = ("import select, sys; r, _, _ = select.select([sys.stdin], [], [], 0.5); "
                 "data = sys.stdin.buffer.read() if r else b''; sys.stdout.write(str(len(data))); sys.exit(0 if data else 1)")

    async def main():
        task = asyncio.ensure_future(iso.isolated_command_runner((sys.executable, "-c", impatient), b"x" * 50_000))
        await asyncio.sleep(0)
        import time
        time.sleep(1.5)  # the driver's synchronous sealing and replay, holding the loop
        return await task

    code, out, _ = asyncio.run(main())
    assert code == 0 and out == b"50000"
