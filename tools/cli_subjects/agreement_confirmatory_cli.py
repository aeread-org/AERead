"""The agreement case's confirmatory campaigns on the admitted pack: the variance pilot and arms H, F and A.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_cli.py dry-run runs/<dir>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_cli.py freeze  runs/<dir> --arm pilot
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_cli.py freeze  runs/<dir> --arm H --sizing-record FILE
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_cli.py run     runs/<dir>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_cli.py verify  runs/<dir>

The plan is ``docs/families/datacenter/agreement_confirmatory_plan.md`` ("Before the confirmatory runs"). This module
wraps :mod:`agreement_cli`, which is hashed into the 18 sealed development plans and accepts only
``agreement_pack.PACKS``, so neither is edited. What it adds:

- the admitted pack ``agreement_admitted_v1`` and its variance pilot ``agreement_admitted_pilot_v1``
  (``agreement_pack.load`` reads both);
- the scripted style ``drawn_public_v1``: the negotiator in the style drawn from the public world and the seat
  (``agreement_admitted_pack.public_negotiator_move``), never from a hidden type (DC-D-32);
- the arms of the plan, each a frozen campaign with its pairings, plays per world, parallelism and two ceilings frozen
  at twice the plan's estimate: list price and wall time. A negotiation not started before either is reached is typed
  ``not_attempted_budget`` or ``not_attempted_wall_time``;
- a halt rule (DC-T-08): after five consecutive operational failures (a negotiation that ended in an exception, such
  as a CLI or service error or a timeout) no further negotiation starts, and each one left is typed
  ``not_attempted_halt``. A failed negotiation is typed missingness and is never rerun;
- the sources it hashes: :data:`agreement_cli.SOURCES`, ``agreement_admitted_pack.py`` and this file;
- ``verify``: every sealed receipt replayed offline from its evidence, with no provider call.

Each move is one CLI subprocess with no tools at reasoning effort low, as in every development run. Both CLIs run on
subscription logins; the cost is the list price of the tokens, not a charge.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import agreement_cli as base
import codex_exec_client as codex
from aeread.shared_runner.analysis.research import _deserialize_receipt
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import finalize_family_execution, finalize_family_failure, replay_family_receipt
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.receipts import read_evaluation_receipt, verify_evaluation_receipt
from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_pack as aap
from aeread_families.datacenter_development import agreement_negotiator as an
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import risk_allocation_campaign as oc
from aeread_families.datacenter_development import risk_allocation_contracts as rc
from aeread_families.datacenter_development.agreement_environment import PLUGIN_ID, AgreementPlugin, agreement_family_manifest
from aeread_families.datacenter_development.agreement_measurement import (
    REFERENCE_IMPLEMENTATION_ID, REFERENCE_SOURCES, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID,
    VERSION as MEASUREMENT_VERSION, combined_sha256, primary_measurement_leaf,
)
from aeread_families.datacenter_development.risk_allocation_environment import _thaw

import aeread.shared_runner.task.execution as execution_module

REPOSITORY_ROOT = base.REPOSITORY_ROOT
PLAN_DOC = "docs/families/datacenter/agreement_confirmatory_plan.md"
PLAN_COMMIT = "ca9d5cac6c601466e062b928c6fb565385b497d1"
ADMITTED_PACK_SHA256 = "265770bd86576c0577035a9f3e2943d1a058e06b7845743474737a8ec3ed700b"
PUBLIC = "drawn_public_v1"
SCRIPTED_PUBLIC = f"{base.SCRIPTED}negotiator_{PUBLIC}"
ADVERSARIAL = ("overreach", "price_only", "collapse")
MODELS = {"codex_sol61": "codex", "claude_opus55": "claude"}
HALT_AFTER = 5
#: Deal worlds the admitted pack gives P1 and P2 after the plan's 7% attrition (45 deal worlds, "Sizing").
DEAL_WORLDS_AVAILABLE = 42
SOURCES = (*base.SOURCES, "src/aeread_families/datacenter_development/agreement_admitted_pack.py",
           "tools/cli_subjects/agreement_confirmatory_cli.py")

for _subject, _name in MODELS.items():
    base.PAIRINGS[f"negotiator_{PUBLIC}_integrator__{_name}_client"] = (SCRIPTED_PUBLIC, _subject)
    base.PAIRINGS[f"{_name}_integrator__negotiator_{PUBLIC}_client"] = (_subject, SCRIPTED_PUBLIC)

_base_policy = base.scripted_policy


def scripted_policy(name: str):
    """``agreement_cli.scripted_policy``, plus the publicly drawn style. The base module's scripted seats look the rule up
    by this name, so the base's own lookup is replaced here rather than edited."""
    if name == f"negotiator_{PUBLIC}":
        return aap.public_negotiator_move
    return _base_policy(name)


base.scripted_policy = scripted_policy


def _model_pairings(counterpart: str) -> tuple[str, ...]:
    """Each model in each seat against one scripted counterpart: the model as integrator first, codex before claude."""
    return (*(f"{n}_integrator__negotiator_{counterpart}_client" for n in ("codex", "claude")),
            *(f"negotiator_{counterpart}_integrator__{n}_client" for n in ("codex", "claude")))


H_PAIRINGS = ("codex_integrator__claude_client", "claude_integrator__codex_client")
F_PAIRINGS = _model_pairings(PUBLIC)
A_PAIRINGS = tuple(p for style in ADVERSARIAL for p in _model_pairings(style))


@dataclass(frozen=True)
class Arm:
    """One campaign of the plan. ``list_usd`` and ``wall_minutes`` are the plan's estimates ("Cost and wall time");
    the frozen ceilings are twice each."""
    name: str
    campaign_id: str
    pack: str
    pairings: tuple[str, ...]
    plays: int
    parallel: int
    list_usd: float
    wall_minutes: float
    role: str

    @property
    def negotiations(self) -> int:
        return len(self.pairings) * self.plays * len(ap.load(self.pack)[0]["worlds"])


ARMS: dict[str, Arm] = {a.name: a for a in (
    Arm("dry", "datacenter_agreement_confirm_scripted_dry_run_v1", aap.ADMITTED.pack,
        ("oracle_integrator__oracle_client", "draft_integrator__draft_client"), 1, 8, 0.5, 10.0,
        "the driver's dry run: the full-information pair and the draft pair on every admitted world, no model"),
    Arm("pilot", "datacenter_agreement_confirm_pilot_v1", aap.PILOT.pack, F_PAIRINGS, 2, 4, 4.40, 18.0,
        "the variance pilot: arm F on the pilot pack, each world twice; development evidence, nothing in it is a result"),
    Arm("H", "datacenter_agreement_confirm_head_to_head_v1", aap.ADMITTED.pack, H_PAIRINGS, 1, 3, 12.90, 56.0,
        "arm H, primary: the two models head to head in both seat orders (P1, P3)"),
    Arm("F", "datacenter_agreement_confirm_firm_population_v1", aap.ADMITTED.pack, F_PAIRINGS, 1, 4, 11.00, 44.0,
        "arm F, primary: each model in each seat against the publicly drawn firm population (P2)"),
    Arm("A", "datacenter_agreement_confirm_adversarial_v1", aap.ADMITTED.pack, A_PAIRINGS, 1, 6, 34.60, 102.0,
        "arm A, secondary: each model in each seat against the overreach, price_only and collapse styles; no claim"),
)}


def controls_for(arm: Arm) -> dict[str, Any]:
    """The development controls (``agreement_cli.CONTROLS``) with this arm's plays, parallelism and ceilings."""
    out = dict(base.CONTROLS)
    out.update(replicates=arm.plays, max_parallel_cells=arm.parallel, prompt_variant="v1",
               max_cost_usd_total=round(2 * arm.list_usd, 2), max_wall_minutes=round(2 * arm.wall_minutes, 1),
               halt_after_consecutive_operational_failures=HALT_AFTER)
    return out


def _use(arm_or_plan: Arm | Mapping[str, Any]) -> None:
    """Point the base module at a pack and controls; every helper of it reads these two globals."""
    if isinstance(arm_or_plan, Arm):
        base.PACK, controls = arm_or_plan.pack, controls_for(arm_or_plan)
    else:
        base.PACK, controls = arm_or_plan["pack"], arm_or_plan["controls"]
    base.CONTROLS.clear()
    base.CONTROLS.update(controls)


def build_setup(arm: str, pairing: str, case_list: Sequence[CaseManifest], runtimes: Mapping[str, Mapping[str, str]]) -> base.Setup:
    """``agreement_cli.build_setup`` with the confirmatory sampling, block and analysis declarations; the same pins,
    registry, harnesses, profiles and provider capabilities."""
    family = agreement_family_manifest()
    integrator_subject, client_subject = base.PAIRINGS[pairing]
    scripted = integrator_subject.startswith(base.SCRIPTED) and client_subject.startswith(base.SCRIPTED)
    pilot = base.PACK == aap.PILOT.pack
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": f"agreement_confirm_{pairing}_sample_v1",
        "estimand": "seat_earnings_spread_on_the_pilot_pack" if pilot else "seat_earnings_on_the_admitted_pack",
        "target": "negotiating_an_agreement_clause_by_clause",
        "selection": "admitted_on_structure_before_hidden_types", "seeds": [oc.SEED], "replicates": base.CONTROLS["replicates"],
        "cluster_level": "agreement_world", "cluster_id_fields": ["world_seed"], "paired_fields": [], "replicate_level": "episode_attempt",
        "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({
        "spec_version": EvaluationBlock.SPEC_VERSION, "block_id": f"agreement_confirm_{pairing}_block",
        "kind": "reference" if scripted else "self_play" if integrator_subject == client_subject else "cross_play",
        "subject_seats": list(ag.SEATS), "controlled_profiles": {}, "repetitions": 1, "seed_policy": "fixed",
    })
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "agreement_confirmatory_analysis_v1",
        "estimands": ["joint_value_lost", "seat_earnings", "client_signed_below_walk_away"], "group_by": ["family_id"],
        "missingness": "typed_missing_never_rerun", "resampling_unit": "agreement_world", "uncertainty": "paired_t_on_world_values",
        "multiplicity": "holm_across_p1_p2_p3", "sensitivity": ["missing_bounds_lowest_highest", "invalid_scored_as_no_deal"],
        "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": f"agreement_{base.PACK}_{len(case_list)}_worlds", "version": "0.1.0",
        "family_ids": [family.family.id], "case_ids": [c.case_id for c in case_list], "sampling_plan_id": sampling.sampling_plan_id,
        "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id,
    })
    profiles, pricing = {}, {}
    for seat, subject in (("integrator", integrator_subject), ("client", client_subject)):
        p, pr = base._profile(pairing, seat, subject, runtimes)
        profiles[seat] = AgentProfile.from_dict(p)
        pricing[p["model"]["model"]] = pr
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"datacenter_agreement_confirm_{arm.lower()}_{pairing}_run_v1", "suite_id": suite.suite_id,
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
    family_dir = base.FAMILY_DIR
    pins = (
        oc._pin(PLUGIN_ID, "family_plugin", family_dir / "agreement_environment.py"),
        oc._pin(SCORER_IMPLEMENTATION_ID, "scorer", family_dir / "agreement_measurement.py", version=MEASUREMENT_VERSION),
        oc._pin(VALIDITY_IMPLEMENTATION_ID, "reference", family_dir / "agreement_measurement.py", version=MEASUREMENT_VERSION),
        ImplementationPin.from_dict({"component_id": REFERENCE_IMPLEMENTATION_ID, "kind": "reference", "version": MEASUREMENT_VERSION,
                                     "sha256": combined_sha256(REFERENCE_SOURCES)}),
        oc._pin("minimal_chat", "harness", execution_path, version="1.0"),
        oc._pin(base.RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
    )
    providers = tuple(sorted({p.model.provider for p in profiles.values()}))
    plan = resolve_run_plan(
        families=(family,), cases=tuple(case_list), suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis,
        agent_profiles=tuple(profiles.values()), run_spec=run_spec, registry=registry, implementation_pins=pins, harness_registry=harness_registry,
        provider_capabilities={prov: ProviderCapabilities(
            native_tools=False, structured_output=prov != "fake", seed=False, system_prompt=True, reasoning_budget=prov != "fake",
            reasoning_token_report=prov == codex.PROVIDER, max_context_tokens=None) for prov in providers},
    )
    return base.Setup(plan, registry, {base.prompt_id(s): base.system_prompt(s) for s in ag.SEATS}, pricing, harnesses, providers)


def _providers(pairings: Sequence[str]) -> list[str]:
    return sorted({p for pairing in pairings for p in base._providers_of(pairing)})


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPOSITORY_ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def sizing_check(record: Mapping[str, Any]) -> list[str]:
    """Why a sizing record cannot freeze a confirmatory arm: it is not from the pilot, or it needs more deal worlds than
    the pack gives (the plan then has to be amended and committed first)."""
    out = []
    if record.get("pilot_pack") != aap.PILOT.pack:
        out.append(f"the sizing record is not from the pilot pack {aap.PILOT.pack}")
    needed = record.get("deal_worlds_needed")
    if not isinstance(needed, int) or needed > DEAL_WORLDS_AVAILABLE:
        out.append(f"the sizing record needs {needed} deal worlds; the plan allows {DEAL_WORLDS_AVAILABLE} without an amendment")
    return out


def freeze(directory: Path, arm_name: str, sizing_record: Path | None = None) -> dict[str, Any]:
    """Check what the plan requires before a freeze, discover the CLIs, and write ``campaign_plan.json``."""
    arm = ARMS[arm_name]
    if arm.name in ("H", "F", "A"):
        if sizing_record is None:
            raise SystemExit(f"arm {arm.name} freezes only with the pilot's sizing record")
        failures = sizing_check(json.loads(sizing_record.read_text()))
        if failures:
            raise SystemExit("; ".join(failures))
    if subprocess.run(["git", "-C", str(REPOSITORY_ROOT), "merge-base", "--is-ancestor", PLAN_COMMIT, "HEAD"]).returncode != 0:
        raise SystemExit("the confirmatory plan's commit is not in this checkout's history")
    if _git("status", "--porcelain", "--", *SOURCES, PLAN_DOC, *([str(sizing_record)] if sizing_record else [])):
        raise SystemExit("a hashed source, the plan or the sizing record has uncommitted changes; commit before freezing")
    _use(arm)
    clients = asyncio.run(base.discover(_providers(arm.pairings)))
    runtimes = {name: dict(client.runtime_metadata) for name, client in clients.items()}
    plan = plan_for(arm, runtimes, sizing_record, source_commit=_git("rev-parse", "HEAD"))
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
    return plan


def plan_for(arm: Arm, runtimes: Mapping[str, Mapping[str, str]], sizing_record: Path | None = None, *, source_commit: str | None = None,
             worlds: Sequence[str] | None = None) -> dict[str, Any]:
    """The frozen plan of one arm; ``worlds`` (case codes) narrows the pack for a test only."""
    pack_bytes = (ap.CASES_ROOT / arm.pack / "pack.json").read_bytes()
    if arm.pack == aap.ADMITTED.pack and hashlib.sha256(pack_bytes).hexdigest() != ADMITTED_PACK_SHA256:
        raise SystemExit("the admitted pack is not the one the confirmatory plan pins")
    _use(arm)
    case_list = base.cases(worlds)
    plans = []
    for pairing in arm.pairings:
        setup = build_setup(arm.name, pairing, case_list, runtimes)
        plans.append({"pairing": pairing, "integrator": base.PAIRINGS[pairing][0], "client": base.PAIRINGS[pairing][1],
                      "run_plan_id": setup.plan.run_plan_id,
                      "cells": [{"cell_id": c.cell_id, "case_id": c.case_id, "replicate_index": c.replicate_index} for c in setup.plan.cells]})
    manifest, _ = ap.load(arm.pack)
    plan: dict[str, Any] = {
        "campaign_id": arm.campaign_id, "arm": arm.name, "role": arm.role,
        "claim_status": ("confirmatory: the plan's declared contrasts only, on the admitted pack" if arm.name in ("H", "F") else
                         "confirmatory, secondary: reported without a claim" if arm.name == "A" else
                         "development: a variance pilot, nothing in it is a result" if arm.name == "pilot" else "control: no model"),
        "confirmatory_plan": {"path": PLAN_DOC, "commit": PLAN_COMMIT, "sha256": hashlib.sha256((REPOSITORY_ROOT / PLAN_DOC).read_bytes()).hexdigest()},
        "source_commit": source_commit, "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "pack": arm.pack, "pack_json_sha256": hashlib.sha256(pack_bytes).hexdigest(),
        "pack_manifest_sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "worlds": [c.case_id.rsplit(".", 1)[-1] for c in case_list], "controls": dict(base.CONTROLS),
        "estimates": {"negotiations": arm.negotiations, "list_usd": arm.list_usd, "wall_minutes": arm.wall_minutes},
        "pairings": {p: list(base.PAIRINGS[p]) for p in arm.pairings}, "provider_runtimes": runtimes,
        "subjects": {k: {"provider": v["provider"], "model": v["model"], "pricing_id": v["pricing"].pricing_id} for k, v in base.SUBJECTS.items()},
        "billing": "subscription logins; cost is the list price of the tokens, not a charge",
        "tools": "none: Claude Code with --tools \"\"; Codex with its acting features disabled, and a call that uses a tool is refused",
        "system_prompts": {base.prompt_id(s): base.system_prompt(s) for s in ag.SEATS},
        "stops": {"list_price": "no negotiation starts once the campaign's list-price total reaches max_cost_usd_total",
                  "wall_time": "no negotiation starts after max_wall_minutes from the start of the run",
                  "halt": f"no negotiation starts after {HALT_AFTER} consecutive operational failures (DC-T-08)",
                  "per_move": "a CLI call that exceeds timeout_seconds fails its negotiation; one attempt a move"},
        "missingness": "a negotiation that ends in an operational failure, or is not started, is typed missing; never rerun or replaced",
        "declared_analysis": f"{PLAN_DOC}, sections 'Primary contrasts', 'Exclusions and missingness' and 'Analysis'",
        "sources": {rel: base._digest(rel) for rel in SOURCES}, "plans": plans,
    }
    styles = sorted({s[len(base.SCRIPTED + "negotiator_"):] for p in arm.pairings for s in base.PAIRINGS[p] if s.startswith(base.SCRIPTED + "negotiator_")})
    if styles:
        plan["scripted_negotiator"] = {
            "module": "aeread_families.datacenter_development.agreement_negotiator", "styles_in_this_campaign": styles,
            "fixed_styles": {k: vars(v) for k, v in an.STYLES.items() if k in styles},
            **({PUBLIC: {"module": "aeread_families.datacenter_development.agreement_admitted_pack.public_negotiator_move",
                         "drawn_from": an.POPULATION, "population_id": aap.STYLE_POPULATION,
                         "drawn_by": "the public world and the seat alone, never a hidden type (DC-D-32); the other side is not told which"}}
               if PUBLIC in styles else {}),
            "reads": "its own seat's information: its own costs, the other side's as the declared types and odds, and the moves; never a note",
        }
    if sizing_record is not None:
        plan["sizing_record"] = {"path": str(sizing_record.resolve().relative_to(REPOSITORY_ROOT)),
                                 "sha256": hashlib.sha256(sizing_record.read_bytes()).hexdigest(), "record": json.loads(sizing_record.read_text())}
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


class Halt:
    """Counts consecutive operational failures in the order negotiations finish."""

    def __init__(self, limit: int) -> None:
        self.limit, self.streak, self.fired_after = limit, 0, None

    def record(self, record: Mapping[str, Any]) -> None:
        if record["status"].startswith("not_attempted"):
            return
        self.streak = self.streak + 1 if record.get("error") else 0
        if self.streak >= self.limit and self.fired_after is None:
            self.fired_after = record["cell_key"]

    @property
    def fired(self) -> bool:
        return self.fired_after is not None


def _write(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, default=str))


async def _run_cell(directory: Path, entry: Mapping[str, Any], setup: base.Setup, cell: Any, clients: Mapping[str, Any], spend: oc.Spend,
                    halt: Halt, sem: asyncio.Semaphore) -> dict[str, Any]:
    """``agreement_cli._run_cell`` with the stops checked once a slot is free, and the wall time of each negotiation."""
    key = f"{entry['pairing']}__{cell.case_id.rsplit('.', 1)[-1]}__r{cell.replicate_index}"
    record_path = directory / "cells" / f"{key}.json"
    if record_path.exists():
        return json.loads(record_path.read_text())
    async with sem:
        record: dict[str, Any] = {"cell_key": key, "pairing": entry["pairing"], "integrator": entry["integrator"], "client": entry["client"],
                                  "case_id": cell.case_id, "cell_id": cell.cell_id, "replicate_index": cell.replicate_index,
                                  "run_plan_id": setup.plan.run_plan_id}
        stop = ("not_attempted_halt" if halt.fired else "not_attempted_budget" if spend.exhausted else
                "not_attempted_wall_time" if spend.past_deadline else None)
        if stop is not None:
            record.update(status=stop, **({"halted_after": halt.fired_after} if halt.fired else {}))
            _write(record_path, record)
            return record
        evidence_root = directory / "evidence" / key
        payload = next(c.payload for c in setup.plan.cases if c.case_id == cell.case_id)
        providers: dict[str, Any] = {name: codex.LoggedClient(client, directory / "cli_calls.jsonl", subject=name) for name, client in clients.items()
                                     if name in setup.providers}
        if "fake" in setup.providers:
            providers["fake"] = base.ScriptedClient(payload, {seat: entry[seat][len(base.SCRIPTED):] for seat in ag.SEATS
                                                              if entry[seat].startswith(base.SCRIPTED)})
        started = time.monotonic()
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
        record["wall_seconds"] = round(time.monotonic() - started, 2)
        _write(record_path, record)
        halt.record(record)
        g = record.get("grade") or {}
        print(f"{key:64} {record['status']:22} {record.get('termination') or ''} lost {g.get('joint_value_lost', '')} "
              f"{record['wall_seconds']:.0f}s", flush=True)
        return record


def _setups(plan: Mapping[str, Any], runtimes: Mapping[str, Mapping[str, str]]) -> dict[str, base.Setup]:
    case_list = base.cases(plan["worlds"])
    out = {}
    for entry in plan["plans"]:
        setup = build_setup(plan["arm"], entry["pairing"], case_list, runtimes)
        if setup.plan.run_plan_id != entry["run_plan_id"]:
            raise SystemExit(f"run plan {entry['run_plan_id']} no longer resolves identically; freeze a new campaign")
        out[entry["pairing"]] = setup
    return out


def _check_sources(plan: Mapping[str, Any]) -> None:
    changed = [rel for rel, d in plan["sources"].items() if base._digest(rel) != d]
    if changed:
        raise SystemExit(f"sources changed since the plan was frozen ({changed}); freeze a new campaign directory")


async def run(directory: Path) -> dict[str, Any]:
    plan = json.loads((directory / "campaign_plan.json").read_text())
    _use(plan)
    _check_sources(plan)
    clients = await base.discover(_providers(plan["pairings"]))
    runtimes = {name: dict(client.runtime_metadata) for name, client in clients.items()}
    if runtimes != plan["provider_runtimes"]:
        raise SystemExit("a CLI's version or the adapter changed since the plan was frozen; freeze a new campaign directory")
    return await run_cells(directory, plan, _setups(plan, runtimes), clients)


async def run_cells(directory: Path, plan: Mapping[str, Any], setups: Mapping[str, base.Setup], clients: Mapping[str, Any]) -> dict[str, Any]:
    """Every cell of the plan under its stops. Records already written are kept as they stand, never rerun."""
    controls = plan["controls"]
    spend = oc.Spend(controls["max_cost_usd_total"], wall_hours=controls["max_wall_minutes"] / 60.0)
    halt = Halt(controls["halt_after_consecutive_operational_failures"])
    sem = asyncio.Semaphore(controls["max_parallel_cells"])
    started = datetime.datetime.now(datetime.timezone.utc)
    t0 = time.monotonic()
    jobs = [_run_cell(directory, entry, setups[entry["pairing"]], cell, clients, spend, halt, sem)
            for entry in plan["plans"] for cell in setups[entry["pairing"]].plan.cells]
    records = await asyncio.gather(*jobs)
    summary = {"campaign_id": plan["campaign_id"], "plan_sha256": plan["plan_sha256"], "started": started.isoformat(timespec="seconds"),
               "wall_minutes": round((time.monotonic() - t0) / 60.0, 2), "list_price_usd": round(spend.spent, 4),
               "status": {s: sum(r["status"] == s for r in records) for s in sorted({r["status"] for r in records})},
               "halted_after": halt.fired_after}
    with (directory / "run_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=1))
    return summary


def verify(directory: Path) -> dict[str, Any]:
    """Every sealed receipt replayed offline from its evidence: digest and canonical bytes, the evidence seal, the score
    recomputed from the sealed events, and the cell record's grade against the receipt. No provider is called."""
    plan = json.loads((directory / "campaign_plan.json").read_text())
    _use(plan)
    _check_sources(plan)
    setups = _setups(plan, plan["provider_runtimes"])
    out = {"replayed": 0, "failed": [], "without_receipt": [], "by_status": {}}
    for path in sorted((directory / "cells").glob("*.json")):
        record = json.loads(path.read_text())
        out["by_status"][record["status"]] = out["by_status"].get(record["status"], 0) + 1
        if not record.get("receipt_sha256"):
            out["without_receipt"].append(record["cell_key"])
            continue
        evidence_root = directory / "evidence" / record["cell_key"]
        try:
            receipt_path = next(evidence_root.rglob("evaluation_receipt.json"))
            receipt = _deserialize_receipt(read_evaluation_receipt(receipt_path))
            if receipt.receipt_sha256 != record["receipt_sha256"]:
                raise ValueError("the cell record names another receipt")
            replayed = replay_family_receipt(setup=setups[record["pairing"]], receipt=receipt, evidence_root=evidence_root)
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise ValueError("replay produced a different receipt")
            out["replayed"] += 1
        except Exception as error:  # noqa: BLE001 - every failure is listed
            out["failed"].append({"cell_key": record["cell_key"], "error": f"{type(error).__name__}: {str(error)[:300]}"})
    (directory / "verify.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    return out


def dry_run_failures(directory: Path) -> list[str]:
    """The dry run's checks, world by world, from the cell records and the pack's own economics: nothing lost, the oracle
    pair loses 0 and signs c* exactly when a deal is worth signing, the draft pair loses A less the draft's surplus (all
    of A where the draft is worse than walking away) and signs the draft at the midpoint of what it leaves."""
    plan = json.loads((directory / "campaign_plan.json").read_text())
    manifest, cases = ap.load(plan["pack"])
    worlds = {w["case_id"]: w for w in manifest["worlds"]}
    records = [json.loads(p.read_text()) for p in sorted((directory / "cells").glob("*.json"))]
    out = []
    expected = sum(len(e["cells"]) for e in plan["plans"])
    if len(records) != expected:
        out.append(f"{len(records)} records for {expected} cells")
    for r in records:
        say = lambda what: out.append(f"{r['cell_key']}: {what}")  # noqa: E731
        g, w = r.get("grade") or {}, worlds[r["case_id"]]
        if r["status"] != "ok" or not g.get("valid"):
            say(f"status {r['status']}, valid {g.get('valid')}")
            continue
        cw, it = rc_world(cases[r["case_id"]]["payload"])
        floor = cw.w.terms.floor_margin
        available = w["available_surplus"]
        if abs(g["available_surplus"] - available) > 1e-9:
            say(f"graded available {g['available_surplus']}, indexed {available}")
        if r["pairing"].startswith("oracle"):
            if abs(g["joint_value_lost"]) > 1e-6:
                say(f"the oracle pair lost {g['joint_value_lost']}")
            if (r["termination"] == "signed") != (available > 0):
                say(f"the oracle pair {r['termination']} with {available} available")
            if r["termination"] == "signed" and g["signed_agreement"] != w["best_agreement"]:
                say(f"the oracle pair signed {g['signed_agreement']}, not c* {w['best_agreement']}")
        else:
            d = ag.draft(cw)
            ic, cc = ag.costs(cw, it, d)
            draft_surplus = cw.best_outside[1] - floor - ic - cc
            predicted = available - max(0.0, draft_surplus)
            if abs(g["joint_value_lost"] - predicted) > 1e-3:
                say(f"the draft pair lost {g['joint_value_lost']}, predicted {predicted}")
            if (r["termination"] == "signed") != (draft_surplus > 0) or w["draft_beats_no_deal"] != (draft_surplus > 0):
                say(f"the draft pair {r['termination']} with the draft's surplus {draft_surplus}")
            if r["termination"] == "signed":
                midpoint = ic + floor + draft_surplus / 2
                if abs(r["signed"]["price"] - midpoint) > 1e-6 or g["signed_agreement"] != w["draft"]:
                    say(f"signed {g['signed_agreement']} at {r['signed']['price']}, not the draft at its midpoint {midpoint}")
    return out


def rc_world(payload: Mapping[str, Any]):
    return rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["freeze", "run", "verify", "dry-run"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--arm", choices=sorted(ARMS))
    parser.add_argument("--sizing-record", type=Path, help="the pilot's sizing record; required to freeze H, F or A")
    args = parser.parse_args(argv)
    if args.command == "freeze":
        if args.arm is None:
            parser.error("freeze needs --arm")
        plan = freeze(args.directory, args.arm, args.sizing_record)
        print(f"froze {sum(len(p['cells']) for p in plan['plans'])} cells in {len(plan['plans'])} plans: {plan['plan_sha256'][:12]}")
    elif args.command == "run":
        asyncio.run(run(args.directory))
    elif args.command == "verify":
        result = verify(args.directory)
        print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in result.items()}, indent=1))
        return 1 if result["failed"] else 0
    else:
        if not args.directory.exists():
            freeze(args.directory, "dry")
        asyncio.run(run(args.directory))
        failures = dry_run_failures(args.directory)
        verified = verify(args.directory)
        print(f"dry run: {len(failures)} failures; {verified['replayed']} receipts replayed offline, {len(verified['failed'])} failed")
        for f in failures[:20]:
            print(" ", f)
        return 1 if failures or verified["failed"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
