from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.model_campaign as campaign_module
from aeread.shared_runner.task.execution import ProviderFailure

from aeread_families.procurement_allocation.model_campaign import (
    CAMPAIGN_ID,
    GLM_MORPH_CANDIDATE,
    conservative_cost_ceiling,
    derive_inference_seeds,
    planned_model_qualification,
    publish_model_qualification,
    run_model_qualification,
    summarize_rows,
)
from aeread_families.procurement_allocation.case_matrix import (
    CASE_SLUGS,
    CASE_VARIANCE_PATHS,
    GROUNDING_SELECTION,
    build_case_matrix,
    validate_grounding_snapshot,
)
from aeread_families.procurement_allocation.environment import (
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.runner import (
    CASE_PATH,
    SequenceResponseProvider,
)


def _response(action: dict) -> str:
    return json.dumps(action, sort_keys=True)


def _optimal_script() -> list[str]:
    negotiated_terms = {
        "switch_reliable": (0.082, 30),
        "oled_reliable": (1.72, 45),
        "charger_reliable": (0.55, 45),
    }
    actions: list[dict] = []
    for supplier_id, (unit_price, refund_window) in negotiated_terms.items():
        actions.extend(
            [
                {
                    "action": "request_quote",
                    "supplier_id": supplier_id,
                    "message": "Please issue a formal quote with full commercial terms.",
                },
                {
                    "action": "counter_offer",
                    "supplier_id": supplier_id,
                    "offer_id": f"offer_{supplier_id}_v1",
                    "proposal": {
                        "unit_price_usd": unit_price,
                        "moq": 10,
                        "payment_terms_days": 60,
                        "refund_window_days": refund_window,
                        "return_freight_payer": "supplier",
                    },
                    "message": "Please formalize these commercial terms.",
                },
                {
                    "action": "request_sample",
                    "supplier_id": supplier_id,
                    "message": "Please provide the exact-variant qualification sample.",
                },
            ]
        )
    actions.append(
        {
            "action": "submit_award",
            "award_lines": [
                {"offer_id": f"offer_{supplier_id}_v2", "quantity": 20}
                for supplier_id in negotiated_terms
            ],
        }
    )
    return [_response(action) for action in actions]


def test_model_plan_holds_harness_fixed_and_separates_case_variance() -> None:
    seeds = derive_inference_seeds(master_seed=20260902, count=3)
    plan = planned_model_qualification(
        case_paths=CASE_VARIANCE_PATHS,
        inference_seeds=seeds,
        max_parallel_cells=2,
    )

    assert len(seeds) == len(set(seeds)) == 3
    assert seeds == derive_inference_seeds(master_seed=20260902, count=3)
    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["independent_case_count"] == 6
    assert plan["planned_trajectory_count"] == 18
    assert plan["harness"] == "minimal_chat/1.0 (fixed transport; not an estimand)"
    assert plan["provider"] == "Morph"
    assert plan["revision"] == "z-ai/glm-5.3-flash-20260826"
    assert plan["pricing_id"] == "openrouter_2026-09-02_glm53_flash_morph"
    assert plan["plan_sha256"]
    assert plan["conservative_cost_ceiling_usd"] == pytest.approx(
        conservative_cost_ceiling(case_count=6, seed_count=3)
    )


def test_case_matrix_is_grounded_distinct_and_objectively_scorable() -> None:
    grounding = validate_grounding_snapshot()
    cases = build_case_matrix()

    assert tuple(case["case_id"].rsplit(".", 1)[-1] for case in cases) == CASE_SLUGS
    assert set(grounding) == set(GROUNDING_SELECTION)
    assert len({tuple(case["payload"]["objective"]["bom"]) for case in cases}) == 6
    assert len({case["world_seed"] for case in cases}) == 6
    for path, raw in zip(CASE_VARIANCE_PATHS, cases, strict=True):
        assert json.loads(path.read_text(encoding="utf-8")) == raw
        case = campaign_module.load_case(path)
        bound = solve_full_information_upper_bound(case.payload)
        assert (
            bound.contribution_margin_usd > case.payload["objective"]["defer_value_usd"]
        )
        assert bound.actions_required <= 10


def test_summary_keeps_provider_failure_out_of_procurement_means() -> None:
    completed = {
        "case_id": "case-a",
        "inference_seed": 1,
        "status": "completed",
        "feasible": True,
        "completed_kits": 19,
        "contribution_margin_usd": 12.5,
        "regret_to_upper_bound_usd": 3.5,
        "violations": [],
        "action_trace": [
            {"action": "request_quote", "supplier_id": "supplier-a"},
            {"action": "submit_award"},
        ],
        "elapsed_seconds": 2.0,
        "cost_usd": 0.001,
        "cached_input_tokens": 100,
        "receipt_replayed": True,
    }
    failed = {
        "case_id": "case-a",
        "inference_seed": 2,
        "status": "operational_failure",
        "failure_condition": "rate_limit",
    }

    summary = summarize_rows(
        (completed, failed),
        planned_trajectory_count=2,
        independent_case_count=1,
    )

    assert summary["reliability"] == pytest.approx(0.5)
    assert summary["operational_failure_count"] == 1
    assert summary["unattempted_trajectory_count"] == 0
    assert summary["mean_contribution_margin_usd"] == pytest.approx(12.5)
    assert summary["feasible_rate_among_completed"] == pytest.approx(1.0)
    assert summary["readiness"] == {
        "execution_qualified": False,
        "case_variance_ready": False,
        "case_variance_minimum_independent_cases": 6,
    }


def test_provider_free_model_campaign_replays_and_resumes(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / CAMPAIGN_ID / "attempt_001"
    providers: list[SequenceResponseProvider] = []

    def provider_factory() -> SequenceResponseProvider:
        provider = SequenceResponseProvider(_optimal_script())
        providers.append(provider)
        return provider

    def preflight(_candidate) -> dict:
        return {
            "route_verified": True,
            "model": GLM_MORPH_CANDIDATE.route.revision,
            "provider": "Morph",
        }

    artifact = asyncio.run(
        run_model_qualification(
            run_root=run_root,
            case_paths=(CASE_PATH,),
            inference_seeds=(231,),
            max_spend_usd=0.02,
            max_parallel_cells=1,
            provider_factory=provider_factory,
            preflight_fn=preflight,
        )
    )

    assert len(providers) == 1
    assert providers[0].exhausted
    assert artifact["summary"]["readiness"] == {
        "execution_qualified": True,
        "case_variance_ready": False,
        "case_variance_minimum_independent_cases": 6,
    }
    assert artifact["rows"][0]["feasible"] is True
    assert artifact["rows"][0]["completed_kits"] == 19
    assert artifact["rows"][0]["receipt_replayed"] is True
    assert (run_root / "model_plan.json").is_file()
    assert (run_root / "summary.json").is_file()

    evidence_root = tmp_path / "evidence" / CAMPAIGN_ID
    published = publish_model_qualification(
        run_root=run_root,
        publication_root=evidence_root,
        supplemental_reports={"reports/paired_invariance.json": {"paired": True}},
    )
    assert (evidence_root / "README.md").is_file()
    assert (evidence_root / "publication_manifest.json").is_file()
    assert (evidence_root / "reports" / "qualification.json").is_file()
    assert (evidence_root / "reports" / "paired_invariance.json").is_file()
    assert (evidence_root / "tables" / "fact_manifest.json").is_file()
    assert published["review"]["rows"] == artifact["rows"]
    assert "reports/paired_invariance.json" in published["manifest"]["artifacts"]
    serialized = (evidence_root / "reports" / "qualification.json").read_text()
    assert "raw_response" not in serialized
    assert "OPENROUTER_API_KEY" not in serialized
    assert "event logs" in serialized
    assert published["review"]["publisher_implementation"]["module"] == (
        "aeread_families.procurement_allocation.model_campaign"
    )
    assert published["review"]["publisher_implementation"]["source_sha256"] == (
        hashlib.sha256(Path(campaign_module.__file__).read_bytes()).hexdigest()
    )

    def should_not_run():
        raise AssertionError("a sealed result must not call the provider on resume")

    resumed = asyncio.run(
        run_model_qualification(
            run_root=run_root,
            case_paths=(CASE_PATH,),
            inference_seeds=(231,),
            max_spend_usd=0.02,
            max_parallel_cells=1,
            resume=True,
            provider_factory=should_not_run,
            preflight_fn=lambda _candidate: should_not_run(),
        )
    )
    assert resumed["rows"] == artifact["rows"]
    assert resumed["preflight"] == artifact["preflight"]


def test_campaign_aborts_after_first_operational_failure_and_cannot_resume(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs" / CAMPAIGN_ID / "attempt_001"
    providers = []

    class RateLimitedProvider:
        async def complete(self, _request):
            raise ProviderFailure(
                "rate_limit", "upstream overloaded", retryable=True, status_code=429
            )

    def provider_factory():
        provider = RateLimitedProvider()
        providers.append(provider)
        return provider

    artifact = asyncio.run(
        run_model_qualification(
            run_root=run_root,
            case_paths=(CASE_PATH,),
            inference_seeds=(231, 232),
            max_spend_usd=0.03,
            max_parallel_cells=1,
            abort_on_operational_failure=True,
            provider_factory=provider_factory,
            preflight_fn=lambda _candidate: {"route_verified": True},
        )
    )

    assert len(providers) == 1
    assert len(artifact["rows"]) == 1
    assert artifact["rows"][0]["failure_condition"] == "rate_limit"
    assert artifact["summary"]["operational_failure_count"] == 1
    assert artifact["summary"]["unattempted_trajectory_count"] == 1
    assert artifact["summary"]["readiness"]["execution_qualified"] is False

    with pytest.raises(ValueError, match="fresh attempt root"):
        asyncio.run(
            run_model_qualification(
                run_root=run_root,
                case_paths=(CASE_PATH,),
                inference_seeds=(231, 232),
                max_spend_usd=0.03,
                max_parallel_cells=1,
                resume=True,
                abort_on_operational_failure=True,
                provider_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("provider must not run")
                ),
                preflight_fn=lambda _candidate: {"route_verified": True},
            )
        )


def test_live_output_requires_canonical_runs_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be under the ignored runs/"):
        asyncio.run(
            run_model_qualification(
                run_root=tmp_path / "evidence" / "procurement",
                case_paths=(CASE_PATH,),
                inference_seeds=(231,),
                max_spend_usd=0.02,
                provider_factory=lambda: SequenceResponseProvider(_optimal_script()),
                preflight_fn=lambda _candidate: {"route_verified": True},
            )
        )

    with pytest.raises(ValueError, match="must be under the ignored runs/"):
        asyncio.run(
            run_model_qualification(
                run_root=tmp_path / "outputs" / "procurement",
                case_paths=(CASE_PATH,),
                inference_seeds=(231,),
                max_spend_usd=0.02,
                provider_factory=lambda: SequenceResponseProvider(_optimal_script()),
                preflight_fn=lambda _candidate: {"route_verified": True},
            )
        )
