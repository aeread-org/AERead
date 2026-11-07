"""The agreement case's v2 confirmatory: its dry run, its pilot and arms IF, HH and CF, with isolated CLI subjects.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_cli.py probe
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_cli.py dry-run  runs/<dir>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_cli.py freeze   runs/<dir> --arm pilot_IF
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_cli.py run      runs/<dir>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_cli.py verify   runs/<dir>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_cli.py estimate runs/<pilot dirs...> --out FILE
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_cli.py freeze   runs/<dir> --arm IF --estimate-record FILE

The plan is ``docs/families/datacenter/agreement_confirmatory_v2_plan.md`` with its three amendments. This module wraps
:mod:`agreement_confirmatory_cli` (v1's driver) and :mod:`agreement_cli`, which stay unedited: v1's cell runner, halt
rule, stops, typed missingness and dry-run checks are used as they are. What v2 adds:

- the packs ``agreement_admitted_v2`` and ``agreement_admitted_pilot_v2`` (:mod:`agreement_admitted_pack_v2`), each pinned
  by the digest of its ``pack.json``;
- the arms of Section 3, each its own campaign: IF (the integrator seat against the publicly drawn firm client, two
  plays a model a world), HH (head to head, both seatings, one play) and CF (the client seat against the firm
  integrator, one play), on the confirmatory pack; the same three on the pilot pack as ``pilot_IF``, ``pilot_HH`` and
  ``pilot_CF`` (amendment 3); and a scripted dry run;
- subject isolation (amendments 1 and 2, :mod:`cli_isolation`): Claude Code runs each call in a fresh neutral directory
  through its command runner, and Codex runs with a fresh ``HOME``, ``CODEX_HOME`` and working directory. Each CLI is
  probed at the freeze and again before the run starts; a probe that shows a violation refuses the freeze or halts the
  run before any cell, and the probes are sealed in the campaign plan;
- the ceilings: an arm's list-price and wall-time ceilings are twice its estimate. The pilot's estimates come from v1's
  measured rates; a confirmatory arm freezes only with an estimate record measured on the pilot (amendment 3).

Both CLIs run on subscription logins; cost is the list price of the tokens, not a charge.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import shutil
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import agreement_cli as base
import agreement_confirmatory_cli as v1
import cli_isolation as iso
import codex_exec_client as codex
from aeread.shared_runner.analysis.research import _deserialize_receipt
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import replay_family_receipt
from aeread.shared_runner.task.execution import ClaudeCodePrintClient, EvidenceStore
from aeread.shared_runner.task.receipts import read_evaluation_receipt, verify_evaluation_receipt
from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_pack_v2 as pv2
from aeread_families.datacenter_development import agreement_negotiator as an
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import risk_allocation_campaign as oc
from aeread_families.datacenter_development.agreement_environment import PLUGIN_ID, AgreementPlugin, agreement_family_manifest
from aeread_families.datacenter_development.agreement_measurement import (
    REFERENCE_IMPLEMENTATION_ID, REFERENCE_SOURCES, SCORER_IMPLEMENTATION_ID, VALIDITY_IMPLEMENTATION_ID,
    VERSION as MEASUREMENT_VERSION, combined_sha256,
)

import aeread.shared_runner.task.execution as execution_module

REPOSITORY_ROOT = base.REPOSITORY_ROOT
PLAN_DOC = "docs/families/datacenter/agreement_confirmatory_v2_plan.md"
#: The plan's declaring commit and its last amendment; both must be in the checkout's history at a freeze.
PLAN_COMMITS = ("01ee245cd8c74f6dad4c1baadcba9db788e297cb", "69584cf58a6d272d45d0d2e92738433460b55a8d")
#: sha256 of each pack's pack.json as committed; a freeze refuses any other bytes.
PACK_SHA256 = {
    pv2.ADMITTED.pack: "56fd64a14fa811c75e68c8cf47ac08184fcac37845bec0b98bd39f12b1002209",
    pv2.PILOT.pack: "943b9b4835e29fd0c4a893ec4d52e71c8da96c24aa6eb1ae0481b076faf2395b",
}
PUBLIC = v1.PUBLIC
HALT_AFTER = v1.HALT_AFTER
SOURCES = (*v1.SOURCES, "src/aeread_families/datacenter_development/agreement_admitted_pack_v2.py",
           "tools/cli_subjects/cli_isolation.py", "tools/cli_subjects/agreement_confirmatory_v2_cli.py")
IF_PAIRINGS = tuple(f"{n}_integrator__negotiator_{PUBLIC}_client" for n in ("codex", "claude"))
HH_PAIRINGS = ("codex_integrator__claude_client", "claude_integrator__codex_client")
CF_PAIRINGS = tuple(f"negotiator_{PUBLIC}_integrator__{n}_client" for n in ("codex", "claude"))
DRY_PAIRINGS = ("oracle_integrator__oracle_client", "draft_integrator__draft_client")
#: v1's measured rates (run_log.jsonl of its arms F and H, 2026-10-14): list price a negotiation and slot-minutes a
#: negotiation (wall minutes times parallel cells over negotiations). A one-model-seat negotiation against a script is
#: arm F's rate; head to head is arm H's.
V1_RATES = {"firm": {"usd": 11.8456 / 240, "slot_minutes": 48.83 * 4 / 240},
            "head_to_head": {"usd": 16.0841 / 120, "slot_minutes": 62.76 * 3 / 120}}


@dataclass(frozen=True)
class Arm:
    name: str
    campaign_id: str
    pack: str
    pairings: tuple[str, ...]
    plays: int
    parallel: int
    kind: str  # "firm", "head_to_head" or "scripted": which rate estimates it
    role: str

    @property
    def worlds(self) -> int:
        return len(ap.load(self.pack)[0]["worlds"])

    @property
    def negotiations(self) -> int:
        return len(self.pairings) * self.plays * self.worlds

    @property
    def confirmatory(self) -> bool:
        return self.name in ("IF", "HH", "CF")


def _arm(name: str, pack: str, pairings: tuple[str, ...], plays: int, parallel: int, kind: str, role: str) -> Arm:
    slug = {"IF": "integrator_firm", "HH": "head_to_head", "CF": "client_firm"}
    tail = name.split("_", 1)[-1]
    prefix = "datacenter_agreement_v2_pilot_" if name.startswith("pilot_") else "datacenter_agreement_v2_"
    return Arm(name, prefix + (slug.get(tail, tail)), pack, pairings, plays, parallel, kind, role)


ARMS: dict[str, Arm] = {a.name: a for a in (
    _arm("dry", pv2.ADMITTED.pack, DRY_PAIRINGS, 1, 8, "scripted",
         "control: the full-information pair and the draft pair on every v2 world, no model"),
    _arm("pilot_IF", pv2.PILOT.pack, IF_PAIRINGS, 2, 4, "firm", "development: the pilot of arm IF (amendment 3); never analysed"),
    _arm("pilot_HH", pv2.PILOT.pack, HH_PAIRINGS, 1, 3, "head_to_head", "development: the pilot of arm HH (amendment 3); never analysed"),
    _arm("pilot_CF", pv2.PILOT.pack, CF_PAIRINGS, 1, 4, "firm", "development: the pilot of arm CF (amendment 3); never analysed"),
    _arm("IF", pv2.ADMITTED.pack, IF_PAIRINGS, 2, 4, "firm", "primary: P1, P3a and P3b"),
    _arm("HH", pv2.ADMITTED.pack, HH_PAIRINGS, 1, 3, "head_to_head", "primary: P2"),
    _arm("CF", pv2.ADMITTED.pack, CF_PAIRINGS, 1, 4, "firm", "secondary: the client seat against the firm population, no claim"),
)}


def v1_estimate(arm: Arm) -> dict[str, float]:
    """The pilot's estimate from v1's measured rates (the scripted dry run costs nothing and takes minutes)."""
    if arm.kind == "scripted":
        return {"list_usd": 0.5, "wall_minutes": 10.0, "source": "scripted"}
    rate = V1_RATES[arm.kind]
    return {"list_usd": round(rate["usd"] * arm.negotiations, 2),
            "wall_minutes": round(rate["slot_minutes"] * arm.negotiations / arm.parallel, 1), "source": "v1 measured rates"}


def controls_for(arm: Arm, estimate: Mapping[str, float]) -> dict[str, Any]:
    out = dict(base.CONTROLS)
    out.update(replicates=arm.plays, max_parallel_cells=arm.parallel, prompt_variant="v1",
               max_cost_usd_total=round(2 * estimate["list_usd"], 2), max_wall_minutes=round(2 * estimate["wall_minutes"], 1),
               halt_after_consecutive_operational_failures=HALT_AFTER)
    return out


def _use(pack: str, controls: Mapping[str, Any]) -> None:
    base.PACK = pack
    base.CONTROLS.clear()
    base.CONTROLS.update(controls)


def build_setup(arm: Arm, pairing: str, case_list: Sequence[CaseManifest], runtimes: Mapping[str, Mapping[str, str]]) -> base.Setup:
    """v1's ``build_setup`` with v2's ids: the same pins, registry, harnesses, profiles and provider capabilities."""
    family = agreement_family_manifest()
    integrator_subject, client_subject = base.PAIRINGS[pairing]
    scripted = integrator_subject.startswith(base.SCRIPTED) and client_subject.startswith(base.SCRIPTED)
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": f"agreement_v2_{pairing}_sample",
        "estimand": "seat_earnings_on_the_v2_pilot_pack" if arm.pack == pv2.PILOT.pack else "seat_earnings_on_the_v2_pack",
        "target": "negotiating_an_agreement_clause_by_clause",
        "selection": "admitted_on_structure_then_screened_for_integrator_headroom", "seeds": [oc.SEED],
        "replicates": base.CONTROLS["replicates"], "cluster_level": "agreement_world", "cluster_id_fields": ["world_seed"],
        "paired_fields": [], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({
        "spec_version": EvaluationBlock.SPEC_VERSION, "block_id": f"agreement_v2_{pairing}_block",
        "kind": "reference" if scripted else "self_play" if integrator_subject == client_subject else "cross_play",
        "subject_seats": list(ag.SEATS), "controlled_profiles": {}, "repetitions": 1, "seed_policy": "fixed",
    })
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "agreement_confirmatory_analysis_v2",
        "estimands": ["seat_earnings", "joint_value_lost", "client_signed_below_walk_away"], "group_by": ["family_id"],
        "missingness": "typed_missing_never_rerun", "resampling_unit": "agreement_world", "uncertainty": "paired_t_on_world_means",
        "multiplicity": "holm_across_p1_p2_p3a_p3b", "sensitivity": ["missing_bounds_lowest_highest", "invalid_scored_as_no_deal"],
        "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": f"agreement_{arm.pack}_{len(case_list)}_worlds", "version": "0.2.0",
        "family_ids": [family.family.id], "case_ids": [c.case_id for c in case_list], "sampling_plan_id": sampling.sampling_plan_id,
        "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id,
    })
    profiles, pricing = {}, {}
    for seat, subject in (("integrator", integrator_subject), ("client", client_subject)):
        p, pr = base._profile(pairing, seat, subject, runtimes)
        profiles[seat] = AgentProfile.from_dict(p)
        pricing[p["model"]["model"]] = pr
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"datacenter_agreement_v2_{arm.name.lower()}_{pairing}_run",
        "suite_id": suite.suite_id, "evaluation_block_ids": [block.block_id],
        "agent_profile_ids": sorted(p.profile_id for p in profiles.values()),
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


# ---------------------------------------------------------------------------
# Isolated subjects.


async def _isolated_claude_runner(arguments: tuple[str, ...], standard_input: bytes) -> tuple[int, bytes, bytes]:
    """``agreement_cli._claude_runner`` (the CLI's refusal reason carried to stderr) in a fresh neutral directory."""
    returncode, stdout, stderr = await iso.isolated_command_runner(arguments, standard_input)
    if returncode != 0 and not stderr.strip():
        try:
            payload = json.loads(stdout)
            stderr = f"{payload.get('result')} (api_error_status {payload.get('api_error_status')})".encode("utf-8")
        except (ValueError, AttributeError):
            stderr = stdout[-400:]
    return returncode, stdout, stderr


async def discover(providers: Sequence[str]) -> dict[str, Any]:
    """The CLI clients of these providers, each isolated."""
    iso.install_codex_isolation()
    clients: dict[str, Any] = {}
    if "claude_code" in providers:
        found = await ClaudeCodePrintClient.discover()
        clients["claude_code"] = ClaudeCodePrintClient(executable=Path(shutil.which("claude")).resolve(), runtime_version=found.runtime_version,
                                                       runtime_sha256=found.runtime_sha256, command_runner=_isolated_claude_runner)
    if codex.PROVIDER in providers:
        clients[codex.PROVIDER] = await codex.CodexExecClient.discover()
    return clients


async def probe(clients: Mapping[str, Any]) -> dict[str, Any]:
    """Each client's context probe under the run's model and effort, and the violations it shows."""
    effort = base.CONTROLS["reasoning_effort"]
    out: dict[str, Any] = {}
    if codex.PROVIDER in clients:
        out["codex_cli"] = await iso.probe_codex(clients[codex.PROVIDER], model=base.SUBJECTS["codex_sol61"]["model"], reasoning_effort=effort)
    if "claude_code" in clients:
        client = clients["claude_code"]
        out["claude_code"] = await iso.probe_claude(client, client._executable, model=base.SUBJECTS["claude_opus55"]["model"],
                                                    reasoning_effort=effort, runner=_isolated_claude_runner)
    return {"probes": out, "violations": {k: iso.isolation_violations(v) for k, v in out.items()},
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}


# ---------------------------------------------------------------------------
# Freeze, run, verify.


def _providers(pairings: Sequence[str]) -> list[str]:
    return sorted({p for pairing in pairings for p in base._providers_of(pairing)})


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPOSITORY_ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def estimate_check(arm: Arm, record: Mapping[str, Any]) -> list[str]:
    """Why an estimate record cannot set a confirmatory arm's ceilings: not measured on this arm's pilot."""
    out = []
    pilot = ARMS[f"pilot_{arm.name}"]
    row = (record.get("arms") or {}).get(arm.name)
    if not isinstance(row, Mapping):
        return [f"the estimate record has no row for arm {arm.name}"]
    if row.get("measured_on") != pilot.campaign_id:
        out.append(f"arm {arm.name}'s estimate is not measured on {pilot.campaign_id}")
    for key in ("list_usd", "wall_minutes"):
        if not isinstance(row.get(key), (int, float)) or row[key] <= 0:
            out.append(f"arm {arm.name}'s estimate lacks a positive {key}")
    return out


def freeze(directory: Path, arm_name: str, estimate_record: Path | None = None) -> dict[str, Any]:
    arm = ARMS[arm_name]
    for commit in PLAN_COMMITS:
        if subprocess.run(["git", "-C", str(REPOSITORY_ROOT), "merge-base", "--is-ancestor", commit, "HEAD"]).returncode != 0:
            raise SystemExit(f"the v2 plan's commit {commit[:8]} is not in this checkout's history")
    if arm.confirmatory:
        if estimate_record is None:
            raise SystemExit(f"arm {arm.name} freezes only with the pilot's estimate record (amendment 3)")
        failures = estimate_check(arm, json.loads(estimate_record.read_text()))
        if failures:
            raise SystemExit("; ".join(failures))
        estimate = dict(json.loads(estimate_record.read_text())["arms"][arm.name])
    else:
        estimate = v1_estimate(arm)
    if _git("status", "--porcelain", "--", *SOURCES, PLAN_DOC, *([str(estimate_record)] if estimate_record else [])):
        raise SystemExit("a hashed source, the plan or the estimate record has uncommitted changes; commit before freezing")
    _use(arm.pack, controls_for(arm, estimate))
    clients = asyncio.run(discover(_providers(arm.pairings)))
    probes = asyncio.run(probe(clients)) if clients else {"probes": {}, "violations": {}}
    bad = {k: v for k, v in probes["violations"].items() if v}
    if bad:
        raise SystemExit(f"the isolation probe refuses the freeze: {bad}")
    runtimes = {name: dict(client.runtime_metadata) for name, client in clients.items()}
    plan = plan_for(arm, runtimes, estimate, probes, estimate_record, source_commit=_git("rev-parse", "HEAD"))
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
    return plan


def plan_for(arm: Arm, runtimes: Mapping[str, Mapping[str, str]], estimate: Mapping[str, Any], probes: Mapping[str, Any],
             estimate_record: Path | None = None, *, source_commit: str | None = None, worlds: Sequence[str] | None = None) -> dict[str, Any]:
    pack_bytes = (ap.CASES_ROOT / arm.pack / "pack.json").read_bytes()
    if hashlib.sha256(pack_bytes).hexdigest() != PACK_SHA256[arm.pack]:
        raise SystemExit(f"{arm.pack} is not the pack the driver pins")
    _use(arm.pack, controls_for(arm, estimate))
    case_list = base.cases(worlds)
    plans = []
    for pairing in arm.pairings:
        setup = build_setup(arm, pairing, case_list, runtimes)
        plans.append({"pairing": pairing, "integrator": base.PAIRINGS[pairing][0], "client": base.PAIRINGS[pairing][1],
                      "run_plan_id": setup.plan.run_plan_id,
                      "cells": [{"cell_id": c.cell_id, "case_id": c.case_id, "replicate_index": c.replicate_index} for c in setup.plan.cells]})
    manifest, _ = ap.load(arm.pack)
    plan: dict[str, Any] = {
        "campaign_id": arm.campaign_id, "arm": arm.name, "role": arm.role,
        "claim_status": ("confirmatory: the plan's declared contrasts only" if arm.name in ("IF", "HH") else
                         "confirmatory, secondary: descriptive, no claim" if arm.name == "CF" else
                         "development: a pilot, never analysed" if arm.name.startswith("pilot_") else "control: no model"),
        "confirmatory_plan": {"path": PLAN_DOC, "commits": list(PLAN_COMMITS),
                              "sha256": hashlib.sha256((REPOSITORY_ROOT / PLAN_DOC).read_bytes()).hexdigest()},
        "source_commit": source_commit, "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "pack": arm.pack, "pack_json_sha256": hashlib.sha256(pack_bytes).hexdigest(),
        "pack_manifest_sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "worlds": [c.case_id.rsplit(".", 1)[-1] for c in case_list], "controls": dict(base.CONTROLS),
        "estimates": {"negotiations": arm.negotiations, **dict(estimate)},
        "pairings": {p: list(base.PAIRINGS[p]) for p in arm.pairings}, "provider_runtimes": runtimes,
        "subjects": {k: {"provider": v["provider"], "model": v["model"], "pricing_id": v["pricing"].pricing_id} for k, v in base.SUBJECTS.items()},
        "billing": "subscription logins; cost is the list price of the tokens, not a charge",
        "tools": "none: Claude Code with --tools \"\"; Codex with its acting features disabled, and a call that uses a tool is refused",
        "isolation": {"declaration": dict(iso.DECLARATION), "freeze_probe": probes,
                      "run_probe": "repeated before the first cell; a violation halts the run before any cell"},
        "system_prompts": {base.prompt_id(s): base.system_prompt(s) for s in ag.SEATS},
        "stops": {"list_price": "no negotiation starts once the campaign's list-price total reaches max_cost_usd_total (twice the estimate)",
                  "wall_time": "no negotiation starts after max_wall_minutes (twice the estimate) from the start of the run",
                  "halt": f"no negotiation starts after {HALT_AFTER} consecutive operational failures (DC-T-08)",
                  "per_move": "a CLI call that exceeds timeout_seconds fails its negotiation; one attempt a move"},
        "missingness": "a negotiation that ends in an operational failure, or is not started, is typed missing; never rerun or replaced",
        "declared_analysis": f"{PLAN_DOC}, Sections 4 and 5; tools/cli_subjects/agreement_confirmatory_v2_analysis.py",
        "sources": {rel: base._digest(rel) for rel in SOURCES}, "plans": plans,
    }
    styles = sorted({s[len(base.SCRIPTED + "negotiator_"):] for p in arm.pairings for s in base.PAIRINGS[p] if s.startswith(base.SCRIPTED + "negotiator_")})
    if styles:
        plan["scripted_negotiator"] = {
            "module": "aeread_families.datacenter_development.agreement_admitted_pack.public_negotiator_move", "styles_in_this_campaign": styles,
            "drawn_from": an.POPULATION, "drawn_by": "the public world and the seat alone, never a hidden type (DC-D-32)",
            "reads": "its own seat's information: its own costs, the other side's as the declared types and odds, and the moves; never a note",
        }
    if estimate_record is not None:
        plan["estimate_record"] = {"path": str(estimate_record.resolve().relative_to(REPOSITORY_ROOT)),
                                   "sha256": hashlib.sha256(estimate_record.read_bytes()).hexdigest()}
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


def _setups(plan: Mapping[str, Any], runtimes: Mapping[str, Mapping[str, str]]) -> dict[str, base.Setup]:
    arm = ARMS[plan["arm"]]
    _use(plan["pack"], plan["controls"])
    case_list = base.cases(plan["worlds"])
    out = {}
    for entry in plan["plans"]:
        setup = build_setup(arm, entry["pairing"], case_list, runtimes)
        if setup.plan.run_plan_id != entry["run_plan_id"]:
            raise SystemExit(f"run plan {entry['run_plan_id']} no longer resolves identically; freeze a new campaign")
        out[entry["pairing"]] = setup
    return out


async def run(directory: Path) -> dict[str, Any]:
    plan = json.loads((directory / "campaign_plan.json").read_text())
    _use(plan["pack"], plan["controls"])
    v1._check_sources(plan)
    clients = await discover(_providers(plan["pairings"]))
    runtimes = {name: dict(client.runtime_metadata) for name, client in clients.items()}
    if runtimes != plan["provider_runtimes"]:
        raise SystemExit("a CLI's version or the adapter changed since the plan was frozen; freeze a new campaign directory")
    if clients:
        probes = await probe(clients)
        (directory / "run_probe.json").write_text(json.dumps(probes, indent=1, default=str))
        bad = {k: v for k, v in probes["violations"].items() if v}
        if bad:
            raise SystemExit(f"the isolation probe halts the run before any cell: {bad}")
    return await v1.run_cells(directory, plan, _setups(plan, runtimes), clients)


def verify(directory: Path) -> dict[str, Any]:
    """Every sealed receipt replayed offline from its evidence. A sealed failure receipt has no score to replay; its digest
    and its evidence seal are checked and it is counted as an exclusion, not as a failed replay (DC-T-22). No provider
    is called."""
    plan = json.loads((directory / "campaign_plan.json").read_text())
    v1._check_sources(plan)
    setups = _setups(plan, plan["provider_runtimes"])
    out: dict[str, Any] = {"replayed": 0, "failed": [], "without_receipt": [], "sealed_failure_receipts": [], "by_status": {}}
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
            if record.get("error"):
                if receipt.status == "ok":
                    raise ValueError("a failed cell carries an ok receipt")
                verify_evaluation_receipt(receipt)
                EvidenceStore.audit_existing(receipt_path.parent).verify_seal()
                out["sealed_failure_receipts"].append(record["cell_key"])
                continue
            replayed = replay_family_receipt(setup=setups[record["pairing"]], receipt=receipt, evidence_root=evidence_root)
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise ValueError("replay produced a different receipt")
            out["replayed"] += 1
        except Exception as error:  # noqa: BLE001 - every failure is listed
            out["failed"].append({"cell_key": record["cell_key"], "error": f"{type(error).__name__}: {str(error)[:300]}"})
    (directory / "verify.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    return out


def estimate(directories: Sequence[Path]) -> dict[str, Any]:
    """Each confirmatory arm's estimate from its pilot's run: list price and slot-minutes a negotiation, scaled to the arm."""
    arms: dict[str, Any] = {}
    for directory in directories:
        plan = json.loads((directory / "campaign_plan.json").read_text())
        pilot = ARMS[plan["arm"]]
        if not pilot.name.startswith("pilot_"):
            raise SystemExit(f"{directory} is not a pilot campaign")
        summary = [json.loads(line) for line in (directory / "run_log.jsonl").read_text().splitlines() if line.strip()][-1]
        records = [json.loads(p.read_text()) for p in (directory / "cells").glob("*.json")]
        attempted = [r for r in records if not r["status"].startswith("not_attempted")]
        target = ARMS[pilot.name.split("_", 1)[1]]
        usd = summary["list_price_usd"] / len(attempted)
        slot_minutes = summary["wall_minutes"] * pilot.parallel / len(attempted)
        arms[target.name] = {
            "measured_on": pilot.campaign_id, "pilot_negotiations": len(attempted), "pilot_list_usd": summary["list_price_usd"],
            "pilot_wall_minutes": summary["wall_minutes"], "median_negotiation_seconds": statistics.median(r.get("wall_seconds", 0) for r in attempted),
            "list_usd": round(usd * target.negotiations, 2), "wall_minutes": round(slot_minutes * target.negotiations / target.parallel, 1),
            "negotiations": target.negotiations, "parallel": target.parallel,
        }
    return {"plan": PLAN_DOC, "rule": "an arm's ceilings are twice these estimates (amendment 3)", "arms": arms}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["probe", "freeze", "run", "verify", "dry-run", "estimate"])
    parser.add_argument("directory", type=Path, nargs="*")
    parser.add_argument("--arm", choices=sorted(ARMS))
    parser.add_argument("--estimate-record", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "probe":
        _use(pv2.ADMITTED.pack, dict(base.CONTROLS, reasoning_effort="low"))
        result = asyncio.run(probe(asyncio.run(discover(["claude_code", codex.PROVIDER]))))
        print(json.dumps(result, indent=1, default=str))
        return 1 if any(result["violations"].values()) else 0
    if args.command == "estimate":
        record = estimate(args.directory)
        text = json.dumps(record, indent=1, sort_keys=True) + "\n"
        if args.out:
            args.out.write_text(text)
        print(text)
        return 0
    directory = args.directory[0]
    if args.command == "freeze":
        if args.arm is None:
            parser.error("freeze needs --arm")
        plan = freeze(directory, args.arm, args.estimate_record)
        print(f"froze {sum(len(p['cells']) for p in plan['plans'])} cells in {len(plan['plans'])} plans: {plan['plan_sha256'][:12]}; "
              f"ceilings ${plan['controls']['max_cost_usd_total']} list, {plan['controls']['max_wall_minutes']} minutes")
    elif args.command == "run":
        asyncio.run(run(directory))
    elif args.command == "verify":
        result = verify(directory)
        print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in result.items()}, indent=1))
        return 1 if result["failed"] else 0
    else:
        if not directory.exists():
            freeze(directory, "dry")
        asyncio.run(run(directory))
        failures = v1.dry_run_failures(directory)
        verified = verify(directory)
        print(f"dry run: {len(failures)} failures; {verified['replayed']} receipts replayed offline, {len(verified['failed'])} failed")
        for f in failures[:20]:
            print(" ", f)
        return 1 if failures or verified["failed"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
