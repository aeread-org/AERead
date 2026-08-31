"""EverOS-backed persistent memory for AERead submitted agents (experimental).

`EverOS <https://github.com/EverMind-AI/EverOS>`_ is an open-source,
markdown-first memory service. This integration turns it into a *treatment
arm* for AERead: a :class:`MemoryCandidate` satisfies the text-boundary
submission contract (``act(observation, phase) -> str``) while

- **searching** memory before every action (past episodes in the same case
  family, extracted agent cases/skills), and
- **writing** the finished episode transcript + outcome back after scoring,

so realized-welfare deltas between a memory-on and memory-off arm measure
what persistent cross-episode memory is worth in a decentralized exchange
economy. Memory is scoped per case family via EverOS ``project_id`` — no
information crosses the submission info-barrier: the candidate only ever
remembers what it itself observed through the text boundary.

Run a local server (see the EverOS quickstart; any OpenAI-compatible
LLM/embedding endpoints work)::

    pip install everos && everos init && everos server start --port 8377

Caveats (deliberate, documented):

- Cross-episode state means a replayed episode sees different memory than
  the live run; run A/B experiments with ``verify_replay=False`` and treat
  official replay-verified submissions as memory-off.
- ``method="vector"`` is the default search mode — it skips EverOS's
  reranker stage, so no rerank provider is required.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

MEMORY_HEADER = (
    "PRIOR EXPERIENCE (from your persistent memory of past episodes "
    "in this case family):")

_SNIPPET_FIELDS = ("summary", "content", "description", "task_intent",
                   "key_insight", "title", "name")


class EverOSMemoryError(RuntimeError):
    """Non-2xx or malformed response from the EverOS server."""


class NullMemory:
    """Memory-off control: no recall, writes discarded. Same code path."""

    def search(self, query: str, **kw: Any) -> dict[str, Any]:  # noqa: ARG002
        return {}

    def add(self, session_id: str, messages: list) -> str:  # noqa: ARG002
        return "discarded"

    def flush(self, session_id: str) -> str:  # noqa: ARG002
        return "no_extraction"


class EverOSMemory:
    """Minimal stdlib client for the EverOS HTTP API (add / flush / search)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8377", *,
                 app_id: str = "aeread", project_id: str = "default",
                 timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_id = app_id
        self.project_id = project_id
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:  # pragma: no cover - network
            raise EverOSMemoryError(
                f"{path} -> HTTP {err.code}: {err.read().decode('utf-8')[:300]}"
            ) from err
        data = obj.get("data")
        if data is None:
            raise EverOSMemoryError(f"{path} -> missing data envelope: {obj}")
        return data

    def add(self, session_id: str, messages: list[dict[str, Any]]) -> str:
        data = self._post("/api/v2/memory/add", {
            "session_id": session_id, "app_id": self.app_id,
            "project_id": self.project_id, "messages": messages})
        return data.get("status", "")

    def flush(self, session_id: str) -> str:
        data = self._post("/api/v2/memory/flush", {
            "session_id": session_id, "app_id": self.app_id,
            "project_id": self.project_id})
        return data.get("status", "")

    def search(self, query: str, *, user_id: str | None = None,
               agent_id: str | None = None, method: str = "vector",
               top_k: int = 4,
               min_score: float | None = None) -> dict[str, Any]:
        if bool(user_id) == bool(agent_id):
            raise ValueError("exactly one of user_id / agent_id must be set")
        payload: dict[str, Any] = {
            "query": query, "method": method, "top_k": top_k,
            "app_id": self.app_id, "project_id": self.project_id}
        if min_score is not None:
            payload["min_score"] = min_score
        if user_id:
            payload["user_id"] = user_id
        else:
            payload["agent_id"] = agent_id
        return self._post("/api/v2/memory/search", payload)


def _snippet(item: dict[str, Any]) -> str:
    parts = [str(item[f]).strip() for f in _SNIPPET_FIELDS
             if item.get(f) and str(item[f]).strip()]
    return " — ".join(dict.fromkeys(parts))


class MemoryCandidate:
    """Text-boundary submitted agent with EverOS persistent memory.

    ``llm_fn(prompt) -> str`` is the policy model (see
    :func:`build_openrouter_llm_fn`); ``memory`` is an :class:`EverOSMemory`
    (or any duck-type). Memory failures never fail the episode — the agent
    degrades to memoryless operation and counts ``memory_errors``.
    """

    def __init__(self, llm_fn: Callable[[str], str], memory: Any, *,
                 agent_id: str = "aeread_mem", arena_user_id: str = "arena",
                 memory_top_k: int = 4, search_method: str = "vector",
                 min_score: float | None = None, distill: bool = False,
                 overfetch: int = 1,
                 clock: Callable[[], float] = time.time) -> None:
        self.llm_fn = llm_fn
        self.memory = memory
        self.agent_id = agent_id
        self.arena_user_id = arena_user_id
        self.memory_top_k = memory_top_k
        self.search_method = search_method
        self.min_score = min_score
        self.distill = distill
        self.overfetch = max(1, int(overfetch))
        self._clock = clock
        self.label = "episode"
        self.session_id = f"{agent_id}-episode"
        self.turns: list[dict[str, str]] = []
        self.memory_errors = 0
        self._buffer: list[dict[str, Any]] = []
        self._last_ts = 0
        self._session_outcomes: dict[str, float] = {}

    def __repr__(self) -> str:  # keeps submission labels readable
        return f"MemoryCandidate(agent_id={self.agent_id!r})"

    @property
    def blank_turns(self) -> int:
        """Turns this episode that emitted nothing through the boundary.

        A blank turn scores as a valid no-op, so it is invisible in the AER
        alone. It is also invisible to the runner's mute circuit breaker,
        which excludes ``submitted``-origin calls by design (the no-op
        baseline is silent on purpose). Counting it here is the only place
        an A/B arm can see it.
        """
        return sum(1 for t in self.turns
                   if not (t.get("response") or "").strip())

    # -- episode lifecycle -------------------------------------------------

    def begin_episode(self, label: str) -> None:
        self.label = label
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")[:100]
        self.session_id = f"{self.agent_id}-{slug}"
        self._buffer = []
        self.turns = []

    def end_episode(self, outcome: str) -> None:
        m = re.search(r"AER=([-+]?[0-9.]+)", outcome)
        if m:
            self._session_outcomes[self.session_id] = float(m.group(1))
        msgs = list(self._buffer)
        reflection = (
            f"Episode complete ({self.label}). Outcome: {outcome}. "
            "Remember which negotiation moves led to executed, "
            "welfare-positive settlements in this case family and "
            "which lost value or failed verification.")
        if self.distill and self.turns:
            lessons = self._distill(outcome)
            if lessons:
                reflection = (f"Episode complete ({self.label}). "
                              f"Outcome: {outcome}.\n{lessons}")
        msgs.append({
            "sender_id": self.agent_id, "sender_name": "AEReadCandidate",
            "role": "assistant", "timestamp": self._now_ms(),
            "content": reflection})
        try:
            self.memory.add(self.session_id, msgs)
            self.memory.flush(self.session_id)
        except Exception:
            self.memory_errors += 1
        self._buffer = []

    def _distill(self, outcome: str) -> str:
        """One LLM call turning the episode into transferable lessons.

        World-specific numbers are explicitly excluded — retrieval feeds these
        lessons into *different* worlds, where this episode's quantities and
        holdings are false.
        """
        moves = "\n".join(f"[{t['phase']}] {t['response'][:400]}"
                          for t in self.turns[-12:])
        prompt = (
            f"You just finished a negotiation episode in the case family "
            f"'{self.label}'. Final outcome: {outcome}.\n"
            f"Your actions were:\n{moves}\n\n"
            "Write 2-4 short, transferable strategy lessons for future "
            "episodes of this case family. Rules: describe negotiation "
            "moves and their consequences in general terms; do NOT mention "
            "specific resource quantities, holdings, or prices (they differ "
            "in every world); each lesson on its own line starting with "
            "'Lesson:'.")
        try:
            return (self.llm_fn(prompt) or "").strip()
        except Exception:
            return ""

    # -- acting ------------------------------------------------------------

    def act(self, observation: str, phase: str) -> str:
        snippets = self.recall(observation, phase)
        prompt = observation
        if snippets:
            block = "\n".join(f"- {s}" for s in snippets)
            prompt = (f"{observation}\n\n{MEMORY_HEADER}\n{block}\n"
                      "(Use this experience where it applies; the current "
                      "episode's own numbers always take precedence.)")
        text = (self.llm_fn(prompt) or "").strip()
        self._buffer.append({
            "sender_id": self.arena_user_id, "role": "user",
            "timestamp": self._now_ms(),
            "content": f"[{phase}] {observation}"})
        self._buffer.append({
            "sender_id": self.agent_id, "sender_name": "AEReadCandidate",
            "role": "assistant", "timestamp": self._now_ms(),
            "content": text})
        self.turns.append({"phase": phase, "observation": observation,
                           "response": text,
                           "memory_snippets": len(snippets)})
        return text

    def recall(self, observation: str, phase: str) -> list[str]:
        query = f"{self.label} {phase}: {observation[:300]}"
        found: list[tuple[str, bool]] = []  # (snippet, from_failed_episode)
        for scope in ({"agent_id": self.agent_id},
                      {"user_id": self.arena_user_id}):
            try:
                # over-fetch so the outcome filter can SUBSTITUTE success
                # material rather than starve injection (v3's failure mode)
                kw: dict[str, Any] = dict(
                    method=self.search_method,
                    top_k=min(100, self.memory_top_k * self.overfetch),
                    **scope)
                if self.min_score is not None:
                    kw["min_score"] = self.min_score
                data = self.memory.search(query, **kw) or {}
            except Exception:
                self.memory_errors += 1
                continue
            for kind in ("agent_skills", "agent_cases", "episodes"):
                for item in data.get(kind) or []:
                    text = _snippet(item)
                    if not text:
                        continue
                    aer = self._session_outcomes.get(
                        str(item.get("session_id") or ""))
                    found.append((text, aer is not None and aer <= 1e-9))
        # outcome-aware filter: drop snippets from episodes known to have
        # realized nothing, unless nothing better survives (fallback, not
        # amnesia) — failure recaps compounding was the v2 arm's doom loop.
        kept = [t for t, failed in found if not failed]
        if not kept:
            kept = [t for t, _ in found]
        return list(dict.fromkeys(kept))[:self.memory_top_k]

    def _now_ms(self) -> int:
        ts = int(self._clock() * 1000)
        self._last_ts = max(ts, self._last_ts + 1)
        return self._last_ts


def build_openrouter_llm_fn(model: str, *, base_url: str | None = None,
                            api_key: str | None = None,
                            temperature: float = 0.7,
                            max_tokens: int = 4096,
                            client: Any = None) -> Callable[[str], str]:
    """Chat-completions policy fn for :class:`MemoryCandidate`.

    Defaults to the ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY`` environment
    (OpenRouter in the AERead reference setup). Reasoning-style models spend
    completion budget on reasoning before emitting content — a too-small
    ``max_tokens`` silently yields EMPTY responses (the 2026-08-01 mute
    audit), so the default budget is generous and an empty response is
    retried once with an escalated budget. ``client`` is injectable for
    tests.
    """
    import os

    if client is None:
        from openai import OpenAI
        client = OpenAI(
            base_url=base_url or os.environ.get(
                "OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=api_key or os.environ.get("OPENAI_API_KEY", "EMPTY"))

    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "empty_retries": 0}

    def _call(prompt: str, budget: int) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=budget)
        usage["calls"] += 1
        if resp.usage is not None:
            usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
            usage["completion_tokens"] += resp.usage.completion_tokens or 0
        return (resp.choices[0].message.content or "").strip()

    def llm_fn(prompt: str) -> str:
        text = _call(prompt, max_tokens)
        if not text:
            usage["empty_retries"] += 1
            text = _call(prompt, max(max_tokens * 2, 8192))
        return text

    llm_fn.usage = usage  # type: ignore[attr-defined] - cost reporting
    return llm_fn


def arm_health(rows: list[dict[str, Any]], *, memory_arm: bool,
               max_blank_rate: float = 0.10,
               max_memory_errors: int = 0) -> dict[str, Any]:
    """Validity counters an A/B arm must not be allowed to skip.

    Three failure modes here produce a *valid-looking* pooled AER rather
    than an error, so each has to be counted explicitly:

    - **muted turns** — the candidate returned an empty string and the
      round scored as a deliberate no-op;
    - **undelivered treatment** — the memory arm injected nothing, making
      it a second control while still being reported as the treatment;
    - **partial degradation** — some episodes lost memory to a transport
      error and silently ran memoryless.

    ``rows`` are the per-episode result rows. Only ``status == "ok"`` rows
    count; a failed episode has no turns to judge.
    """
    ok = [r for r in rows if r.get("status") == "ok"]
    turns = sum(int(r.get("turns") or 0) for r in ok)
    blank = sum(int(r.get("blank_turns") or 0) for r in ok)
    snippets = sum(int(r.get("memory_snippets") or 0) for r in ok)
    errors = sum(int(r.get("memory_errors") or 0) for r in ok)
    rate = (blank / turns) if turns else None

    problems: list[str] = []
    if memory_arm and ok and snippets == 0:
        problems.append(
            f"treatment not delivered: 0 memory snippets injected across "
            f"{len(ok)} ok episodes")
    if rate is not None and rate > max_blank_rate:
        problems.append(
            f"blank-turn rate {rate:.1%} exceeds {max_blank_rate:.0%} "
            f"({blank}/{turns} turns muted)")
    if memory_arm and errors > max_memory_errors:
        problems.append(
            f"{errors} memory error(s): the arm degraded to memoryless on "
            "some turns")
    return {"episodes": len(ok), "turns": turns, "blank_turns": blank,
            "blank_turn_rate": rate, "memory_snippets": snippets,
            "memory_errors": errors, "problems": problems}


def should_abort_memory_arm(rows: list[dict[str, Any]], *,
                            min_episodes: int = 3) -> str | None:
    """Reason to stop a memory arm early, or ``None`` to keep going.

    A memory server that is up but returning nothing produces a clean run
    with ``memory_errors == 0`` and no injected context. Catching that at
    three episodes rather than twelve is the difference between a cheap
    restart and a full arm's spend on an accidental second control.
    """
    ok = [r for r in rows if r.get("status") == "ok"]
    if len(ok) < min_episodes:
        return None
    if sum(int(r.get("memory_snippets") or 0) for r in ok):
        return None
    return (f"memory arm injected 0 memory snippets across its first "
            f"{len(ok)} completed episodes: the memory server is returning "
            "nothing and this arm is a second control")


def run_memory_episode(case_path: str | Path, seed: int,
                       candidate: MemoryCandidate, *,
                       agent_label: str = "everos-mem",
                       max_tokens: int = 1200,
                       out_root: str | Path | None = None) -> dict[str, Any]:
    """One seeded episode through the submission harness, with memory hooks.

    Mirrors :func:`aeread.integrations.rllm_flow.run_episode` but drives an
    externally-owned candidate: ``begin_episode`` before the run,
    ``end_episode(outcome)`` with the realized score row after. Replay
    verification is off (cross-episode memory makes replay non-bytewise).
    """
    import tempfile

    from aeread.exchange_v1 import pilot as pilot
    from aeread.exchange_v1 import runner as runner
    from aeread.exchange_v1 import submit as submit

    case_path = Path(case_path)
    candidate.begin_episode(f"{case_path.stem}-s{int(seed)}")

    def _run(out: Path) -> dict[str, Any]:
        (out / "cases").mkdir(parents=True, exist_ok=True)
        prepared = pilot.seeded_case(case_path, int(seed), out / "cases",
                                     agent_label)
        sub_dir = submit.run_submission(
            [prepared], candidate, agent_label=agent_label,
            out_root=out / "submissions",
            options=runner.InferenceOptions(max_tokens=max_tokens),
            verify_replay=False, quiet=True)
        report = json.loads((sub_dir / "submission_report.json").read_text())
        return report["cases"][0]

    if out_root is None:
        with tempfile.TemporaryDirectory() as td:
            case_row = _run(Path(td))
    else:
        case_row = _run(Path(out_root))

    score = case_row.get("score") or {}
    w_real = score.get("w_real")
    denom = score.get("denominator")
    aer = None
    if w_real is not None and denom and denom > 1e-9:
        aer = float(w_real) / float(denom)
    outcome = (f"status={case_row.get('status')} AER="
               f"{'n/a' if aer is None else format(aer, '.3f')} "
               f"(w_real={w_real} denominator={denom})")
    blank = candidate.blank_turns  # before end_episode, which may distill
    candidate.end_episode(outcome)
    return {"status": case_row.get("status"), "aer": aer, "w_real": w_real,
            "denominator": denom, "score": score, "turns": candidate.turns,
            "blank_turns": blank,
            "memory_errors": candidate.memory_errors,
            # carry the harness's own reason forward: without it a failed
            # episode lands in results.jsonl as a bare "harness_error" with
            # no way to tell a mute trip from a provider outage
            "error": case_row.get("error")}
