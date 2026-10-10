"""One agreement negotiation between two CLI subjects: Codex on one side, Claude Code on the other.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_cli.py freeze runs/<campaign> --pairing codex_integrator__claude_client --worlds 1
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_cli.py run    runs/<campaign>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_cli.py dry-run runs/<campaign>-dry

Both seats are players (the agreement case's first slice, ``aeread_families.datacenter_development.agreement``).
Each move is one CLI subprocess with no tools, the seat's prompt as the system prompt and the action
schema enforced by the CLI, at reasoning effort low. A CLI takes no seed and no temperature, so the
profile seals both as unavailable. Both run on subscription logins: cost is the list price of the
tokens. Two scripted pairs are controls that check the grader: a full-information pair that signs the
best agreement at once (loses nothing), and a pair that signs the integrator's draft as it stands.

Everything that can end a run is in the frozen plan. A failed cell is typed missingness and is not rerun.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, RunPlan, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import finalize_family_execution, finalize_family_failure, replay_family_receipt
from aeread.shared_runner.task.execution import CanonicalResponse, ClaudeCodePrintClient, ProviderRequest, ProviderResult, TokenPricing, execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import risk_allocation_campaign as oc
from aeread_families.datacenter_development import risk_allocation_contracts as rc
from aeread_families.datacenter_development.agreement_environment import (
    PLUGIN_ID, STRICT_ACTION_SCHEMA, AgreementPlugin, agreement_family_manifest, parse_move,
)
from aeread_families.datacenter_development.agreement_measurement import (
    REFERENCE_IMPLEMENTATION_ID, REFERENCE_SOURCES, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID,
    VERSION as MEASUREMENT_VERSION, combined_sha256, primary_measurement_leaf,
)
from aeread_families.datacenter_development.risk_allocation_environment import _thaw

import codex_exec_client as codex

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FAMILY_DIR = REPOSITORY_ROOT / "src/aeread_families/datacenter_development"
CAMPAIGN_ID = "datacenter_agreement_cli_pair_dev_v1"
PACK = "agreement_dev_v1"
RUNTIME_ID = oc.RUNTIME_ID
SCRIPTED = "scripted_"
#: List prices, used as the sealed price of a call; nothing is charged per call on a subscription login.
SUBJECTS: dict[str, dict[str, Any]] = {
    "claude_opus55": {"provider": "claude_code", "model": "claude-opus-5-5",
                      "pricing": TokenPricing(4.0, 0.20, 20.0, "anthropic_list_2026-09-22_claude-opus-5-5")},
    "codex_sol61": {"provider": codex.PROVIDER, "model": "gpt-6.1-sol",
                    "pricing": TokenPricing(2.0, 0.10, 10.0, "openai_list_2026-10-04_gpt-6.1-sol")},
}
# integrator subject, client subject
PAIRINGS: dict[str, tuple[str, str]] = {
    "codex_integrator__claude_client": ("codex_sol61", "claude_opus55"),
    "claude_integrator__codex_client": ("claude_opus55", "codex_sol61"),
    "oracle_integrator__oracle_client": ("scripted_oracle", "scripted_oracle"),
    "draft_integrator__draft_client": ("scripted_draft", "scripted_draft"),
}
CONTROLS = {"reasoning_effort": "low", "timeout_seconds": 300.0, "max_action_attempts": 1, "replicates": 1,
            "max_cost_usd_per_seat": 1.0, "max_cost_usd_total": 6.0, "max_parallel_cells": 2}
CLAIM_STATUS = "development probe: one play a world between two CLI subjects; no winner, no ranking"
SOURCES = (
    "src/aeread_families/datacenter_development/risk_allocation.py",
    "src/aeread_families/datacenter_development/risk_allocation_contracts.py",
    "src/aeread_families/datacenter_development/agreement.py",
    "src/aeread_families/datacenter_development/agreement_environment.py",
    "src/aeread_families/datacenter_development/agreement_measurement.py",
    "src/aeread_families/datacenter_development/agreement_pack.py",
    "tools/cli_subjects/agreement_cli.py",
    "tools/cli_subjects/codex_exec_client.py",
    "src/aeread/shared_runner/task/execution.py",
    "src/aeread/shared_runner/task/evaluation.py",
)


def system_prompt(seat: str) -> str:
    them = "client" if seat == "integrator" else "integrator"
    clauses = ", ".join(f'"{k}": <{" | ".join(str(v).lower() if isinstance(v, bool) else str(v) for v in rc.LEVELS[k])} | null>' for k in ag.TERMS)
    return (
        f"You are negotiating a services agreement on behalf of the {seat}; the {them} is another negotiator acting for itself. Each turn you "
        "receive a JSON object whose observation holds your brief (observation.brief: the facts, what each clause decides, your own costs, what "
        "you know about the other side, the rules of the negotiation and your objective), the agreement as it stands clause by clause "
        "(observation.agreement: each clause's current position and text, the positions it can take, and the latest tracked change with who made "
        "it and what it replaced), the price on the table and whose it is (observation.on_the_table), every move so far with its changes, price "
        "and note (observation.history), and the actions allowed now. Reply with exactly one JSON object and nothing else:\n"
        '{"action": "redline" | "sign" | "walk", "clauses": {' + clauses + '} or null, "price": <all-in price in $ thousands> or null, '
        '"note": "<one or two sentences the other side will read>" or null}\n'
        "In a redline, give a position for each clause you change and null for each clause you leave as it stands, and state the all-in price at "
        "which you would sign the agreement as you leave it. To sign the version the other side put on the table at its price, or to walk, set "
        "clauses and price to null."
    )


def prompt_id(seat: str) -> str:
    return f"datacenter_agreement_{seat}_prompt_v1"


@dataclass
class Setup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: dict[str, str]
    pricing: dict[str, TokenPricing]
    harnesses: dict[str, Any]
    providers: tuple[str, ...]


def cases(worlds: Sequence[str] | None = None) -> list[CaseManifest]:
    _, raw = ap.load(PACK)
    wanted = None if worlds is None else set(worlds)
    return [CaseManifest.from_dict(c) for c in sorted(raw.values(), key=lambda c: c["case_id"])
            if wanted is None or c["case_id"].rsplit(".", 1)[-1] in wanted]


def _profile(pairing: str, seat: str, subject: str, runtimes: Mapping[str, Mapping[str, str]]) -> tuple[dict[str, Any], TokenPricing]:
    pid, prompt = prompt_id(seat), system_prompt(seat)
    if subject.startswith(SCRIPTED):
        policy = subject[len(SCRIPTED):]
        pricing = TokenPricing(0.0, 0.0, 0.0, "scripted_policy_zero_cost_v1")
        model = {"provider": "fake", "model": f"agreement-{policy}-{seat}", "revision": f"agreement_{policy}_v1", "base_url": None}
        config: dict[str, Any] = {"pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": STRICT_ACTION_SCHEMA}
        reasoning = {"condition_id": "reasoning_unspecified_v1", "effort": None, "token_budget": None, "rationale_visibility": "hidden"}
        sampling = {"temperature": 0.0, "max_output_tokens": 1000, "seed": None, "top_p": None}
        budgets = {"max_logical_actions": ag.MOVES, "timeout_seconds": 60.0, "max_cost_usd": 0.0}
    else:
        spec = SUBJECTS[subject]
        pricing = spec["pricing"]
        model = {"provider": spec["provider"], "model": spec["model"], "revision": spec["model"], "base_url": None}
        config = {"pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": STRICT_ACTION_SCHEMA,
                  "provider_runtime": dict(runtimes[spec["provider"]]),
                  "sampling_controls": {"temperature": "unavailable", "max_output_tokens": "provider_model_default"}}
        effort = CONTROLS["reasoning_effort"]
        reasoning = {"condition_id": f"reasoning_{effort}_v1", "effort": effort, "token_budget": None, "rationale_visibility": "hidden"}
        sampling = {"temperature": 0.0, "max_output_tokens": 32_000, "seed": None, "top_p": None}
        budgets = {"max_logical_actions": ag.MOVES, "timeout_seconds": CONTROLS["timeout_seconds"], "max_cost_usd": CONTROLS["max_cost_usd_per_seat"]}
    profile = {
        "spec_version": AgentProfile.SPEC_VERSION, "profile_id": f"datacenter_agreement_{pairing}_{seat}_v1", "model": model,
        "harness": {"id": "minimal_chat", "version": "1.0", "config": config},
        "prompt": {"prompt_id": pid, "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()},
        "runtime": {"kind": "python", "implementation": RUNTIME_ID, "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"}, "reasoning": reasoning, "sampling": sampling, "budgets": budgets,
        "retry_policy": {"max_action_attempts": CONTROLS["max_action_attempts"], "retryable_conditions": [], "session_mode": "restart", "sdk_retries": 0},
    }
    return profile, pricing


def build_setup(pairing: str, case_list: Sequence[CaseManifest], runtimes: Mapping[str, Mapping[str, str]]) -> Setup:
    family = agreement_family_manifest()
    integrator_subject, client_subject = PAIRINGS[pairing]
    scripted = integrator_subject.startswith(SCRIPTED)
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": f"agreement_{pairing}_sample_v1",
        "estimand": "joint_value_lost_on_a_development_pack", "target": "negotiating_an_agreement_clause_by_clause",
        "selection": "generated_admitted_cells", "seeds": [oc.SEED], "replicates": CONTROLS["replicates"], "cluster_level": "agreement_world",
        "cluster_id_fields": ["world_seed"], "paired_fields": [], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({
        "spec_version": EvaluationBlock.SPEC_VERSION, "block_id": f"agreement_{pairing}_block",
        "kind": "reference" if scripted else "cross_play", "subject_seats": list(ag.SEATS), "controlled_profiles": {}, "repetitions": 1,
        "seed_policy": "fixed",
    })
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "agreement_analysis_v1", "estimands": ["joint_value_lost"],
        "group_by": ["family_id"], "missingness": "report_separately", "resampling_unit": "agreement_world",
        "uncertainty": "world_cluster_bootstrap_95", "multiplicity": "none", "sensitivity": [], "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": f"agreement_{PACK}_{len(case_list)}_worlds", "version": "0.1.0",
        "family_ids": [family.family.id], "case_ids": [c.case_id for c in case_list], "sampling_plan_id": sampling.sampling_plan_id,
        "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id,
    })
    profiles, pricing = {}, {}
    for seat, subject in (("integrator", integrator_subject), ("client", client_subject)):
        p, pr = _profile(pairing, seat, subject, runtimes)
        profiles[seat] = AgentProfile.from_dict(p)
        pricing[p["model"]["model"]] = pr
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"datacenter_agreement_{pairing}_run_v1", "suite_id": suite.suite_id,
        "evaluation_block_ids": [block.block_id], "agent_profile_ids": sorted(p.profile_id for p in profiles.values()),
        "seat_assignments": {seat: p.profile_id for seat, p in profiles.items()},
        "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None,
    })
    registry = PluginRegistry()
    registry.register_trusted(family, AgreementPlugin())
    harnesses = default_harnesses()
    harness_registry = HarnessRegistry()
    for h in harnesses.values():
        harness_registry.register(h)
    execution_path = Path(execution_module.__file__)
    pins = (
        oc._pin(PLUGIN_ID, "family_plugin", FAMILY_DIR / "agreement_environment.py"),
        oc._pin(SCORER_IMPLEMENTATION_ID, "scorer", FAMILY_DIR / "agreement_measurement.py", version=MEASUREMENT_VERSION),
        oc._pin(VALIDITY_IMPLEMENTATION_ID, "reference", FAMILY_DIR / "agreement_measurement.py", version=MEASUREMENT_VERSION),
        ImplementationPin.from_dict({"component_id": REFERENCE_IMPLEMENTATION_ID, "kind": "reference", "version": MEASUREMENT_VERSION,
                                     "sha256": combined_sha256(REFERENCE_SOURCES)}),
        oc._pin("minimal_chat", "harness", execution_path, version="1.0"),
        oc._pin(RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
    )
    providers = tuple(sorted({p.model.provider for p in profiles.values()}))
    plan = resolve_run_plan(
        families=(family,), cases=tuple(case_list), suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis,
        agent_profiles=tuple(profiles.values()), run_spec=run_spec, registry=registry, implementation_pins=pins, harness_registry=harness_registry,
        provider_capabilities={prov: ProviderCapabilities(
            native_tools=False, structured_output=prov != "fake", seed=False, system_prompt=True, reasoning_budget=prov != "fake",
            reasoning_token_report=prov == codex.PROVIDER, max_context_tokens=None) for prov in providers},
    )
    return Setup(plan, registry, {prompt_id(s): system_prompt(s) for s in ag.SEATS}, pricing, harnesses, providers)


class PairClient:
    """Both seats of a scripted pair: it rebuilds the negotiation from its own earlier replies and answers for the seat to move."""

    def __init__(self, payload: Mapping[str, Any], policy: str) -> None:
        self.payload = AgreementPlugin().validate_payload(payload)
        self.policy = ag.POLICIES[policy]
        self.replies: list[str] = []

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        cw, it = rc.world_from(self.payload)
        state = ag.initial_state(cw)
        for text in self.replies:
            state = ag.apply(state, parse_move(CanonicalResponse(text, "stop", False, False, (), (), 0, 0, 0, 0.0)).action, cw)
        text = json.dumps(self.policy(state, cw, it))
        self.replies.append(text)
        return ProviderResult(response_id=f"scripted_{len(self.replies)}", requested_model=request.model, resolved_model=request.revision or request.model,
                              output_text=text, finish_reason="stop", input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0,
                              raw_response={"scripted": True, "output_text": text})


async def _claude_runner(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    """The kernel's runner, with the CLI's own refusal reason carried to where the adapter reads it (RN-T-06)."""
    returncode, stdout, stderr = await execution_module._run_subprocess(arguments, standard_input)
    if returncode != 0 and not stderr.strip():
        try:
            payload = json.loads(stdout)
            stderr = f"{payload.get('result')} (api_error_status {payload.get('api_error_status')})".encode("utf-8")
        except (ValueError, AttributeError):
            stderr = stdout[-400:]
    return returncode, stdout, stderr


async def discover(providers: Sequence[str]) -> dict[str, Any]:
    clients: dict[str, Any] = {}
    if "claude_code" in providers:
        found = await ClaudeCodePrintClient.discover()
        clients["claude_code"] = ClaudeCodePrintClient(executable=Path(shutil.which("claude")).resolve(), runtime_version=found.runtime_version,
                                                       runtime_sha256=found.runtime_sha256, command_runner=_claude_runner)
    if codex.PROVIDER in providers:
        clients[codex.PROVIDER] = await codex.CodexExecClient.discover()
    return clients


def _providers_of(pairing: str) -> list[str]:
    return sorted({SUBJECTS[s]["provider"] for s in PAIRINGS[pairing] if not s.startswith(SCRIPTED)})


def _digest(rel: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / rel).read_bytes()).hexdigest()


def freeze(directory: Path, pairings: Sequence[str], worlds: Sequence[str], campaign_id: str = CAMPAIGN_ID) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    clients = asyncio.run(discover(sorted({p for pairing in pairings for p in _providers_of(pairing)})))
    runtimes = {name: dict(client.runtime_metadata) for name, client in clients.items()}
    case_list = cases(worlds)
    plans = []
    for pairing in pairings:
        setup = build_setup(pairing, case_list, runtimes)
        plans.append({"pairing": pairing, "integrator": PAIRINGS[pairing][0], "client": PAIRINGS[pairing][1], "run_plan_id": setup.plan.run_plan_id,
                      "cells": [{"cell_id": c.cell_id, "case_id": c.case_id, "replicate_index": c.replicate_index} for c in setup.plan.cells]})
    manifest, _ = ap.load(PACK)
    plan = {
        "campaign_id": campaign_id, "claim_status": CLAIM_STATUS, "pack": PACK, "worlds": list(worlds), "controls": CONTROLS,
        "pairings": {p: list(PAIRINGS[p]) for p in pairings}, "provider_runtimes": runtimes,
        "subjects": {k: {"provider": v["provider"], "model": v["model"], "pricing_id": v["pricing"].pricing_id} for k, v in SUBJECTS.items()},
        "billing": "subscription logins; cost is the list price of the tokens, not a charge",
        "tools": "none: Claude Code with --tools \"\"; Codex with its acting features disabled, and a call that uses a tool is refused",
        "system_prompts": {prompt_id(s): system_prompt(s) for s in ag.SEATS},
        "pack_manifest_sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "declared_analysis": {
            "primary": "per pairing, joint value lost against the best agreement for both true types; with its split into allocation, no deal and delay",
            "also": "each side's surplus and share; agreements signed below an outside option; redlines that move only the price; the joint value each side's clause changes added or destroyed",
            "controls": "the oracle pair must lose zero on every world; the draft pair shows what signing the integrator's paper costs",
            "missingness": "an invalid or failed negotiation is missing for its pairing, by cause and by the seat that made it invalid; never rerun",
            "claim": "descriptive: one play a world, no winner, no ranking",
        },
        "sources": {rel: _digest(rel) for rel in SOURCES}, "plans": plans,
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    (directory / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
    return plan


async def _run_cell(directory: Path, entry: Mapping[str, Any], setup: Setup, cell: Any, clients: Mapping[str, Any], spend: oc.Spend,
                    sem: asyncio.Semaphore) -> dict[str, Any]:
    key = f"{entry['pairing']}__{cell.case_id.rsplit('.', 1)[-1]}__r{cell.replicate_index}"
    record_path = directory / "cells" / f"{key}.json"
    if record_path.exists():
        return json.loads(record_path.read_text())
    async with sem:
        if spend.exhausted:
            return {"cell_key": key, "status": "not_attempted_budget"}
        evidence_root = directory / "evidence" / key
        payload = next(c.payload for c in setup.plan.cases if c.case_id == cell.case_id)
        providers: dict[str, Any] = {name: codex.LoggedClient(client, directory / "cli_calls.jsonl", subject=name) for name, client in clients.items()
                                     if name in setup.providers}
        if "fake" in setup.providers:
            providers["fake"] = PairClient(payload, entry["integrator"][len(SCRIPTED):])
        record: dict[str, Any] = {"cell_key": key, "pairing": entry["pairing"], "integrator": entry["integrator"], "client": entry["client"],
                                  "case_id": cell.case_id, "cell_id": cell.cell_id, "replicate_index": cell.replicate_index,
                                  "run_plan_id": setup.plan.run_plan_id}
        try:
            execution = await execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence_root,
                                                prompt_sources=setup.prompt_sources, providers=providers, pricing=setup.pricing, harnesses=setup.harnesses)
            receipt = finalize_family_execution(setup=setup, execution=execution)
            verify_evaluation_receipt(receipt)
            replayed = replay_family_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("replay produced a different receipt")
            cost = float(execution.total_cost_usd or 0.0)
            spend.add(cost)
            outcome = _thaw(execution.episode_result.outcome)
            record.update(status=receipt.status, receipt_sha256=receipt.receipt_sha256, episode_attempt_id=execution.episode_attempt_id, cost_usd=cost,
                          termination=outcome.get("termination"), grade=outcome.get("grade"), signed=outcome.get("signed"),
                          evidence_dir=str(execution.evidence.root.relative_to(directory)))
        except Exception as error:  # noqa: BLE001 - a failed cell is sealed as a typed exclusion, never rerun
            try:
                receipt = finalize_family_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error,
                                                  leaf_builder=primary_measurement_leaf)
                record.update(status=receipt.status, receipt_sha256=receipt.receipt_sha256, error=f"{type(error).__name__}: {str(error)[:400]}")
            except Exception as sealing_error:  # noqa: BLE001
                record.update(status="unsealed_failure", error=f"{type(error).__name__}: {str(error)[:400]}",
                              sealing_error=f"{type(sealing_error).__name__}: {str(sealing_error)[:300]}")
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=1, default=str))
        g = record.get("grade") or {}
        print(f"{key:60} {record['status']:22} {record.get('termination') or ''} lost {g.get('joint_value_lost', '')}", flush=True)
        return record


async def run(directory: Path) -> None:
    plan = json.loads((directory / "campaign_plan.json").read_text())
    if any(_digest(rel) != d for rel, d in plan["sources"].items()):
        raise SystemExit("sources changed since the plan was frozen; freeze a new campaign directory")
    clients = await discover(sorted({p for pairing in plan["pairings"] for p in _providers_of(pairing)}))
    runtimes = {name: dict(client.runtime_metadata) for name, client in clients.items()}
    if runtimes != plan["provider_runtimes"]:
        raise SystemExit("a CLI's version or the adapter changed since the plan was frozen; freeze a new campaign directory")
    spend = oc.Spend(plan["controls"]["max_cost_usd_total"])
    case_list = cases(plan["worlds"])
    sem = asyncio.Semaphore(plan["controls"]["max_parallel_cells"])
    jobs = []
    for entry in plan["plans"]:
        setup = build_setup(entry["pairing"], case_list, runtimes)
        if setup.plan.run_plan_id != entry["run_plan_id"]:
            raise SystemExit(f"run plan {entry['run_plan_id']} no longer resolves identically; freeze a new campaign")
        jobs += [_run_cell(directory, entry, setup, cell, clients, spend, sem) for cell in setup.plan.cells]
    await asyncio.gather(*jobs)
    print(f"list-price cost ${spend.spent:.4f}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["freeze", "run", "dry-run"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--pairing", action="append", choices=sorted(PAIRINGS))
    parser.add_argument("--worlds", type=int, default=1, help="how many worlds of the pack, in case-id order")
    parser.add_argument("--world", action="append", help="a world's case code; overrides --worlds")
    parser.add_argument("--campaign", default=CAMPAIGN_ID, help="campaign identity; a different pairing or world set is a different campaign")
    args = parser.parse_args(argv)
    if args.command in ("freeze", "dry-run") and not args.directory.exists():
        codes = args.world or [c.case_id.rsplit(".", 1)[-1] for c in cases()][: args.worlds]
        scripted = [p for p in PAIRINGS if PAIRINGS[p][0].startswith(SCRIPTED)]
        pairings = scripted if args.command == "dry-run" else (args.pairing or ["codex_integrator__claude_client"])
        plan = freeze(args.directory, pairings, codes, args.campaign + ("_scripted_dry_run" if args.command == "dry-run" else ""))
        print(f"froze {sum(len(p['cells']) for p in plan['plans'])} cells in {len(plan['plans'])} plans: {plan['plan_sha256'][:12]}")
    if args.command in ("run", "dry-run"):
        asyncio.run(run(args.directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
