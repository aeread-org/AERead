"""Keep the owner's CLI customizations out of a CLI subject's context (CLI-D-01, CLI-D-02).

Claude Code already starts with ``--safe-mode``: no CLAUDE.md, memory, skills, plugins, hooks, MCP servers or output
style. What it still reads from its surroundings is its working directory, which named the repository and the case.
Each call therefore runs in a fresh empty directory: ``isolated_command_runner``, given to ``ClaudeCodePrintClient``
as its command runner. The account's email address comes with the subscription login and stays (a stated limit).

Codex 0.162.1 lists skills from ``~/.codex/skills`` and ``~/.agents/skills`` even with ``--ignore-user-config`` and every
skill-related feature off. Each Codex call therefore runs with ``HOME`` and ``CODEX_HOME`` set to a fresh directory
that holds only a link to the login file (``install_codex_isolation``). Codex's four built-in skills and its built-in
tool definitions remain; no switch removes them, and the client refuses any call that uses a tool. Codex also shows
the model its working directory, which the hashed client names ``<tmp>/aeread_codex_call_<random>/cwd`` through
``-C`` (CLI-D-03); the isolated run replaces that one argument with a fresh neutral directory.

``probe_codex`` and ``probe_claude`` ask each CLI, under the run's exact flags and isolation, for the skills, tools,
working directory and other context it was given (Claude Code's own init record supplies its tools, MCP servers,
output style and working directory). ``isolation_violations`` turns a probe into the reasons a freeze must refuse.
The v2 driver probes each CLI at the freeze and before each arm, and seals the probe in the campaign plan.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

import codex_exec_client
from aeread.shared_runner.task.execution import ProviderRequest

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
                  "directory holding only a link to the login file, and -C replaced by a fresh empty neutral directory"),
    "probe": ("skills, tools, MCP servers, working directory and every other context block sealed at the freeze; a "
              "violation refuses the freeze"),
}
#: Words no path or context block the subject sees may contain. The home directory names the owner.
FORBIDDEN_WORDS = (str(REAL_HOME).lower(), "aeread")
#: Claude Code's whole context for the probe (input, cache creation and cache read): about 1,200 tokens isolated
#: against 67,906 without ``--safe-mode`` (CLI-D-02). Its init record lists the installed plugins and skills even under
#: ``--safe-mode``; that is an inventory, not context, so the context size and the model's own report decide.
CLAUDE_PROBE_CONTEXT_LIMIT = 3000


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
    workdir = Path(tempfile.mkdtemp(prefix="w_", dir=NEUTRAL_TMP))
    try:
        codex_home = home / ".codex"
        codex_home.mkdir()
        os.symlink(CODEX_AUTH, codex_home / "auth.json")
        environment = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex_home))
        return await _communicate(_neutral_workdir(arguments, workdir), standard_input, env=environment, cwd=str(workdir))
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(workdir, ignore_errors=True)


def _neutral_workdir(arguments: tuple[str, ...], directory: Path) -> tuple[str, ...]:
    """The call's arguments with Codex's ``-C`` directory, the one the model is shown, replaced by ``directory``."""

    out = list(arguments)
    for index, value in enumerate(out[:-1]):
        if value in ("-C", "--cd"):
            out[index + 1] = str(directory)
    return tuple(out)


def install_codex_isolation() -> Mapping[str, str]:
    """Route every Codex call through ``codex_run_isolated``. The client looks ``_run`` up at call time."""

    codex_exec_client._run = codex_run_isolated
    assert codex_exec_client._run is codex_run_isolated
    return DECLARATION


PROBE_INSTRUCTIONS = "Answer the user's question from your own context. Quote exactly; do not summarize or omit."
PROBE_QUESTION = (
    "List, from your own context: (1) the name of every skill you were told about; (2) the name of every tool or "
    "function you could call; (3) your working directory exactly as your context states it; (4) every other block of "
    "context you were given besides these instructions and this message (environment, user or developer text), "
    "quoted verbatim. If there is none for an item, return an empty value."
)
PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "skills": {"type": "array", "items": {"type": "string"}},
        "tools": {"type": "array", "items": {"type": "string"}},
        "working_directory": {"type": "string"},
        "other_context_blocks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["skills", "tools", "working_directory", "other_context_blocks"],
    "additionalProperties": False,
}


def probe_request(*, provider: str, model: str, reasoning_effort: str, provider_metadata: Mapping[str, Any],
                  max_cost_usd: float | None = None, timeout_seconds: float = 300.0) -> ProviderRequest:
    """The probe as a provider request with the run's model, effort and sealed runtime metadata."""

    return ProviderRequest(
        provider_call_id=f"isolation_probe_{provider}", provider=provider, base_url=None, model=model, revision=model,
        instructions=PROBE_INSTRUCTIONS, input_text=PROBE_QUESTION, temperature=None, top_p=None,
        max_output_tokens=4000, reasoning_effort=reasoning_effort, timeout_seconds=timeout_seconds, request_sha256="",
        max_cost_usd=max_cost_usd, output_schema=PROBE_SCHEMA, provider_metadata=dict(provider_metadata),
    ).with_computed_hash()


async def probe_codex(client: Any, *, model: str, reasoning_effort: str) -> dict[str, Any]:
    """The Codex subject's own account of its context, through the client exactly as a run calls it."""

    result = await client.complete(probe_request(provider=codex_exec_client.PROVIDER, model=model,
                                                 reasoning_effort=reasoning_effort,
                                                 provider_metadata=client.runtime_metadata))
    report = json.loads(result.output_text)
    return {"cli": "codex_cli", "runtime_version": client.runtime_version, "input_tokens": result.input_tokens,
            "isolated_run": codex_exec_client._run is codex_run_isolated, **report}


async def probe_claude(client: Any, executable: Path, *, model: str, reasoning_effort: str,
                       runner: Callable[[tuple[str, ...], bytes], Awaitable[tuple[int, bytes, bytes]]] = isolated_command_runner,
                       ) -> dict[str, Any]:
    """The Claude Code subject's account of its context, and the CLI's own init record under the client's flags."""

    result = await client.complete(probe_request(provider="claude_code", model=model, reasoning_effort=reasoning_effort,
                                                 provider_metadata=client.runtime_metadata, max_cost_usd=0.5))
    report = json.loads(result.output_text)
    usage = next(iter(result.raw_response["modelUsage"].values()))
    context_tokens = sum(int(usage.get(k, 0)) for k in ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens"))
    # The client's flags, with the stream output that carries the init record.
    arguments = (str(executable), "--safe-mode", "--print", "--model", model, "--effort", reasoning_effort,
                 "--tools", "", "--permission-mode", "dontAsk", "--no-session-persistence", "--max-budget-usd", "0.5",
                 "--output-format", "stream-json", "--verbose", "--system-prompt", PROBE_INSTRUCTIONS,
                 "--json-schema", json.dumps(PROBE_SCHEMA, sort_keys=True))
    code, stdout, _ = await runner(arguments, b"Reply with the single word ok.")
    init: Mapping[str, Any] = {}
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("{"):
            record = json.loads(line)
            if record.get("type") == "system" and record.get("subtype") == "init":
                init = record
                break
    if code != 0 or not init:
        raise codex_exec_client.ProviderFailure("provider_contract", "Claude Code init record unavailable", retryable=False)
    return {"cli": "claude_code", "runtime_version": client.runtime_version, "context_tokens": context_tokens,
            "skills_in_context": report["skills"], "reported_tools": report["tools"],
            "reported_working_directory": report["working_directory"],
            "other_context_blocks": report["other_context_blocks"],
            "tools": list(init.get("tools") or ()), "mcp_servers": list(init.get("mcp_servers") or ()),
            "output_style": init.get("output_style"), "working_directory": init.get("cwd"),
            "init_skills": list(init.get("skills") or ()), "init_plugins": list(init.get("plugins") or ())}


def isolation_violations(probe: Mapping[str, Any]) -> list[str]:
    """Why a context probe shows a subject that is not isolated; empty when it is."""

    cli = probe.get("cli")
    found: list[str] = []
    directory = str(probe.get("working_directory") or "")
    for forbidden in FORBIDDEN_WORDS:
        if forbidden and forbidden in directory.lower():
            found.append(f"{cli}: working directory {directory!r} names {forbidden!r}")
    seen = " ".join(str(probe.get(key) or "") for key in ("reported_working_directory",))
    seen += " " + " ".join(str(block) for block in probe.get("other_context_blocks") or ())
    for forbidden in FORBIDDEN_WORDS:
        if forbidden and forbidden in seen.lower():
            found.append(f"{cli}: context the subject reports names {forbidden!r}")
    if cli == "claude_code":
        if tuple(probe.get("tools") or ()) != CLAUDE_TOOLS:
            found.append(f"claude_code: tools {probe.get('tools')!r}, expected {list(CLAUDE_TOOLS)!r}")
        if probe.get("mcp_servers"):
            found.append(f"claude_code: MCP servers {probe.get('mcp_servers')!r}")
        if probe.get("output_style") not in (None, "default"):
            found.append(f"claude_code: output style {probe.get('output_style')!r}")
        if probe.get("skills_in_context"):
            found.append(f"claude_code: skills in context {probe.get('skills_in_context')!r}")
        if probe.get("context_tokens") is not None and probe["context_tokens"] > CLAUDE_PROBE_CONTEXT_LIMIT:
            found.append(f"claude_code: probe context {probe['context_tokens']} tokens, above {CLAUDE_PROBE_CONTEXT_LIMIT}")
    elif cli == "codex_cli":
        if probe.get("isolated_run") is False:
            found.append("codex_cli: the probe ran without the isolated subprocess call")
        extra = sorted(set(probe.get("skills") or ()) - BUILTIN_CODEX_SKILLS)
        if extra:
            found.append(f"codex_cli: skills beyond the built-in ones {extra!r}")
    else:
        found.append(f"unknown CLI {cli!r}")
    return found
