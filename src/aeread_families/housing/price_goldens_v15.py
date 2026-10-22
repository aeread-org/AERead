"""The v15 golden-receipt bundle: five kinds of seat-0 play sealed through ``build_v15_setup`` (plan Section 6).

    PYTHONPATH=src python -m aeread_families.housing.price_goldens_v15 --write
    PYTHONPATH=src python -m aeread_families.housing.price_goldens_v15 --check   # verify the published bundle

Each scenario plays one scripted seat-0 policy in both landlord arms of one development world of the goldens identity
(``housing_lemons_price_goldens_v15``, scripted only). It runs through the kernel under the v15 setup: the seat-0
scorer, notice v5, and outside demand from ``price_campaign.make_seat_router``. No provider is called. The plan names
the scripted inspect-then-sign tenant. The provider here answers seat 0 with the scenario's policy instead, so each
row records the policy that actually played, as ``qc_bundle`` does.

| Scenario | Policy | What must hold |
|---|---|---|
| successful | ``inspect_lowball`` | ``ok``; the primary equals the policy's offline measure-v2 net |
| valid_but_poor | ``sign_anything`` | ``ok``; the primary equals its offline net, below ``inspect_then_sign``'s |
| invalid_unauthorized | an unknown listing, a negative or non-finite rent | ``ok``; typed invalid actions counted, each applied as a pass; net $0 |
| malformed | ``inspect_then_sign`` with every commit facing a hold malformed | ``ok``; typed invalid actions; each hold lapses; net minus fees |
| degenerate | ``pass`` | ``ok``; primary $0, the floor reference |

Every receipt is verified, replayed from its sealed events to the same scores, and published with its events.
Receipts and events are run records (ids and times differ between runs), so ``--check`` verifies the published
bundle rather than regenerating it: each receipt reads back canonical and matches its recorded digest, each events
file matches its digest, and every row still meets its scenario's condition.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.receipts import read_evaluation_receipt, verify_evaluation_receipt

from aeread_families.housing import lemons, price_campaign, price_reference, price_seat0, runner
from aeread_families.housing import price_reply_posterior as posterior

CAMPAIGN = "housing_lemons_price_goldens_v15"
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evidence/housing" / CAMPAIGN
ARMS = ("true_cost", "pooled")


def _invalid(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    """Every phase, an action the environment must refuse."""
    round_index = int(observation["round_index"])
    if phase_id == "inspect":
        return {"decision": "inspect", "listing_id": (99, -1, 7)[round_index % 3]}
    if phase_id == "contact":
        return {"decision": "offer", "listing_id": 1, "rent": (-5.0, -1.0, -50.0)[round_index % 3]}
    return lemons._pass(phase_id)


SCENARIOS: tuple[dict[str, Any], ...] = (
    {"scenario_id": "successful", "policy": "inspect_lowball", "world_index": 0},
    {"scenario_id": "valid_but_poor", "policy": "sign_anything", "world_index": 1},
    {"scenario_id": "invalid_unauthorized", "policy": "invalid", "world_index": 2},
    {"scenario_id": "malformed", "policy": "inspect_then_sign_malformed_commit", "world_index": 3},
    {"scenario_id": "degenerate", "policy": "pass", "world_index": 4},
)
POLICIES = {"inspect_lowball": price_reference.inspect_lowball_action, "sign_anything": lemons.sign_anything_action,
            "invalid": _invalid, "inspect_then_sign_malformed_commit": lemons.inspect_then_sign_action,
            "pass": lemons.pass_action}


class ScenarioTenant:
    """Answers seat 0 with the scenario's policy from its observation; scripted, deterministic, no provider call."""

    def __init__(self, policy: str) -> None:
        self.policy = policy

    async def complete(self, request: Any) -> Any:
        payload = json.loads(request.input_text)
        observation, phase_id = payload["observation"], payload["phase_id"]
        result = runner._scripted_result(request, POLICIES[self.policy](observation, phase_id))
        if self.policy.endswith("_malformed_commit") and phase_id == "commit" and observation.get("active_hold") is not None:
            text = "I will sign the hold." if int(observation["round_index"]) == 0 else '{"decision":"walk","hold_id":null}'
            import dataclasses

            return dataclasses.replace(result, output_text=text)
        return result


def offline(seed: int, arm: str, policy: str) -> dict[str, Any]:
    """The same policy in the same world and arm, played offline and scored under measure v2."""
    market, trajectory = posterior.run_recorded(seed, arm, POLICIES[policy])
    scored = posterior.score_market(market, trajectory)
    return {"primary_v2": scored["primary_v2"], "net_realized": scored["net_realized"],
            "inspection_spend": float(market.inspection_spend[price_reference.FOCAL_SEAT])}


async def _cell(contract: Mapping[str, Any], scenario: Mapping[str, Any], arm: str, root: Path) -> dict[str, Any]:
    seed = contract["world_seeds"][scenario["world_index"]]
    setup = price_seat0.build_v15_setup(contract, arm, live=False)
    spec = price_campaign.identity(contract)
    router = price_campaign.make_seat_router(spec, contract, ScenarioTenant(scenario["policy"]), root / "seat_calls.jsonl")
    cell = next(c for c in setup.plan.cells if c.world_seed == seed and c.replicate_index == 0)
    evidence = root / f"{scenario['scenario_id']}__{arm}"
    execution = await execute_plan_cell(
        plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence,
        prompt_sources=setup.prompt_sources,
        providers={"housing_scripted_tenant": router, "housing_scripted_landlord": runner.HousingScriptedLandlordProvider()},
        pricing=setup.pricing, harnesses=setup.harnesses)
    receipt = runner.finalize_housing_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = runner.replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=evidence)
    score = receipt.scores[0]
    seat0 = execution.episode_result.outcome["seat0"]
    events = sorted(evidence.glob("runplan_*/tasks/*/attempts/*/events.jsonl"))
    return {
        "scenario_id": scenario["scenario_id"], "policy": scenario["policy"], "world_seed": seed, "arm": arm,
        "run_plan_id": receipt.run_plan_id, "cell_id": receipt.cell_id, "receipt_sha256": receipt.receipt_sha256,
        "receipt_status": receipt.status, "score_status": score.status,
        "replay_verified": canonical_json_bytes(replayed) == canonical_json_bytes(receipt),
        "primary": None if score.primary is None else score.primary.value,
        "references": {k: v.value for k, v in score.reference_values.items()},
        "invalid_actions": dict(seat0["invalid_actions"]), "inspection_spend": float(seat0["inspection_spend"]),
        "net_realized": seat0["net_realized"], "offline": offline(seed, arm, scenario["policy"]),
        "events_sha256": hashlib.sha256(events[0].read_bytes()).hexdigest() if events else None,
        "_receipt": canonical_json_bytes(receipt) + b"\n", "_events": events[0].read_bytes() if events else b"",
    }


def check_row(row: Mapping[str, Any]) -> list[str]:
    """What each scenario must show; an empty list means it holds."""
    bad = []
    if row["receipt_status"] != "ok" or row["score_status"] != "ok" or not row["replay_verified"]:
        bad.append("receipt not ok or replay differs")
    kind = row["scenario_id"]
    if kind in {"successful", "valid_but_poor", "degenerate"} and not math.isclose(row["primary"], row["offline"]["primary_v2"], abs_tol=0.005):
        bad.append("primary differs from the policy's offline measure-v2 net")
    if kind == "valid_but_poor" and not row["primary"] < row["references"]["comparison_baseline"]:
        bad.append("the poor policy does not score below inspect_then_sign")
    if kind == "invalid_unauthorized" and (sum(row["invalid_actions"].values()) == 0 or row["net_realized"] != 0.0 or row["inspection_spend"] != 0.0):
        bad.append("refused actions were not typed, or they cost or earned something")
    if kind == "malformed" and (not row["invalid_actions"] or not math.isclose(row["primary"], -row["inspection_spend"], abs_tol=0.005)):
        bad.append("malformed commits were not typed, or a hold did not lapse")
    if kind == "degenerate" and row["primary"] != 0.0:
        bad.append("doing nothing does not score the $0 floor")
    return bad


def build() -> dict[str, Any]:
    contract = price_campaign.load_contract(ROOT / "configs" / f"{CAMPAIGN}.json")
    with tempfile.TemporaryDirectory() as tmp:
        rows = [asyncio.run(_cell(contract, s, arm, Path(tmp))) for s in SCENARIOS for arm in ARMS]
    failures = {f"{r['scenario_id']}__{r['arm']}": check_row(r) for r in rows if check_row(r)}
    if failures:
        raise AssertionError(f"golden scenarios failed: {failures}")
    report = {
        "bundle_id": CAMPAIGN, "plan": "docs/families/housing/price_confirmatory_v15_plan.md, Section 6 and amendment 1",
        "contract_sha256": hashlib.sha256(canonical_json_bytes(contract)).hexdigest(),
        "scorer_id": price_seat0.SCORER_ID, "scorer_implementation_sha256": price_seat0.implementation_digest(),
        "cost_usd": 0.0, "rows": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
    }
    files = {"reports/goldens.json": (json.dumps(report, indent=1, sort_keys=True) + "\n").encode("utf-8")}
    for r in rows:
        name = f"{r['scenario_id']}__{r['arm']}"
        files[f"receipts/{name}.json"] = r["_receipt"]
        files[f"trajectories/{name}_events.jsonl"] = r["_events"]
    return files


def verify(out: Path = OUT) -> list[str]:
    """Problems with the published bundle; an empty list means it verifies."""
    report = json.loads((out / "reports/goldens.json").read_text())
    problems = []
    for row in report["rows"]:
        name = f"{row['scenario_id']}__{row['arm']}"
        receipt = read_evaluation_receipt(out / "receipts" / f"{name}.json")
        if receipt["receipt_sha256"] != row["receipt_sha256"]:
            problems.append(f"{name}: receipt digest differs from the report")
        events = (out / "trajectories" / f"{name}_events.jsonl").read_bytes()
        if not events or hashlib.sha256(events).hexdigest() != row["events_sha256"]:
            problems.append(f"{name}: events file missing or differs from its digest")
        problems += [f"{name}: {p}" for p in check_row(row)]
    if len(report["rows"]) != len(SCENARIOS) * len(ARMS):
        problems.append("the bundle does not hold every scenario in both arms")
    return problems


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)
    if args.check and not args.write:
        problems = verify(out)
        print("check:", "ok" if not problems else problems)
        return 1 if problems else 0
    files = build()
    if args.write:
        for name, data in files.items():
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(data)
        print(f"wrote {len(files)} files to {out}")
    if args.check:
        problems = verify(out)
        print("check:", "ok" if not problems else problems)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["CAMPAIGN", "SCENARIOS", "ScenarioTenant", "build", "check_row", "offline", "verify"]
