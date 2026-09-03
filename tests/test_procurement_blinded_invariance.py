from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation.blinded_invariance import (
    BASELINE_CAMPAIGN_ID,
    CAMPAIGN_ID,
    PAIRED_INFERENCE_SEEDS,
    build_paired_comparison,
    run_admission_canary,
)
from aeread_families.procurement_allocation.case_matrix import (
    BLINDED_CASE_PATHS,
    CASE_SLUGS,
    build_blinded_case_matrix,
    build_case_matrix,
)
from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider


def _supplier_signature(supplier: dict) -> bytes:
    projected = copy.deepcopy(supplier)
    projected.pop("supplier_id")
    projected["listing"].pop("supplier_name")
    return canonical_json_bytes(projected)


def test_blinded_cases_are_exact_economic_mirrors_with_opaque_reordered_labels() -> (
    None
):
    baseline = build_case_matrix()
    blinded = build_blinded_case_matrix()
    forbidden = (
        "value",
        "express",
        "assured",
        "lot",
        "prepay",
        "net",
        "near",
        "exact",
        "risky",
        "service",
    )

    assert len(baseline) == len(blinded) == 6
    for source, mirror, path in zip(baseline, blinded, BLINDED_CASE_PATHS, strict=True):
        assert json.loads(path.read_text(encoding="utf-8")) == mirror
        assert mirror["case_id"] == source["case_id"].replace(".dev.", ".blinded_v3.")
        assert mirror["split"] == "blinded_v3"
        assert mirror["world_seed"] == source["world_seed"]
        assert mirror["payload"]["objective"] == source["payload"]["objective"]
        assert mirror["payload"]["interaction"] == source["payload"]["interaction"]
        assert mirror["payload"]["policy"] == source["payload"]["policy"]

        source_signatures = [
            _supplier_signature(supplier) for supplier in source["payload"]["suppliers"]
        ]
        mirror_signatures = [
            _supplier_signature(supplier) for supplier in mirror["payload"]["suppliers"]
        ]
        assert sorted(source_signatures) == sorted(mirror_signatures)
        assert source_signatures != mirror_signatures
        for supplier in mirror["payload"]["suppliers"]:
            visible_identity = f"{supplier['supplier_id']} {supplier['listing']['supplier_name']}".lower()
            assert supplier["supplier_id"].startswith("supplier_")
            assert not any(token in visible_identity for token in forbidden)

        source_case = CaseManifest.from_dict(source)
        mirror_case = CaseManifest.from_dict(mirror)
        source_bound = solve_full_information_upper_bound(source_case.payload)
        mirror_bound = solve_full_information_upper_bound(mirror_case.payload)
        assert (
            mirror_bound.contribution_margin_usd == source_bound.contribution_margin_usd
        )
        assert mirror_bound.completed_kits == source_bound.completed_kits
        assert mirror_bound.cash_spend_usd == source_bound.cash_spend_usd
        assert mirror_bound.actions_required == source_bound.actions_required
        assert mirror_bound.elapsed_days == source_bound.elapsed_days

        plugin = ProcurementAllocationPlugin()
        state = plugin.initial_state(mirror_case.payload, run=None)
        observation = plugin.observe(
            mirror_case.payload, state, "buyer", plugin.phases(mirror_case.payload)[0]
        )
        assert "private_terms" not in json.dumps(observation, sort_keys=True)


def _write_artifact(
    run_root: Path, *, campaign_id: str, split: str, margin_delta: float
) -> None:
    rows = []
    for slug in CASE_SLUGS:
        for seed in PAIRED_INFERENCE_SEEDS:
            margin = 10.0 + margin_delta
            row = {
                "case_id": f"procurement_allocation_v1.{split}.{slug}",
                "case_content_sha256": hashlib.sha256(
                    f"{split}:{slug}".encode()
                ).hexdigest(),
                "inference_seed": seed,
                "status": "completed",
                "feasible": margin_delta == 0.0,
                "completed_kits": 20 if margin_delta == 0.0 else 18,
                "contribution_margin_usd": margin,
                "upper_bound_usd": 20.0,
                "regret_to_upper_bound_usd": 20.0 - margin,
                "receipt_replayed": True,
            }
            row["result_sha256"] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            rows.append(row)
    plan = {
        "campaign_id": campaign_id,
        "inference_seeds": list(PAIRED_INFERENCE_SEEDS),
        "model": "z-ai/glm-5.3-flash",
        "revision": "z-ai/glm-5.3-flash-20260826",
        "provider": "Morph",
        "quantization": "fp8",
        "harness": "minimal_chat/1.0 (fixed transport; not an estimand)",
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    artifact = {
        "plan": plan,
        "summary": {
            "feasible_count": 18 if margin_delta == 0.0 else 0,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    run_root.mkdir(parents=True)
    (run_root / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def test_paired_comparison_separates_label_sensitivity_from_execution_validity(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    blinded_root = tmp_path / "blinded"
    _write_artifact(
        baseline_root,
        campaign_id=BASELINE_CAMPAIGN_ID,
        split="dev",
        margin_delta=0.0,
    )
    _write_artifact(
        blinded_root,
        campaign_id=CAMPAIGN_ID,
        split="blinded_v3",
        margin_delta=-2.0,
    )

    comparison = build_paired_comparison(
        baseline_run_root=baseline_root,
        blinded_run_root=blinded_root,
    )

    assert comparison["summary"]["pair_count"] == 18
    assert comparison["summary"]["feasibility_transition_counts"] == {"pass_fail": 18}
    assert comparison["summary"]["mean_contribution_margin_delta_usd"] == -2.0
    assert comparison["integrity"] == {
        "route_and_harness_match": True,
        "paired_inference_seeds_match": True,
        "pair_identities_match": True,
        "upper_bounds_invariant": True,
    }
    assert comparison["readiness"]["paired_invariance_qualified"] is True
    assert comparison["artifact_sha256"]


def test_admission_canary_uses_real_request_shape_and_is_reusable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs" / "campaign" / "admission_canary.json"
    provider = SequenceResponseProvider(
        (json.dumps({"action": "inquire", "supplier_id": "supplier_test"}),)
    )

    canary = asyncio.run(
        run_admission_canary(path=path, provider_factory=lambda: provider)
    )

    assert canary["status"] == "admitted"
    assert canary["scored"] is False
    assert canary["structured_action"] == "inquire"
    assert canary["request_sha256"] == provider.requests[0].request_sha256
    assert len(provider.requests[0].input_text) > 500
    assert provider.requests[0].output_schema is not None
    assert "raw_response" not in path.read_text(encoding="utf-8")

    reused = asyncio.run(
        run_admission_canary(
            path=path,
            provider_factory=lambda: (_ for _ in ()).throw(
                AssertionError("a sealed canary must not call the provider")
            ),
        )
    )
    assert reused == canary
