"""Codex CLI (`codex exec`) as a provider client, and a call log for any CLI subject.

The kernel already drives Claude Code through ``ClaudeCodePrintClient``: one
subprocess per action, tools off, the family prompt as the system prompt, the
action schema enforced by the CLI, the executable's version and digest sealed
into every request. This is the same contract for Codex, kept outside the
kernel because it is a development probe; if it becomes a supported route it
moves into ``shared_runner`` through the kernel lane.

What the subject is. One ``codex exec`` process per action, with

* the family prompt as the model's instructions (``model_instructions_file``,
  which replaces Codex's own agent instructions, as ``--system-prompt`` does
  for Claude Code),
* the observation on standard input,
* the action schema as ``--output-schema``,
* no user configuration, no session persistence, an empty working directory,
  a read-only sandbox, web search off and every feature that gives the model
  a way to act on the machine switched off (``DISABLED_FEATURES``).

Codex cannot be started with no tool definitions at all, so a call whose event
stream contains anything other than reasoning and the final message is refused
as a contract failure and never scored. The stream of every call is kept in the
provider result.

Codex under a ChatGPT login reports tokens and no charge, so the result carries
no cost and the kernel prices the call from the sealed list price.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    EvidenceIntegrityError,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
)

PROVIDER = "codex_cli"

#: Features that hand the model a shell, a browser, other agents, plugins,
#: connectors, memory or files. Read from ``codex features list`` on 0.160.0;
#: with these off a probe asked to run ``pwd`` answered that it could not and
#: the event stream held no command.
DISABLED_FEATURES: tuple[str, ...] = (
    "shell_tool", "unified_exec", "apps", "plugins", "multi_agent", "image_generation",
    "memories", "browser_use", "browser_use_external", "computer_use", "goals",
    "view_image", "skill_search", "tool_suggest", "sleep_tool", "hooks",
    "in_app_browser", "remote_plugin", "workspace_dependencies",
)
#: Event items a tool-less turn may contain.
PASSIVE_ITEMS = frozenset({"agent_message", "reasoning"})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


async def _run(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate(standard_input)
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    return process.returncode, stdout, stderr


class CodexExecClient:
    """One tool-less ``codex exec`` call per provider request."""

    def __init__(self, *, executable: Path, runtime_version: str, runtime_sha256: str) -> None:
        self._executable = executable
        self.runtime_version = runtime_version
        self.runtime_sha256 = runtime_sha256
        self._adapter_sha256 = _sha256_file(Path(__file__))

    @classmethod
    async def discover(cls, executable: str = "codex") -> "CodexExecClient":
        resolved = shutil.which(executable)
        if resolved is None:
            raise EvidenceIntegrityError(f"Codex executable is unavailable: {executable!r}")
        path = Path(resolved).resolve()
        returncode, stdout, stderr = await _run((str(path), "--version"), b"")
        if returncode != 0:
            raise EvidenceIntegrityError(
                f"Codex version probe failed with exit {returncode}: {stderr.decode(errors='replace').strip()}"
            )
        words = stdout.decode().split()
        if not words:
            raise EvidenceIntegrityError("Codex version probe returned no version")
        return cls(executable=path, runtime_version=words[-1], runtime_sha256=_sha256_file(path))

    @property
    def runtime_metadata(self) -> Mapping[str, str]:
        """Sealed into the profile; a request whose metadata differs is refused."""
        return MappingProxyType(
            {
                "runtime_version": self.runtime_version,
                "runtime_sha256": self.runtime_sha256,
                "adapter_sha256": self._adapter_sha256,
                "sandbox": "read-only",
                "web_search": "disabled",
                "user_config": "ignored",
                "instructions": "model_instructions_file (replaces the agent instructions)",
                "disabled_features": ",".join(DISABLED_FEATURES),
            }
        )

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        def refuse(message: str) -> ProviderFailure:
            return ProviderFailure("provider_contract", message, retryable=False)

        if request.messages is not None:
            raise refuse("Codex adapter does not support native chat messages")
        if request.provider != PROVIDER:
            raise refuse(f"Codex adapter received provider {request.provider!r}")
        if request.base_url is not None:
            raise refuse("Codex adapter does not accept a base URL")
        if request.revision != request.model:
            raise refuse("Codex runs name the model itself as its revision")
        if not isinstance(request.output_schema, Mapping):
            raise refuse("Codex adapter requires a structured output schema")
        declared = request.provider_metadata
        if not isinstance(declared, Mapping) or dict(declared) != dict(self.runtime_metadata):
            raise refuse("sealed Codex runtime metadata does not match the adapter")
        if _sha256_file(self._executable) != self.runtime_sha256:
            raise refuse("Codex runtime digest changed after plan resolution")

        scratch = Path(tempfile.mkdtemp(prefix="aeread_codex_call_"))
        try:
            empty = scratch / "cwd"
            empty.mkdir()
            (scratch / "instructions.md").write_text(request.instructions, encoding="utf-8")
            (scratch / "schema.json").write_bytes(canonical_json_bytes(request.output_schema))
            last = scratch / "last_message.txt"
            arguments: list[str] = [
                str(self._executable), "exec", "--ignore-user-config",
                "-m", request.model,
                "-c", f'model_reasoning_effort="{request.reasoning_effort or "medium"}"',
                "-c", "suppress_unstable_features_warning=true",
                "-c", f'model_instructions_file="{scratch / "instructions.md"}"',
                "-c", 'web_search="disabled"',
            ]
            for feature in DISABLED_FEATURES:
                arguments += ["--disable", feature]
            arguments += [
                "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
                "-C", str(empty), "--output-schema", str(scratch / "schema.json"),
                "-o", str(last), "--json", "-",
            ]
            try:
                returncode, stdout, stderr = await asyncio.wait_for(
                    _run(tuple(arguments), request.input_text.encode("utf-8")),
                    timeout=request.timeout_seconds,
                )
            except asyncio.TimeoutError as error:
                raise ProviderFailure("timeout", "Codex invocation timed out", retryable=True) from error
            events: list[dict[str, Any]] = []
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                if line.startswith("{"):
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            usage: Mapping[str, Any] | None = None
            thread_id = ""
            acted: list[dict[str, Any]] = []
            failures: list[str] = []
            for event in events:
                kind = event.get("type")
                item = event.get("item") if isinstance(event.get("item"), Mapping) else {}
                if kind == "thread.started":
                    thread_id = str(event.get("thread_id") or "")
                elif kind == "turn.completed" and isinstance(event.get("usage"), Mapping):
                    usage = event["usage"]
                elif kind in {"turn.failed", "error"}:
                    failures.append(json.dumps(event, sort_keys=True)[:600])
                elif kind == "item.completed" and item.get("type") == "error":
                    failures.append(str(item.get("message"))[:600])
                elif kind in {"item.started", "item.completed"} and item.get("type") not in PASSIVE_ITEMS:
                    acted.append({"event": kind, "item_type": item.get("type"),
                                  "detail": json.dumps(item, sort_keys=True)[:400]})
            raw = {"thread_id": thread_id, "usage": dict(usage) if usage else None, "tool_items": acted,
                   "errors": failures, "exit_code": returncode, "event_types": [e.get("type") for e in events]}
            if usage is None or returncode != 0:
                text = " | ".join(failures) or stderr.decode("utf-8", errors="replace").strip()[-600:]
                limited = any(word in text.lower() for word in ("usage limit", "rate limit", "429", "too many requests"))
                raise ProviderFailure(
                    "rate_limit" if limited else "provider_rejected",
                    f"Codex exited with {returncode} and no completed turn: {text}",
                    retryable=limited,
                )
            if acted:
                raise refuse(
                    "Codex used a tool in a run that declares none: "
                    + "; ".join(f"{row['item_type']}" for row in acted)
                )
            try:
                structured = json.loads(last.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise refuse("Codex did not write one JSON final message") from error
            if not isinstance(structured, Mapping):
                raise refuse("Codex final message must be a JSON object")

            def count(field: str) -> int:
                value = usage.get(field, 0)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise refuse(f"Codex usage field {field!r} is invalid")
                return value

            return ProviderResult(
                response_id=thread_id,
                requested_model=request.model,
                resolved_model=None,
                output_text=canonical_json_bytes(structured).decode("utf-8"),
                finish_reason="stop",
                input_tokens=count("input_tokens"),
                cached_input_tokens=count("cached_input_tokens"),
                output_tokens=count("output_tokens"),
                cost_usd=None,
                raw_response=raw,
                reasoning_tokens=count("reasoning_output_tokens"),
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


class LoggedClient:
    """Passes every call through and appends one line per call to ``log_path``.

    The line holds what a wall-time and spend estimate needs (seconds, tokens,
    the cost the provider reported, how the call failed) and nothing the model
    wrote. The sealed evidence stays the record; this is a convenience index.
    """

    def __init__(self, inner: Any, log_path: Path, *, subject: str) -> None:
        self._inner, self._log, self._subject = inner, log_path, subject
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        started = time.perf_counter()
        row: dict[str, Any] = {"subject": self._subject, "provider_call_id": request.provider_call_id,
                               "input_chars": len(request.input_text)}
        try:
            result = await self._inner.complete(request)
        except ProviderFailure as failure:
            row.update(status="failed", condition=failure.condition, message=str(failure)[:300])
            raise
        else:
            row.update(status="ok", input_tokens=result.input_tokens,
                       cached_input_tokens=result.cached_input_tokens,
                       output_tokens=result.output_tokens, reported_cost_usd=result.cost_usd,
                       reasoning_tokens=result.reasoning_tokens)
            return result
        finally:
            row["seconds"] = round(time.perf_counter() - started, 2)
            with self._log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
