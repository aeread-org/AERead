"""QC layer: the failures that digest and contract tests cannot catch.

The existing suites are strong on digests, frozen plans, and receipt replay. Three
defects fixed on 2026-09-05 passed every one of them:

- the confirmation rule guarded terminal feasibility, which counts an explicit
  defer as a success, so a treatment that deferred more could pass while earning
  nothing (design review defect 5);
- the full-information solver was exponential and hung rather than failing, which
  silently made fine-grained quantity worlds unauthorable (defect 7);
- a conftest edit dropped a function header and broke collection for the whole
  repository, which only a full-suite run surfaced.

Each class of defect gets a cheap standing test here:

1. **Adversarial guardrail tests** — synthesize an arm that games the guarded
   metric and assert the rule rejects it. A metric is only a guardrail if some
   behaviour fails it.
2. **Outcome invariants** — properties that must hold for every row ever
   produced, checked against all published evidence.
3. **Metamorphic tests** — a transformation that must not change the economics
   (opaque relabelling) must not change the bound.
4. **Determinism** — the same case and trace must score identically twice.
5. **Import smoke** — every family module imports, in seconds rather than the
   36 minutes a full suite costs.
"""

from __future__ import annotations

import glob
import importlib
import json
import pkgutil
from pathlib import Path

import pytest

import aeread_families.procurement_allocation as family
from aeread_families.procurement_allocation.confirmatory_v2_case_matrix import (
    build_confirmatory_case_matrix as build_holdout,
)
from aeread_families.procurement_allocation.environment import (
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.regret_decomposition import (
    BUNDLE_REPORTS,
    case_path_for_id,
    replay_action_trace,
    verified_bundle_report,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _published_rows() -> list[dict]:
    rows: list[dict] = []
    for bundle in BUNDLE_REPORTS:
        report, _ = verified_bundle_report(REPOSITORY_ROOT / bundle.report_path)
        rows.extend(report["rows"])
    for pattern in (
        "evidence/procurement_allocation_glm53_flash_parasail_pre_award_check_v1/reports/*_worksheet.json",
        "evidence/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v*/reports/*_worksheet.json",
    ):
        for path in glob.glob(str(REPOSITORY_ROOT / pattern)):
            rows.extend(json.loads(Path(path).read_text(encoding="utf-8"))["rows"])
    return rows


# ---------------------------------------------------------------- invariants


def test_every_published_row_has_non_negative_regret() -> None:
    """No award may beat the full-information bound.

    A negative regret would mean the oracle is not an upper bound, which would
    invalidate every campaign that reports regret.
    """
    rows = _published_rows()
    assert rows, "no published rows found; the QC layer would be vacuous"
    for row in rows:
        assert row["regret_to_upper_bound_usd"] >= -1e-9, row["case_id"]
        assert row["contribution_margin_usd"] <= row["upper_bound_usd"] + 1e-9


def test_a_feasible_award_is_always_terminally_feasible() -> None:
    """`feasible_award` must be a strict subset of `feasible`.

    The two fields disagree exactly on deferrals, which is the distinction the
    confirmation guardrail depends on.
    """
    for row in _published_rows():
        if row.get("feasible_award"):
            assert row["feasible"] is True, row["case_id"]
            assert row["decision"] == "award", row["case_id"]


def test_a_defer_never_completes_a_kit() -> None:
    for row in _published_rows():
        if row["decision"] == "defer":
            assert row["completed_kits"] == 0, row["case_id"]
            assert row.get("feasible_award", False) is False, row["case_id"]


# --------------------------------------------------------------- metamorphic


def test_opaque_relabelling_does_not_change_the_bound() -> None:
    """Renaming and reordering suppliers must leave the economics identical.

    This is what makes the labeled and opaque surfaces comparable at all; if it
    ever fails, every surface-gap number in the family is meaningless.
    """
    labeled = {
        case["case_id"].rsplit(".", 1)[-1]: case
        for case in build_holdout(surface="labeled")
    }
    opaque = {
        case["case_id"].rsplit(".", 1)[-1]: case
        for case in build_holdout(surface="opaque")
    }
    assert set(labeled) == set(opaque)
    for slug, left in labeled.items():
        right = opaque[slug]
        assert left["world_seed"] == right["world_seed"]
        left_bound = solve_full_information_upper_bound(left["payload"])
        right_bound = solve_full_information_upper_bound(right["payload"])
        assert left_bound.contribution_margin_usd == pytest.approx(
            right_bound.contribution_margin_usd, abs=1e-9
        ), slug
        assert left_bound.completed_kits == right_bound.completed_kits, slug
        assert left_bound.actions_required == right_bound.actions_required, slug


# -------------------------------------------------------------- determinism


def test_scoring_a_trace_twice_gives_the_same_outcome() -> None:
    """Replay must be deterministic, or receipt verification proves nothing."""
    checked = 0
    for bundle in BUNDLE_REPORTS[:2]:
        report, _ = verified_bundle_report(REPOSITORY_ROOT / bundle.report_path)
        for row in report["rows"][:4]:
            path = case_path_for_id(row["case_id"], repository_root=REPOSITORY_ROOT)
            payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
            first = replay_action_trace(payload, row["action_trace"])["outcome"]
            second = replay_action_trace(payload, row["action_trace"])["outcome"]
            assert first == second, row["case_id"]
            checked += 1
    assert checked >= 4


# ------------------------------------------------------------- import smoke


def test_every_family_module_imports() -> None:
    """Catch a syntax or import break in seconds.

    A conftest edit on 2026-09-05 dropped a function header and broke collection
    for the entire repository; only a 36-minute full-suite run surfaced it.
    """
    failures: list[str] = []
    for module in pkgutil.iter_modules(family.__path__):
        if module.name == "__main__":
            # Importing a __main__ module runs its argument parser by design.
            continue
        name = f"{family.__name__}.{module.name}"
        try:
            importlib.import_module(name)
        except Exception as error:  # noqa: BLE001 - the failure is the result
            failures.append(f"{name}: {type(error).__name__}: {error}")
    assert not failures, "modules failed to import:\n" + "\n".join(failures)


def test_the_repository_conftest_parses() -> None:
    import ast

    source = (REPOSITORY_ROOT / "conftest.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "pytest_terminal_summary" in functions


# ------------------------------------------------- adversarial guardrail tests


def _arm(root: Path, *, name: str, plan: dict, defer_everything: bool) -> None:
    """Write a synthetic arm.

    The treatment arm optionally defers every row. A deferral is terminally
    feasible and earns nothing, which is precisely the behaviour a guardrail on
    terminal feasibility would wave through.
    """
    import hashlib

    from aeread.shared_runner.run.resolver import canonical_json_bytes

    surface = "labeled" if name.startswith("labeled") else "opaque"
    treatment = name.endswith("treatment")
    defers = treatment and defer_everything
    rows = []
    for pair in plan["world_pairs"]:
        for seed in plan["inference_seeds"]:
            row = {
                "case_id": pair[f"{surface}_case_id"],
                "case_content_sha256": pair[f"{surface}_case_content_sha256"],
                "inference_seed": seed,
                "status": "completed",
                "decision": "defer" if defers else "award",
                "termination_reason": "deferred" if defers else "submitted",
                # A defer is terminally feasible and never a feasible award.
                "feasible": True,
                "feasible_award": not defers,
                "completed_kits": 0 if defers else (18 if treatment else 16),
                "contribution_margin_usd": 0.0 if defers else (10.0 if treatment else 5.0),
                "upper_bound_usd": 20.0,
                "regret_to_upper_bound_usd": 20.0 if defers else (10.0 if treatment else 15.0),
                "violations": [],
                "elapsed_environment_days": 4,
                "action_count": 5,
                "action_trace": [{"ordinal": 1, "action": "request_quote"}],
                "elapsed_seconds": 1.0,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 20,
                "cost_usd": 0.001,
                "provider_call_count": 5,
                "runner_retry_count": 0,
                "retry_condition_counts": {},
                "resolved_models": ["z-ai/glm-5.3-flash-20260826"],
                "receipt_sha256": "a" * 64,
                "receipt_replayed": True,
                "replay_level": "provider_response",
            }
            row["result_sha256"] = hashlib.sha256(
                canonical_json_bytes(row)
            ).hexdigest()
            rows.append(row)
    artifact = {
        "schema_version": "aeread.procurement_allocation_model_qualification/0.1",
        "plan": plan["arms"][name],
        "preflight": {
            "candidate_id": "glm53_flash_parasail",
            "model": "z-ai/glm-5.3-flash",
            "revision": "z-ai/glm-5.3-flash-20260826",
            "route_provider": "Parasail",
        },
        "summary": {
            "planned_trajectory_count": len(rows),
            "row_count": len(rows),
            "unattempted_trajectory_count": 0,
            "completed_trajectory_count": len(rows),
            "operational_failure_count": 0,
            "total_cost_usd": len(rows) * 0.001,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    path = root / "arms" / name / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(artifact) + b"\n")


def _canary(root: Path, condition: str, plan: dict) -> None:
    import hashlib

    from aeread.shared_runner.run.resolver import canonical_json_bytes

    prompts = plan["prompts"]
    value = {
        "schema_version": "aeread.provider_admission_canary/0.1",
        "campaign_id": plan["campaign_id"],
        "condition": condition,
        "status": "admitted",
        "scored": False,
        "prompt_id": (
            prompts["control_prompt_id"]
            if condition == "control"
            else prompts["treatment_prompt_id"]
        ),
        "prompt_sha256": (
            prompts["control_sha256"]
            if condition == "control"
            else prompts["treatment_sha256"]
        ),
        "model": "z-ai/glm-5.3-flash",
        "revision": "z-ai/glm-5.3-flash-20260826",
        "route_provider": "Parasail",
        "resolved_model": "z-ai/glm-5.3-flash-20260826",
        "cost_usd": 0.001,
    }
    value["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(value)
    ).hexdigest()
    path = root / "canaries" / f"{condition}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def test_an_arm_that_defers_everything_cannot_pass_the_guardrail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The test that would have caught design-review defect 5.

    A treatment that defers every row earns nothing, yet every deferral is
    terminally feasible. Guarding terminal feasibility would score this arm as
    non-inferior and, because a deferral's regret is the whole bound, only the
    regret check would stop it. Guarding `feasible_award` rejects it outright.

    A metric is only a guardrail if some behaviour fails it; this pins that.
    """
    import aeread_families.procurement_allocation.pre_award_confirmatory_campaign as campaign

    from aeread.shared_runner.run.resolver import canonical_json_bytes

    monkeypatch.setattr(campaign, "BOOTSTRAP_RESAMPLES", 500)
    plan = campaign.build_plan()
    root = tmp_path / "runs" / "procurement_allocation" / plan["campaign_id"] / "a1"
    root.mkdir(parents=True)
    (root / "campaign_plan.json").write_bytes(canonical_json_bytes(plan) + b"\n")
    for name in plan["arm_execution_order"]:
        _arm(root, name=name, plan=plan, defer_everything=True)
    _canary(root, "control", plan)
    _canary(root, "treatment", plan)

    comparison = campaign.build_confirmatory_comparison(run_root=root)

    guarded = comparison["effects"]["overall_treatment_minus_control"]["feasible_award"]
    terminal = comparison["effects"]["overall_treatment_minus_control"]["feasible"]
    # Terminal feasibility is blind to the behaviour: every row is "feasible".
    assert terminal["world_cluster_mean"] == pytest.approx(0.0)
    # The guarded metric sees it: every treatment row lost its award.
    assert guarded["world_cluster_mean"] == pytest.approx(-1.0)
    assert comparison["confirmation"]["status"] != "supported"
    assert (
        comparison["confirmation"]["checks"][
            "feasible_award_noninferiority_lower_at_least_minus_0_05"
        ]
        is False
    )
