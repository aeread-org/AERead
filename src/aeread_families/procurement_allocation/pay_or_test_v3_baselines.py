"""Pay or test version 3's free baselines played through the kernel on the declared worlds (qc.md 8.2, Gate 3, check 5).

    PYTHONPATH=src python -m aeread_families.procurement_allocation.pay_or_test_v3_baselines RUN_ROOT

Five scripted policies, valued exactly by ``pay_or_test_v3_reference``, play each of the 20 worlds of
``pay_or_test_v3_confirm`` through the kernel scheduler with the scripted response provider (no model call): the best
policy, the one-step rule, the look-up-first rule, paying the premium, and the kind-blind shortcut. Each episode's
receipt is finalized, replayed against its live receipt, and its margin checked against the reference's own play of the
same actions. The run root gets a ``model_plan.json`` and a ``summary.json`` in the shape the version 3 drivers write,
so ``pay_or_test_v3_publication`` publishes it as a kernel bundle and ``aeread verify-replay`` re-drives it.

The rule is the episode attempt's ordinal (0 to 4, in ``RULES`` order), so the five plays of one world are distinct
episodes of the one plan cell that world has.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import finalize_family_execution, replay_family_receipt
from aeread.shared_runner.task.execution import execute_plan_cell

from . import pay_or_test_v3_case_matrix as pack_module
from . import pay_or_test_v3_reference as reference
from . import pay_or_test_v3_runner as runner
from .pay_or_test_reference import final_margin
from .pay_or_test_v3_prompt import PAY_OR_TEST_V3_PROMPT, PROMPT_ID, TREATMENT_ID
from .runner import SequenceResponseProvider

CAMPAIGN_ID = "procurement_allocation_pay_or_test_v3_confirm_v3_scripted_baselines_v1"
PACK = pack_module.CONFIRM_PACK_ID
#: (name, rule key in ``reference.RULES``; None is the best policy).
RULES = (("best_policy", None), ("one_step_value", "one_step_value"), ("look_up_first", "look_up_first"),
         ("pay_premium", "pay_premium"), ("cheapest_sample_first", "cheapest_sample_first"))


def build_setup(case_path: Path | str):
    """The kernel setup every baseline episode of a world is sealed under."""
    return runner.build_offline_setup(case_path=case_path, prompt=PAY_OR_TEST_V3_PROMPT, prompt_id=PROMPT_ID)


def model_plan() -> dict[str, Any]:
    cases = sorted(pack_module.case_paths(split=PACK))
    plan = {
        "schema_version": "aeread.procurement_pay_or_test_v3_baselines_plan/0.1", "kind": "scripted_baselines",
        "campaign_id": CAMPAIGN_ID, "claim_status": "baseline_receipts",
        "claim_scope": "the free baselines' episodes through the kernel, sealed and replayable (qc.md 8.2, Gate 3, "
                       "check 5); their values are the reference's exact ones, not a result",
        "pack": PACK, "pack_json_sha256": hashlib.sha256((pack_module.pack_root(PACK) / "pack.json").read_bytes()).hexdigest(),
        "prompt": {"prompt_id": PROMPT_ID, "sha256": hashlib.sha256(PAY_OR_TEST_V3_PROMPT.encode("utf-8")).hexdigest(),
                   "treatment_id": TREATMENT_ID},
        "rules": [name for name, _ in RULES], "inference_seeds": list(range(len(RULES))),
        "inference_seed_meaning": "the rule's index in rules, which is the episode attempt's ordinal",
        "planned_trajectory_count": len(cases) * len(RULES), "provider": "scripted_sequence",
        "reference": {"module": "src/aeread_families/procurement_allocation/pay_or_test_v3_reference.py",
                      "sha256": hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest()},
        "driver": {"path": "src/aeread_families/procurement_allocation/pay_or_test_v3_baselines.py",
                   "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


async def _play(case_path: Path, ordinal: int, rule: str | None, evidence_root: Path) -> dict[str, Any]:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    actions = reference.play(case["payload"], reference.RULES[rule] if rule else None)
    setup = build_setup(case_path)
    provider = SequenceResponseProvider([canonical_json_bytes(a).decode("utf-8") for a in actions])
    execution = await execute_plan_cell(
        plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry, evidence_root=evidence_root,
        prompt_sources=setup.prompt_sources, providers={"fake": provider}, pricing=setup.pricing,
        episode_attempt_ordinal=ordinal, harnesses=setup.harnesses)
    if not provider.exhausted:
        raise RuntimeError(f"{case_path.stem} {rule}: the episode ended before the policy's last action")
    receipt = finalize_family_execution(setup=setup, execution=execution)
    replayed = replay_family_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
    if canonical_json_bytes(replayed) != canonical_json_bytes(receipt):
        raise RuntimeError(f"{case_path.stem} {rule}: the replayed receipt differs")
    outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
    expected = final_margin(reference.Reference(case["payload"]), reference.run(case["payload"], actions))
    if abs(float(outcome["contribution_margin_usd"]) - expected) > 1e-6:
        raise RuntimeError(f"{case_path.stem} {rule}: the kernel's margin is not the reference's play of the same actions")
    return {"case_id": case["case_id"], "inference_seed": ordinal, "rule": RULES[ordinal][0], "status": "completed",
            "decision": outcome["decision"], "termination_reason": outcome["termination_reason"],
            "contribution_margin_usd": float(outcome["contribution_margin_usd"]), "receipt_sha256": receipt.receipt_sha256}


def run(run_root: Path | str) -> dict[str, Any]:
    root = Path(run_root)
    if (root / "summary.json").exists():
        raise FileExistsError(f"{root} already holds a run")
    plan = model_plan()
    root.mkdir(parents=True, exist_ok=True)
    (root / "model_plan.json").write_bytes(canonical_json_bytes(plan) + b"\n")
    rows = []
    for case_path in sorted(pack_module.case_paths(split=PACK)):
        for ordinal, (_name, rule) in enumerate(RULES):
            evidence = root / "executions" / case_path.stem / f"rule_{ordinal}"
            rows.append(asyncio.run(_play(case_path, ordinal, rule, evidence)))
    summary = {"schema_version": "aeread.procurement_pay_or_test_v3_baselines_summary/0.1", "plan": plan, "halted": None,
               "rows": rows}
    summary["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(summary)).hexdigest()
    (root / "summary.json").write_bytes(canonical_json_bytes(summary) + b"\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args(argv)
    summary = run(args.run_root)
    print(json.dumps({"rows": len(summary["rows"]), "plan_sha256": summary["plan"]["plan_sha256"]}))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI
    raise SystemExit(main())
