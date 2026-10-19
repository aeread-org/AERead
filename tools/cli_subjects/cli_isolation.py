"""Keep the owner's CLI customizations out of a CLI subject's context (CLI-D-01, CLI-D-02).

Claude Code already starts with ``--safe-mode``: no CLAUDE.md, memory, skills, plugins, hooks, MCP servers or output
style. What it still reads from its surroundings is its working directory, which named the repository and the case.
Each call therefore runs in a fresh empty directory: ``isolated_command_runner``, given to ``ClaudeCodePrintClient``
as its command runner. The account's email address comes with the subscription login and stays (a stated limit).

Codex 0.162.1 lists skills from ``~/.codex/skills`` and ``~/.agents/skills`` even with ``--ignore-user-config`` and every
skill-related feature off. Each Codex call therefore runs with ``HOME`` and ``CODEX_HOME`` set to a fresh directory
that holds only a link to the login file (``install_codex_isolation``). Codex's four built-in skills and its built-in
tool definitions remain; no switch removes them, and the client refuses any call that uses a tool.

``isolation_violations`` turns a context probe (the skills, tools, MCP servers and working directory a CLI reports
under the run's exact flags) into the reasons a freeze must refuse. The v2 driver probes each CLI at the freeze and
before each arm, and seals the probe in the campaign plan.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

import codex_exec_client

REAL_HOME = Path.home()
CODEX_AUTH = REAL_HOME / ".codex" / "auth.json"
BUILTIN_CODEX_SKILLS = frozenset({"imagegen", "openai-docs", "skill-creator", "skill-installer"})
CLAUDE_TOOLS = ("StructuredOutput",)
#: Not ``tempfile.gettempdir()``: TMPDIR can name the repository (a sandboxed session sets it under a path that
#: does), and the subject sees its working directory. Directory names carry no project word either.
NEUTRAL_TMP = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path(tempfile.gettempdir())
DECLARATION = {
    "claude_code": "--safe-mode; each call in a fresh empty directory outside the repository and the home directory",
    "codex_cli": ("--ignore-user-config and the v1 disabled features; each call with HOME and CODEX_HOME set to a fresh "
                  "directory holding only a link to the login file, and a fresh empty working directory"),
    "probe": "skills, tools, MCP servers and working directory sealed at the freeze; a violation refuses the freeze",
}


async def _communicate(arguments: tuple[str, ...], standard_input: bytes, **options: Any) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *arguments, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **options,
    )
    try:
        stdout, stderr = await process.communicate(standard_input)
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    return process.returncode, stdout, stderr


async def isolated_command_runner(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    """Claude Code's command runner: the call runs in a fresh empty directory that is removed afterwards."""

    directory = Path(tempfile.mkdtemp(prefix="w_", dir=NEUTRAL_TMP))
    try:
        return await _communicate(arguments, standard_input, cwd=str(directory))
    finally:
        shutil.rmtree(directory, ignore_errors=True)


async def codex_run_isolated(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    """Codex's subprocess call with a fresh HOME and CODEX_HOME that hold only a link to the login file."""

    if not CODEX_AUTH.is_file():
        raise codex_exec_client.ProviderFailure(
            "provider_contract", f"Codex login file is missing: {CODEX_AUTH}", retryable=False
        )
    home = Path(tempfile.mkdtemp(prefix="h_", dir=NEUTRAL_TMP))
    try:
        codex_home = home / ".codex"
        codex_home.mkdir()
        os.symlink(CODEX_AUTH, codex_home / "auth.json")
        environment = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex_home))
        return await _communicate(arguments, standard_input, env=environment, cwd=str(home))
    finally:
        shutil.rmtree(home, ignore_errors=True)


def install_codex_isolation() -> Mapping[str, str]:
    """Route every Codex call through ``codex_run_isolated``. The client looks ``_run`` up at call time."""

    codex_exec_client._run = codex_run_isolated
    assert codex_exec_client._run is codex_run_isolated
    return DECLARATION


def isolation_violations(probe: Mapping[str, Any]) -> list[str]:
    """Why a context probe shows a subject that is not isolated; empty when it is."""

    cli = probe.get("cli")
    found: list[str] = []
    directory = str(probe.get("working_directory") or "")
    for forbidden in (str(REAL_HOME).lower(), "aeread"):
        if forbidden and forbidden in directory.lower():
            found.append(f"{cli}: working directory {directory!r} names {forbidden!r}")
    if cli == "claude_code":
        if tuple(probe.get("tools") or ()) != CLAUDE_TOOLS:
            found.append(f"claude_code: tools {probe.get('tools')!r}, expected {list(CLAUDE_TOOLS)!r}")
        if probe.get("mcp_servers"):
            found.append(f"claude_code: MCP servers {probe.get('mcp_servers')!r}")
        if probe.get("output_style") not in (None, "default"):
            found.append(f"claude_code: output style {probe.get('output_style')!r}")
        if probe.get("skills_in_context"):
            found.append(f"claude_code: skills in context {probe.get('skills_in_context')!r}")
    elif cli == "codex_cli":
        extra = sorted(set(probe.get("skills") or ()) - BUILTIN_CODEX_SKILLS)
        if extra:
            found.append(f"codex_cli: skills beyond the built-in ones {extra!r}")
    else:
        found.append(f"unknown CLI {cli!r}")
    return found
