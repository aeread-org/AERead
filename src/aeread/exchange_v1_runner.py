"""Exchange V1 runner — config-agnostic execution + reproducibility spine (Part A).

Wraps the existing 10-phase engine (`exchange_economy.run_exchange_transcript`) without
re-implementing any game logic. Every invocation produces one self-contained run
directory that downstream scoring reads and that replay can reproduce:

    runs/<run_id>/
      run_meta.json             provenance: schema version, git commit, config hash,
                                seed, mode, models, argv, cache-relevant env, usage
      config_snapshot.json      the resolved ExchangeExperimentConfig actually used
      trace.jsonl               written by the engine's own trace writer (one row/round)
      inference_manifest.jsonl  one row per LLM call (live_frozen / replay modes)
      llm_cache/                per-call response snapshots replay serves from
      summary.json              build_run_summary_payload + usage/cost totals

Modes (selected via the policy object — the single offline/live seam):
  offline      scripted deterministic policy, zero API calls. Infra/CI/determinism
               runs; NOT a scored model run.
  live_frozen  real LLM policy; every call recorded to the manifest + llm_cache.
  replay       real policy classes, but responses served from a prior run's
               llm_cache; any fresh provider call hard-fails.

Usage:
    python sprint/exchange_v1_runner.py --config configs/exchange_economy/X.json \
        --seed 7 --mode offline --out runs/
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aeread import exchange_economy as ex  # noqa: E402
from aeread.exchange_v1_roles import (  # noqa: E402
    KIND_FROZEN_LLM,
    KIND_LIVE_LEARNING,
    KIND_LLM,
    KIND_SCRIPTED,
    KIND_SCRIPTED_EXTRACT,
    KIND_SCRIPTED_OPTIMAL,
    KIND_SUBMITTED,
    CompositePolicy,
    RoleConfigError,
    RoleTable,
    SubmittedAgentPolicy,
    parse_role_table,
)

RUN_SCHEMA_VERSION = "1.0"
# 1.1: + resolved_model (provider-reported model version) on every row
# 1.2: + seat (under_test | panel | env) on every row — D9 per-role seam
MANIFEST_SCHEMA_VERSION = "1.2"
REPO_ROOT = Path(__file__).resolve().parents[1]

# Env vars that are folded into llm_agent's cache key (or select the provider path).
# Recorded in run_meta.json so replay can detect a mismatched environment. Never
# record secret values — only whether a key is set.
_CACHE_RELEVANT_ENV = (
    "OPENAI_BASE_URL",
    "OPENROUTER_REASONING_EFFORT",
    "OPENAI_GPT5_REASONING_EFFORT",
    "OPENAI_GPT5_MIN_COMPLETION_TOKENS",
)
_SECRET_PRESENCE_ENV = ("OPENAI_API_KEY", "GEMINI_API_KEY", "GEMINI_VERTEX")

MODES = ("offline", "live_frozen", "replay")


class RunnerError(RuntimeError):
    """Harness-level failure (bad arguments, broken artifacts) — never an economic result."""


# ===============================================================
# Offline scripted policy (the no-API seam)
# ===============================================================


class ScriptedBilateralIRPolicy:
    """Deterministic scripted policy for `--mode offline` — zero LLM calls.

    Each round it brute-forces (in a fixed iteration order) a bilateral swap between
    the controller and another agent that is feasible and strictly individually
    rational for BOTH sides, and compiles exactly that; when no such swap exists
    (e.g. ring-cycle worlds with cycle_length >= 3) it compiles an explicit no-op.
    Purpose: exercising the runner/trace/replay spine and CI determinism checks.
    Offline runs are infra-grade, never scored model runs.
    """

    label_swap = "scripted_bilateral_swap"
    label_noop = "scripted_noop"

    SELECTION_FIRST_IR = "first_ir"      # myopic L1 panel: first mutually-IR swap in scan order
    SELECTION_MAX_JOINT = "max_joint"    # full-info benevolent: max total surplus (-> W*)
    SELECTION_MAX_OWN = "max_own"        # full-info self-interested: max this seat's own surplus
    SELECTIONS = (SELECTION_FIRST_IR, SELECTION_MAX_JOINT, SELECTION_MAX_OWN)

    def __init__(
        self,
        quantity_ladder: tuple[int, ...] = (1, 2, 3, 5, 10),
        min_gain: float = 1e-9,
        selection: str = SELECTION_FIRST_IR,
    ) -> None:
        if selection not in self.SELECTIONS:
            raise ValueError(
                f"unknown selection {selection!r}; expected one of {self.SELECTIONS}"
            )
        self.protocol: Optional[ex.ProtocolConfig] = None  # assigned by run_exchange_transcript
        self.quantity_ladder = tuple(sorted(set(quantity_ladder)))
        self.min_gain = float(min_gain)
        self.selection = selection

    # -- text phases (deterministic, side-effect free) --

    def communication_text(self, world, agent_id, round_index, history) -> str:
        return (
            "PUBLIC ACTION\n"
            f"a{agent_id}: standing by for mutually beneficial bilateral trades "
            "(scripted offline policy)."
        )

    def propose_text(self, world, agent_id, round_index, history, communication_texts) -> str:
        mechanism = self._find_bilateral_ir_swap(world, agent_id)
        if mechanism is None:
            return (
                "PUBLIC ACTION\n"
                f"a{agent_id}: no strictly mutually beneficial bilateral swap exists; "
                "proposing no-op this round."
            )
        return "PUBLIC ACTION\n" + mechanism.summary

    def respond_text(self, world, agent_id, transcript, history) -> str:
        # Echo the CONCRETE proposal, not a generic conditional consent: the
        # frozen-LLM compiler cannot turn "I consent to any beneficial trade"
        # into transfers, so a scripted panel seat that abstains this way makes
        # every round compile to a no-op (the 2026-07-20 scripted-panel-collapse
        # diagnosis: greedy scored 0.150 vs the LLM panel but 0.000 vs the
        # scripted panel, despite identical world-derived proposals). The
        # controller's proposal_text is the exact swap; restate it as an explicit
        # acceptance when this seat is a beneficiary, else decline concretely.
        proposal = getattr(transcript, "proposal_text", "") or ""
        return (
            "PUBLIC ACTION\n"
            f"a{agent_id}: I ACCEPT the proposed trade exactly as stated: "
            f"{proposal.replace(chr(10), ' ').removeprefix('PUBLIC ACTION ').strip()}"
        )

    def finalize_text(self, world, agent_id, transcript, history) -> str:
        return f"PUBLIC ACTION\na{agent_id}: finalize exactly as proposed."

    def private_acceptance_text(self, world, agent_id, transcript, mechanism, history) -> str:
        # Real IR consent for composite (D9) seats: approve iff this seat's own
        # utility delta is strictly positive. Without this, a scripted panel seat
        # abstains and its empty text parses as malformed — fail-open silent
        # approval under llm_structured, unconditional rejection under strict.
        # The single-policy offline path is unchanged (the engine consumes only
        # the plural form, which this class still does not define).
        delta = ex.utility_delta_for_mechanism(world, mechanism, agent_id)
        sign = ex._delta_sign(delta)
        debits = ex._agent_transfer_rows(mechanism, agent_id, "debit")
        credits = ex._agent_transfer_rows(mechanism, agent_id, "credit")
        counterpart_present = bool(credits)
        approve = sign == "positive" and counterpart_present
        return json.dumps(
            {
                "approve": approve,
                "claimed_delta_sign": sign,
                "counterpart_transfers_present": counterpart_present,
                "same_bundle_authorized": True,
                "own_debits_seen": debits,
                "own_credits_seen": credits,
                "reason": "scripted IR consent: approve iff own utility delta is strictly positive",
            }
        )

    # -- compile / verify (the executable output) --

    def compile_transcript(self, world, transcript) -> ex.CompiledMechanism:
        mechanism = self._find_bilateral_ir_swap(world, transcript.controller_id)
        if mechanism is not None:
            return mechanism
        return ex.CompiledMechanism(
            proposer_id=transcript.controller_id,
            label=self.label_noop,
            summary="no strictly mutually IR bilateral swap found; no-op",
            transfers=[],
            consenting_agents=[],
            confidence=1.0,
        )

    def verify_compilation(self, world, transcript, mechanism) -> ex.CompiledMechanism:
        return mechanism

    # -- deterministic search --

    def _find_bilateral_ir_swap(self, world, proposer_id: int) -> Optional[ex.CompiledMechanism]:
        """A feasible, strictly-mutually-IR bilateral swap, selected by `self.selection`.

        Every mode scans the SAME candidate set in a fixed order (ascending partner id,
        then resource pair, then the quantity ladder) — the determinism guarantee — and
        differs only in which mutually-IR swap it returns:
          first_ir  -> the first one in scan order (the myopic L1 panel);
          max_joint -> the one maximizing total surplus (full-info benevolent -> W*);
          max_own   -> the one maximizing THIS seat's own surplus (full-info extractor).
        max_joint/max_own read the true world state (the realized draw); ties break to
        scan-order-first via the stable `max`, so every mode stays reproducible.
        """
        candidates: list[tuple[ex.CompiledMechanism, float, float]] = []
        p_hold = world.allocation[proposer_id - 1]
        for partner_id in range(1, world.num_agents + 1):
            if partner_id == proposer_id:
                continue
            q_hold = world.allocation[partner_id - 1]
            for r_out in range(1, world.num_resources + 1):
                if p_hold[r_out - 1] <= 0:
                    continue
                for r_in in range(1, world.num_resources + 1):
                    if r_in == r_out or q_hold[r_in - 1] <= 0:
                        continue
                    for q_out in self.quantity_ladder:
                        if q_out > p_hold[r_out - 1]:
                            break
                        for q_in in self.quantity_ladder:
                            if q_in > q_hold[r_in - 1]:
                                break
                            mechanism = ex.CompiledMechanism(
                                proposer_id=proposer_id,
                                label=self.label_swap,
                                summary=(
                                    f"a{proposer_id} gives {q_out} r{r_out} to a{partner_id} "
                                    f"for {q_in} r{r_in}"
                                ),
                                transfers=[
                                    ex.Transfer(proposer_id, partner_id, r_out, q_out),
                                    ex.Transfer(partner_id, proposer_id, r_in, q_in),
                                ],
                                consenting_agents=[proposer_id, partner_id],
                                confidence=1.0,
                            )
                            if not ex.compiled_mechanism_feasible(world, mechanism):
                                continue
                            own_gain = ex.utility_delta_for_mechanism(world, mechanism, proposer_id)
                            partner_gain = ex.utility_delta_for_mechanism(world, mechanism, partner_id)
                            if own_gain > self.min_gain and partner_gain > self.min_gain:
                                if self.selection == self.SELECTION_FIRST_IR:
                                    return mechanism  # preserve exact scan-order-first behavior
                                candidates.append((mechanism, own_gain, partner_gain))
        if not candidates:
            return None
        if self.selection == self.SELECTION_MAX_JOINT:
            return max(candidates, key=lambda c: c[1] + c[2])[0]
        return max(candidates, key=lambda c: c[1])[0]  # SELECTION_MAX_OWN


# ===============================================================
# Run-directory + provenance helpers
# ===============================================================


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_info(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    def _run(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(
                ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=10
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    commit = _run("rev-parse", "HEAD")
    status = _run("status", "--porcelain")
    return {
        "commit": commit,
        "branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def _cache_relevant_env() -> dict[str, Any]:
    env: dict[str, Any] = {name: os.environ.get(name) for name in _CACHE_RELEVANT_ENV}
    for name in _SECRET_PRESENCE_ENV:
        env[f"{name}_set"] = bool(os.environ.get(name))
    return env


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    # atomic: a crash mid-write must not leave a truncated artifact behind
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)


def make_run_id(config_name: str, model_label: str, seed: int, when: Optional[str] = None) -> str:
    if when is None:
        now = datetime.now(timezone.utc)
        # millisecond resolution: two runs of the same cell in the same second
        # must not collide on the run-dir name
        when = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
    safe_model = model_label.replace("/", "-").replace(":", "-")
    return f"{config_name}__{safe_model}__s{seed}__{when}"


def resolve_config(
    config_path: Path,
    *,
    seed: Optional[int] = None,
    rounds_override: Optional[int] = None,
    controllers_override: Optional[list[int]] = None,
) -> ex.ExchangeExperimentConfig:
    config = ex.load_experiment_config(config_path)
    config = ex.override_experiment_config_runtime(
        config, rounds=rounds_override, controllers=controllers_override
    )
    if seed is not None:
        config = dataclasses.replace(config, seed=seed)
    return config


# ===============================================================
# Inference manifest (D8) — one JSONL row per LLM call
# ===============================================================


class ManifestRecorder:
    """Writes inference_manifest.jsonl + per-call response snapshots (llm_cache/).

    Rows carry the natural join key back to the trace — (round_index, role,
    agent_id) — plus a readable call_id, the full prompt/response, hashes, usage
    (llm_agent's normalized keys) and cost. Snapshots are what replay serves from.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        total_rounds: Optional[int] = None,
        label: str = "live",
        verbose: bool = False,
    ) -> None:
        self.manifest_path = run_dir / "inference_manifest.jsonl"
        self.snapshot_dir = run_dir / "llm_cache"
        # eager, so a zero-call run is still a valid replay source
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text("")
        self.rows = 0
        self.funnel_rows = 0
        self.total_cost_usd = 0.0
        self.unpriced_rows = 0
        self._seq: dict[tuple[Any, Any, Any], int] = {}
        self._snapshot_response_sha: dict[str, str] = {}
        # per-seat aggregation (D9): cost split + resolved-model pinning evidence
        self.seat_totals: dict[str, dict[str, Any]] = {}
        self.resolved_models_by_seat: dict[str, set[str]] = {}
        self.resolved_models: dict[tuple[str, str], set[str]] = {}
        self._total_rounds = total_rounds
        self._label = label
        self._verbose = verbose
        self._progress_round: Optional[int] = None

    def _progress(self, round_index: Optional[int], role: str) -> None:
        """One line at each round boundary + a ticker every 25 calls, so a slow
        live run (sequential provider calls) is never a silent terminal."""
        if not self._verbose:
            return
        total = f"/{self._total_rounds}" if self._total_rounds else ""
        if round_index is not None and round_index != self._progress_round:
            self._progress_round = round_index
            print(
                f"[{self._label}] round {round_index}{total} started "
                f"({self.rows} calls, ${self.total_cost_usd:.4f} so far)",
                flush=True,
            )
        elif self.rows and self.rows % 25 == 0:
            print(
                f"[{self._label}]   … {self.rows} calls "
                f"(round {round_index}{total}, {role}, ${self.total_cost_usd:.4f})",
                flush=True,
            )

    def record(
        self,
        *,
        role: str,
        agent_id: Optional[int],
        round_index: Optional[int],
        system: str,
        prompt: str,
        response: Any,
        model: str,
        params: dict[str, Any],
        batched: bool,
        seat: str = "env",
        origin: str = "llm",  # "llm" (through the funnel) | "submitted" (foreign agent)
    ) -> None:
        from aeread import llm_agent

        replay_key = llm_agent.compute_replay_key(
            model, system, prompt,
            params["max_tokens"], params["temperature"], params["sample"],
        )
        self._progress(round_index, role)
        natural_key = (round_index, role, agent_id)
        seq = self._seq.get(natural_key, 0)
        self._seq[natural_key] = seq + 1
        agent_part = f"a{agent_id}" if agent_id is not None else "-"
        call_id = f"r{round_index if round_index is not None else '-'}:{role}:{agent_part}:{seq}"
        cost = getattr(response, "estimated_cost_usd", None)
        if cost is None and not getattr(response, "cached", False):
            self.unpriced_rows += 1
        self.total_cost_usd += cost or 0.0
        row = {
            "call_id": call_id,
            "round_index": round_index,
            "role": role,
            "agent_id": agent_id,
            "seat": seat,
            "origin": origin,
            "model": getattr(response, "model", model),
            "resolved_model": getattr(response, "resolved_model", None),
            "batched": batched,
            "cached": bool(getattr(response, "cached", False)),
            "params": dict(params),
            "system": system,
            "prompt": prompt,
            "response": response.text,
            "prompt_sha256": _sha256_bytes((system + "\x00" + prompt).encode("utf-8")),
            "response_sha256": _sha256_bytes(response.text.encode("utf-8")),
            "replay_key": replay_key,
            "usage": getattr(response, "usage", None),
            "estimated_cost_usd": cost,
            "cost_note": getattr(response, "cost_note", ""),
        }
        with self.manifest_path.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        self.rows += 1
        if origin == "llm":
            # only funnel-backed rows count against the observer/call_records
            # tallies; submitted-agent actions never touch the LLM funnel
            self.funnel_rows += 1
        seat_bucket = self.seat_totals.setdefault(
            seat, {"rows": 0, "estimated_cost_usd": 0.0, "unpriced_rows": 0}
        )
        seat_bucket["rows"] += 1
        seat_bucket["estimated_cost_usd"] = round(
            seat_bucket["estimated_cost_usd"] + (cost or 0.0), 10
        )
        if cost is None and not getattr(response, "cached", False):
            seat_bucket["unpriced_rows"] += 1
        resolved = getattr(response, "resolved_model", None)
        if resolved is not None:
            self.resolved_models_by_seat.setdefault(seat, set()).add(resolved)
            # keyed by (seat, request model) so two panel groups with different
            # models never pollute each other's pin evidence
            self.resolved_models.setdefault((seat, model), set()).add(resolved)
        # Two calls sharing one replay key must have returned the same text,
        # or replay would silently serve the last-written response to both and
        # diverge from the live trace. Fail loudly instead.
        previous_sha = self._snapshot_response_sha.get(replay_key)
        if previous_sha is not None and previous_sha != row["response_sha256"]:
            raise RunnerError(
                f"replay-key collision with divergent responses (key={replay_key}, "
                f"call_id={call_id}): this run cannot be replayed faithfully"
            )
        self._snapshot_response_sha[replay_key] = row["response_sha256"]
        llm_agent.write_response_snapshot(self.snapshot_dir, replay_key, response)

    def totals(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "funnel_rows": self.funnel_rows,
            "submitted_rows": self.rows - self.funnel_rows,
            "estimated_cost_usd": round(self.total_cost_usd, 10),
            "unpriced_rows": self.unpriced_rows,
            "by_seat": {seat: dict(bucket) for seat, bucket in sorted(self.seat_totals.items())},
        }


def check_pins(role_table: RoleTable, recorder: "ManifestRecorder") -> Optional[dict[str, Any]]:
    """Evaluate every pin_resolved_model against the recorder's per-(seat, model)
    evidence. Returns None when no seat declares a pin.

    Evidence is keyed by (manifest_seat, request model), so two panel groups
    sharing a seat label but using different models never pollute each other's
    pins. ok per pin: True (all observed == pin) / False (drift) /
    None (zero observations — unverifiable, e.g. the provider reported no
    version or the seat made no live calls; not a pass, not a failure).
    """
    entries = []
    for group in role_table.groups:
        pin = group.pin_resolved_model
        if not pin:
            continue
        observed = sorted(
            recorder.resolved_models.get((group.manifest_seat, group.policy.get("model")), set())
        )
        entries.append(
            {
                "seat": group.seat,
                "model": group.policy.get("model"),
                "pin": pin,
                "observed": observed,
                "ok": all(v == pin for v in observed) if observed else None,
            }
        )
    if not entries:
        return None
    return {"pins": entries, "ok": all(e["ok"] is not False for e in entries)}


def _make_manifest_policy_class(base: type) -> type:
    """Subclass ``base`` so every _call/_batch_call also writes a manifest row.

    _call is the one policy chokepoint that sees BOTH the call content
    (system/prompt/response) and the natural-key metadata (role, agent_id,
    round_index), so recording here needs no edit to the engine. The batch
    override records only when the true provider-batch path ran (the sequential
    fallback already records via _call — detected by the row count).
    """

    class ManifestRecordingPolicy(base):  # type: ignore[misc,valid-type]
        v1_recorder: Optional[ManifestRecorder] = None
        # compile/verify call sites don't thread round_index into _call; both
        # methods receive the transcript, so stash its round for the manifest row.
        _v1_round_hint: Optional[int] = None

        def compile_transcript(self, world, transcript):
            self._v1_round_hint = transcript.round_index
            try:
                return super().compile_transcript(world, transcript)
            finally:
                self._v1_round_hint = None

        def verify_compilation(self, world, transcript, mechanism):
            self._v1_round_hint = transcript.round_index
            try:
                return super().verify_compilation(world, transcript, mechanism)
            finally:
                self._v1_round_hint = None

        def _call(self, role, system, prompt, model, max_tokens, agent_id=None, round_index=None):
            response = super()._call(
                role, system, prompt, model, max_tokens,
                agent_id=agent_id, round_index=round_index,
            )
            if self.v1_recorder is not None:
                temperature, sample = self._role_sampling(role)
                self.v1_recorder.record(
                    role=role,
                    agent_id=agent_id,
                    round_index=round_index if round_index is not None else self._v1_round_hint,
                    system=system,
                    prompt=prompt,
                    response=response,
                    model=model,
                    params={"max_tokens": max_tokens, "temperature": temperature, "sample": sample},
                    batched=False,
                    seat=getattr(self, "v1_seat", "env"),
                )
            return response

        def _batch_call(self, role, calls, model):
            rows_before = self.v1_recorder.rows if self.v1_recorder is not None else 0
            responses = super()._batch_call(role, calls, model)
            if self.v1_recorder is not None and self.v1_recorder.rows == rows_before:
                temperature, sample = self._role_sampling(role)
                for call, response in zip(calls, responses):
                    self.v1_recorder.record(
                        role=role,
                        agent_id=call.get("agent_id"),
                        round_index=call.get("round_index"),
                        system=call["system"],
                        prompt=call["prompt"],
                        response=response,
                        model=model,
                        params={
                            "max_tokens": call["max_tokens"],
                            "temperature": temperature,
                            "sample": sample,
                        },
                        batched=True,
                        seat=getattr(self, "v1_seat", "env"),
                    )
            return responses

    ManifestRecordingPolicy.__name__ = f"Manifest{base.__name__}"
    return ManifestRecordingPolicy


# ===============================================================
# Policy factory (mirrors main()'s branching; one seam for all modes)
# ===============================================================


@dataclasses.dataclass(frozen=True)
class InferenceOptions:
    model: str = "google/gemini-3.5-flash"
    compiler_model: Optional[str] = None
    verifier_model: Optional[str] = None
    max_tokens: int = 1200
    temperature: float = 0.0
    sample: int = 0
    batch: bool = False


def _build_seat_policy(
    spec: dict[str, Any],
    config: ex.ExchangeExperimentConfig,
    options: InferenceOptions,
    under_test_agent: Optional[Any] = None,
):
    """Instantiate one seat's policy from its spec (D9/D10 policy kinds)."""
    kind = spec["kind"]
    if kind == KIND_SCRIPTED:
        return ScriptedBilateralIRPolicy()
    if kind == KIND_SCRIPTED_OPTIMAL:
        return ScriptedBilateralIRPolicy(selection=ScriptedBilateralIRPolicy.SELECTION_MAX_JOINT)
    if kind == KIND_SCRIPTED_EXTRACT:
        return ScriptedBilateralIRPolicy(selection=ScriptedBilateralIRPolicy.SELECTION_MAX_OWN)
    if kind == KIND_SUBMITTED:
        # live runs need the foreign agent; in replay the adapter serves the
        # recorded actions, so agent=None is valid there (checked at call time)
        return SubmittedAgentPolicy(under_test_agent, label=spec.get("name", "submitted"))
    if kind == KIND_LIVE_LEARNING:
        raise RunnerError(
            "policy kind 'live-learning' is reserved for the L3 gym (D17); "
            "it parses so today's cases stay valid, but it cannot run yet"
        )
    frozen = kind == KIND_FROZEN_LLM
    policy_cls = _make_manifest_policy_class(ex.LLMCompilerVerifierPolicy)
    return policy_cls(
        model=spec["model"],
        compiler_model=spec.get("compiler_model"),
        verifier_model=spec.get("verifier_model"),
        max_tokens=int(spec.get("max_tokens", options.max_tokens)),
        protocol=config.protocol,
        batch_enabled=False,  # composite routing forfeits provider-batch in v0
        temperature=0.0 if frozen else float(spec.get("temperature", options.temperature)),
        sample=0 if frozen else int(spec.get("sample", options.sample)),
    )


def build_composite_policy(
    role_table: RoleTable,
    config: ex.ExchangeExperimentConfig,
    options: InferenceOptions,
    under_test_agent: Optional[Any] = None,
) -> CompositePolicy:
    """Assemble the D9 seat table into one engine-facing policy object."""
    agent_policies: dict[int, Any] = {}
    for group in role_table.agent_groups():
        policy = _build_seat_policy(
            group.policy,
            config,
            options,
            under_test_agent=under_test_agent if group.seat == "under_test" else None,
        )
        policy.v1_seat = group.manifest_seat
        for agent_id in group.agents:
            agent_policies[agent_id] = policy
    compiler = _build_seat_policy(role_table.group_for("compiler").policy, config, options)
    compiler.v1_seat = "env"
    verifier = _build_seat_policy(role_table.group_for("verifier").policy, config, options)
    verifier.v1_seat = "env"
    return CompositePolicy(agent_policies, compiler, verifier)


def build_policy(
    mode: str,
    config: ex.ExchangeExperimentConfig,
    options: InferenceOptions,
    role_table: Optional[RoleTable] = None,
    under_test_agent: Optional[Any] = None,
):
    if mode == "offline":
        return ScriptedBilateralIRPolicy()
    if mode not in ("live_frozen", "replay"):
        raise RunnerError(f"unknown mode {mode!r}; expected one of {MODES}")
    if role_table is not None:
        return build_composite_policy(
            role_table, config, options, under_test_agent=under_test_agent
        )
    policy_kwargs: dict[str, Any] = dict(
        model=options.model,
        compiler_model=options.compiler_model,
        verifier_model=options.verifier_model,
        max_tokens=options.max_tokens,
        protocol=config.protocol,
        batch_enabled=options.batch,
        temperature=options.temperature,
        sample=options.sample,
    )
    if getattr(config.protocol, "defection_rate", 0.0) > 0.0:
        from aeread.exchange_economy_adversarial import AdversarialCounterpartyPolicy

        base: type = AdversarialCounterpartyPolicy
        policy_kwargs.update(
            defection_rate=config.protocol.defection_rate,
            defection_seed=config.protocol.defection_seed,
        )
    else:
        base = ex.LLMCompilerVerifierPolicy
    return _make_manifest_policy_class(base)(**policy_kwargs)


# ===============================================================
# The run itself
# ===============================================================


@dataclasses.dataclass
class RunOutcome:
    run_dir: Path
    result: ex.RunResult
    summary: dict[str, Any]


def _usage_payload(policy: Any) -> dict[str, Any]:
    if hasattr(policy, "usage_summary"):
        return policy.usage_summary()
    return {"calls": 0, "note": "offline scripted policy; no LLM calls"}


def _cost_line(usage: dict[str, Any]) -> str:
    calls = usage.get("calls", 0)
    if not calls:
        return "llm calls: 0 | estimated API cost: $0.000000"
    cost = usage.get("estimated_cost_usd") or 0.0
    unpriced = usage.get("unknown_cost_calls", 0)
    suffix = f" + {unpriced} unpriced fresh call(s)" if unpriced else ""
    return (
        f"llm calls: {calls} ({usage.get('fresh_calls', 0)} fresh, "
        f"{usage.get('cached_calls', 0)} cached, {usage.get('batched_calls', 0)} batched) | "
        f"estimated API cost: ${cost:.6f}{suffix}"
    )


def _load_replay_source(replay_from: str | Path) -> tuple[Path, dict[str, Any]]:
    """Validate a prior run dir and return (dir, its run_meta)."""
    source = Path(replay_from)
    meta_path = source / "run_meta.json"
    if not meta_path.is_file():
        raise RunnerError(f"replay source has no run_meta.json: {source}")
    if not (source / "config_snapshot.json").is_file():
        raise RunnerError(f"replay source has no config_snapshot.json: {source}")
    if not (source / "llm_cache").is_dir():
        raise RunnerError(
            f"replay source has no llm_cache/ (was it a live_frozen run?): {source}"
        )
    return source, json.loads(meta_path.read_text())


def _options_from_meta(meta: dict[str, Any]) -> InferenceOptions:
    models = meta.get("models") or {}
    params = meta.get("params") or {}
    return InferenceOptions(
        model=models.get("agents", InferenceOptions.model),
        compiler_model=models.get("compiler"),
        verifier_model=models.get("verifier"),
        max_tokens=int(params.get("max_tokens", InferenceOptions.max_tokens)),
        temperature=float(params.get("temperature", InferenceOptions.temperature)),
        sample=int(params.get("sample", InferenceOptions.sample)),
        batch=bool(params.get("batch", False)),
    )


def run_v1(
    config_path: Optional[str | Path] = None,
    *,
    mode: str = "offline",
    seed: Optional[int] = None,
    out_root: str | Path = "runs",
    options: Optional[InferenceOptions] = None,
    rounds_override: Optional[int] = None,
    controllers_override: Optional[list[int]] = None,
    replay_from: Optional[str | Path] = None,
    run_id: Optional[str] = None,
    quiet: bool = False,
    strict: bool = False,
    under_test_agent: Optional[Any] = None,
) -> RunOutcome:
    """Execute one run end-to-end and return its self-contained run directory.

    Library entry point used by the CLI, the sweep harness, and tests alike.
    In replay mode the config, seed, models and sampling params are taken from
    the source run's artifacts — a replay reproduces the original run, period.
    With strict=True a funnel-check mismatch raises (after all artifacts are
    written) instead of merely stamping status=manifest_incomplete: a call
    missing from the manifest means the run is not faithfully replayable.
    """
    if mode not in MODES:
        raise RunnerError(f"unknown mode {mode!r}; expected one of {MODES}")

    replay_source: Optional[Path] = None
    replay_source_meta: Optional[dict[str, Any]] = None
    if mode == "replay":
        if replay_from is None:
            raise RunnerError("mode=replay requires replay_from=<prior run dir>")
        replay_source, replay_source_meta = _load_replay_source(replay_from)
        config_path = replay_source / "config_snapshot.json"
        options = _options_from_meta(replay_source_meta)
        seed = None  # the snapshot already carries the effective seed
        rounds_override = controllers_override = None
        current_env = _cache_relevant_env()
        recorded_env = replay_source_meta.get("env") or {}
        drift = {
            k: (recorded_env.get(k), current_env.get(k))
            for k in current_env
            if recorded_env.get(k) != current_env.get(k)
        }
        if drift and not quiet:
            print(f"replay note: env differs from recording (harmless in replay): {drift}")
    elif config_path is None:
        raise RunnerError("config_path is required outside replay mode")

    options = options or InferenceOptions()
    config_path = Path(config_path)
    if not config_path.is_file():
        raise RunnerError(f"config not found: {config_path}")
    config_bytes = config_path.read_bytes()
    config = resolve_config(
        config_path,
        seed=seed,
        rounds_override=rounds_override,
        controllers_override=controllers_override,
    )
    resolved_dict = dataclasses.asdict(config)

    # D9: a `roles` block in the config JSON selects the per-seat composite path.
    # The engine's config loader ignores unknown keys, so we read it from the raw
    # bytes; embedding it in the snapshot makes replay re-derive the seat table.
    raw_config = json.loads(config_bytes.decode("utf-8"))
    roles_block = raw_config.get("roles") if isinstance(raw_config, dict) else None
    role_table: Optional[RoleTable] = None
    if roles_block is not None:
        resolved_dict["roles"] = roles_block
        if mode != "offline":  # offline scripts every seat; roles kept for provenance only
            try:
                role_table = parse_role_table(roles_block, config.num_agents)
            except RoleConfigError as err:
                raise RunnerError(f"invalid roles block in {config_path}: {err}") from err

    if mode == "offline":
        model_label = "offline"
    elif role_table is not None:
        under_test_policy = role_table.group_for("under_test").policy
        model_label = under_test_policy.get("model") or under_test_policy["kind"]
    else:
        model_label = options.model
    run_id = run_id or make_run_id(
        config.name,
        f"{model_label}-replay" if mode == "replay" else model_label,
        config.seed,
    )
    run_dir = Path(out_root) / run_id
    if run_dir.exists():
        raise RunnerError(f"run dir already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    started = time.monotonic()
    meta: dict[str, Any] = {
        "schema_version": RUN_SCHEMA_VERSION,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION if mode != "offline" else None,
        "run_id": run_id,
        "mode": mode,
        "status": "running",
        "created_utc": _utc_now_iso(),
        "config": {
            "path": str(config_path),
            "name": config.name,
            "file_sha256": _sha256_bytes(config_bytes),
            "resolved_sha256": _sha256_bytes(
                json.dumps(resolved_dict, sort_keys=True).encode("utf-8")
            ),
        },
        "seed": config.seed,
        "overrides": {
            "seed": seed,
            "rounds": rounds_override,
            "controllers": controllers_override,
        },
        "models": (
            None
            if mode == "offline"
            # roles-driven runs: per-seat models come from the roles block, not
            # InferenceOptions — reporting the harness defaults here would label
            # every submission run with a model that never ran.
            else {
                "source": "roles",
                "seats": [
                    {"seat": s["seat"], "kind": s["kind"], "model": s["model"]}
                    for s in role_table.summary()["seats"]
                ],
            }
            if role_table is not None
            else {
                "agents": options.model,
                "compiler": options.compiler_model or options.model,
                "verifier": options.verifier_model or options.compiler_model or options.model,
            }
        ),
        "params": {
            "max_tokens": options.max_tokens,
            "temperature": options.temperature,
            "sample": options.sample,
            "batch": options.batch,
        },
        "replay_from": str(replay_from) if replay_from else None,
        "strict": strict,
        "roles": role_table.summary() if role_table is not None else None,
        "git": _git_info(),
        "python": sys.version,
        "argv": list(sys.argv),
        "env": _cache_relevant_env(),
    }
    _write_json(run_dir / "run_meta.json", meta)
    _write_json(run_dir / "config_snapshot.json", resolved_dict)

    recorder: Optional[ManifestRecorder] = None
    observed_calls = [0]
    hooks_installed = False
    # Everything from world construction onward runs under one try: any failure
    # writes status=failed, and the finally ALWAYS uninstalls the module-global
    # llm_agent hooks (a leaked observer/replay dir would corrupt later runs in
    # the same process, e.g. subsequent sweep cells).
    try:
        world = ex.make_world_from_config(config)
        policy = build_policy(
            mode, config, options, role_table=role_table, under_test_agent=under_test_agent
        )
        if mode != "offline":
            from aeread import llm_agent

            if not quiet:
                print(
                    f"[{mode}] {config.name} seed={config.seed} rounds={config.rounds} "
                    f"model={model_label} -> {run_dir}",
                    flush=True,
                )
            recorder = ManifestRecorder(
                run_dir,
                total_rounds=config.rounds,
                label=mode,
                verbose=not quiet,
            )
            # composite: every recording-capable seat shares the run's recorder
            for sub_policy in getattr(policy, "sub_policies", (policy,)):
                if hasattr(sub_policy, "v1_recorder"):
                    sub_policy.v1_recorder = recorder
            previous_observer = llm_agent.set_call_observer(
                lambda record: observed_calls.__setitem__(0, observed_calls[0] + 1)
            )
            previous_replay_dir = llm_agent.set_replay_dir(
                replay_source / "llm_cache" if mode == "replay" else None
            )
            hooks_installed = True
        result = ex.run_exchange_transcript(
            world,
            rounds=config.rounds,
            controllers=config.controllers,
            policy=policy,
            protocol=config.protocol,
            trace_jsonl_path=run_dir / "trace.jsonl",
        )
    except BaseException as err:
        meta["status"] = "failed"
        meta["error"] = f"{type(err).__name__}: {err}"
        meta["completed_utc"] = _utc_now_iso()
        meta["duration_seconds"] = round(time.monotonic() - started, 3)
        _write_json(run_dir / "run_meta.json", meta)
        raise
    finally:
        if hooks_installed:
            llm_agent.set_call_observer(previous_observer)
            llm_agent.set_replay_dir(previous_replay_dir)

    usage = _usage_payload(policy)
    funnel_check: Optional[dict[str, Any]] = None
    if recorder is not None:
        policy_records = len(getattr(policy, "call_records", []) or [])
        funnel_check = {
            "observed_calls": observed_calls[0],
            "policy_call_records": policy_records,
            "manifest_rows": recorder.funnel_rows,
            "submitted_rows": recorder.rows - recorder.funnel_rows,
            "ok": observed_calls[0] == policy_records == recorder.funnel_rows,
        }
        if not funnel_check["ok"] and not quiet:
            print(
                f"WARNING: funnel check mismatch {funnel_check} — an LLM call "
                "bypassed the policy chokepoint and is missing from the manifest"
            )

    # D9 pin enforcement: a declared pin_resolved_model is an assertion about
    # panel integrity — drift always fails the run (independent of strict mode).
    pin_check: Optional[dict[str, Any]] = None
    if role_table is not None and recorder is not None:
        pin_check = check_pins(role_table, recorder)
        if pin_check is not None and not pin_check["ok"] and not quiet:
            print(f"WARNING: panel drift detected: {pin_check}")

    summary = ex.build_run_summary_payload(
        result,
        config=config,
        usage=usage,
        model=model_label,
    )
    summary["run_id"] = run_id
    summary["mode"] = mode
    summary["cost_line"] = _cost_line(usage)
    summary["manifest_totals"] = recorder.totals() if recorder is not None else None
    _write_json(run_dir / "summary.json", summary)

    # a funnel mismatch means a call is missing from the manifest, i.e. the run
    # is NOT faithfully replayable — never label that "complete"; a violated
    # panel pin outranks both (the exam itself changed under the candidate)
    meta["status"] = (
        "complete" if funnel_check is None or funnel_check["ok"] else "manifest_incomplete"
    )
    if pin_check is not None and not pin_check["ok"]:
        meta["status"] = "panel_drift"
    meta["completed_utc"] = _utc_now_iso()
    meta["duration_seconds"] = round(time.monotonic() - started, 3)
    meta["usage"] = usage
    meta["funnel_check"] = funnel_check
    meta["pin_check"] = pin_check
    meta["manifest_totals"] = recorder.totals() if recorder is not None else None
    _write_json(run_dir / "run_meta.json", meta)

    if pin_check is not None and not pin_check["ok"]:
        raise RunnerError(
            f"panel drift: a pinned counterpart model resolved to a different version "
            f"({pin_check}); run {run_id} is not comparable to runs recorded under the pin"
        )
    if strict and funnel_check is not None and not funnel_check["ok"]:
        # artifacts are all on disk (status=manifest_incomplete) — now fail loudly
        raise RunnerError(
            f"strict mode: funnel check failed {funnel_check} — an LLM call bypassed "
            f"the policy chokepoint; run {run_id} is not faithfully replayable"
        )

    if not quiet:
        print(f"run dir: {run_dir}")
        print(
            f"config={config.name} seed={config.seed} mode={mode} rounds={config.rounds} | "
            f"welfare {result.initial_welfare:.3f} -> {result.final_welfare:.3f} "
            f"(optimum {result.optimum_welfare:.3f}, ratio {result.final_welfare_ratio:.3f}) | "
            f"applied {result.applied_mechanisms}/{len(result.history)}"
        )
        print(summary["cost_line"])
    return RunOutcome(run_dir=run_dir, result=result, summary=summary)


# ===============================================================
# CLI
# ===============================================================


def _parse_int_list(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--config",
        default=None,
        help="experiment config JSON (required except with --replay-from, which "
        "re-uses the source run's config snapshot)",
    )
    ap.add_argument("--seed", type=int, default=None, help="override the config's seed")
    ap.add_argument("--mode", choices=MODES, default="offline")
    ap.add_argument("--out", default="runs", help="parent directory for run dirs")
    ap.add_argument("--run-id", default=None, help="explicit run id (default: derived + UTC stamp)")
    ap.add_argument("--model", default=os.environ.get("POC_MODEL", "google/gemini-3.5-flash"))
    ap.add_argument("--compiler-model", default=os.environ.get("POC_COMPILER_MODEL"))
    ap.add_argument("--verifier-model", default=os.environ.get("POC_VERIFIER_MODEL"))
    ap.add_argument("--max-tokens", type=int, default=int(os.environ.get("POC_MT", "1200")))
    ap.add_argument("--temperature", type=float, default=float(os.environ.get("POC_TEMPERATURE", "0.0")))
    ap.add_argument("--sample", type=int, default=int(os.environ.get("POC_SAMPLE", "0")))
    ap.add_argument("--batch", action="store_true", help="use provider batch API where available")
    ap.add_argument("--rounds-override", type=int, default=None)
    ap.add_argument("--controllers-override", default=None, help="comma-separated controller ids")
    ap.add_argument("--replay-from", default=None, help="prior run dir to replay (mode=replay)")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="raise on a funnel-check mismatch instead of only stamping manifest_incomplete",
    )
    args = ap.parse_args(argv)

    options = InferenceOptions(
        model=args.model,
        compiler_model=args.compiler_model,
        verifier_model=args.verifier_model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        sample=args.sample,
        batch=args.batch,
    )
    run_v1(
        args.config,
        mode=args.mode,
        seed=args.seed,
        out_root=args.out,
        options=options,
        rounds_override=args.rounds_override,
        controllers_override=(
            _parse_int_list(args.controllers_override) if args.controllers_override else None
        ),
        replay_from=args.replay_from,
        run_id=args.run_id,
        strict=args.strict,
    )


if __name__ == "__main__":
    main()
