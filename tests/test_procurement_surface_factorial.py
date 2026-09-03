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
    CAMPAIGN_ID as COMBINED_CAMPAIGN_ID,
    PAIRED_INFERENCE_SEEDS,
)
from aeread_families.procurement_allocation.case_matrix import (
    LABELED_REORDERED_PATHS,
    OPAQUE_ORIGINAL_PATHS,
    build_blinded_case_matrix,
    build_case_matrix,
    build_labeled_reordered_case_matrix,
    build_opaque_original_case_matrix,
)
from aeread_families.procurement_allocation.environment import (
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider
from aeread_families.procurement_allocation.surface_factorial import (
    LABELED_REORDERED_CAMPAIGN_ID,
    OPAQUE_ORIGINAL_CAMPAIGN_ID,
    build_factorial_comparison,
    run_panel_canary,
)


def _supplier_signature(supplier: dict) -> bytes:
    projected = copy.deepcopy(supplier)
    projected.pop("supplier_id")
    projected["listing"].pop("supplier_name")
    return canonical_json_bytes(projected)


def _signatures(case: dict) -> list[bytes]:
    return [_supplier_signature(item) for item in case["payload"]["suppliers"]]


def test_factorial_panels_change_only_declared_surface_factors() -> None:
    baseline = build_case_matrix()
    combined = build_blinded_case_matrix()
    opaque = build_opaque_original_case_matrix()
    reordered = build_labeled_reordered_case_matrix()

    for base, both, identity, order, identity_path, order_path in zip(
        baseline,
        combined,
        opaque,
        reordered,
        OPAQUE_ORIGINAL_PATHS,
        LABELED_REORDERED_PATHS,
        strict=True,
    ):
        assert json.loads(identity_path.read_text()) == identity
        assert json.loads(order_path.read_text()) == order
        assert _signatures(identity) == _signatures(base)
        assert _signatures(order) == _signatures(both)
        assert [item["supplier_id"] for item in order["payload"]["suppliers"]] != [
            item["supplier_id"] for item in base["payload"]["suppliers"]
        ]
        assert sorted(
            item["supplier_id"] for item in order["payload"]["suppliers"]
        ) == sorted(item["supplier_id"] for item in base["payload"]["suppliers"])
        assert sorted(
            item["supplier_id"] for item in identity["payload"]["suppliers"]
        ) == sorted(item["supplier_id"] for item in both["payload"]["suppliers"])

        for case in (both, identity, order):
            assert case["world_seed"] == base["world_seed"]
            assert case["payload"]["objective"] == base["payload"]["objective"]
            assert case["payload"]["interaction"] == base["payload"]["interaction"]
            assert case["payload"]["policy"] == base["payload"]["policy"]
            bound = solve_full_information_upper_bound(
                CaseManifest.from_dict(case).payload
            )
            baseline_bound = solve_full_information_upper_bound(
                CaseManifest.from_dict(base).payload
            )
            assert (
                bound.contribution_margin_usd == baseline_bound.contribution_margin_usd
            )
            assert bound.completed_kits == baseline_bound.completed_kits
            assert bound.cash_spend_usd == baseline_bound.cash_spend_usd
            assert bound.actions_required == baseline_bound.actions_required
            assert bound.elapsed_days == baseline_bound.elapsed_days


def _write_artifact(
    root: Path, *, campaign_id: str, split: str, margin_delta: float
) -> None:
    rows = []
    for path in OPAQUE_ORIGINAL_PATHS:
        for seed in PAIRED_INFERENCE_SEEDS:
            row = {
                "case_id": f"procurement_allocation_v1.{split}.{path.stem}",
                "case_content_sha256": hashlib.sha256(
                    f"{split}:{path.stem}".encode()
                ).hexdigest(),
                "inference_seed": seed,
                "status": "completed",
                "feasible": margin_delta == 0.0,
                "completed_kits": 20 + margin_delta,
                "contribution_margin_usd": 10.0 + margin_delta,
                "upper_bound_usd": 20.0,
                "regret_to_upper_bound_usd": 10.0 - margin_delta,
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
            "total_cost_usd": 0.01,
            "readiness": {"execution_qualified": True},
        },
        "rows": rows,
    }
    artifact["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(artifact)
    ).hexdigest()
    root.mkdir(parents=True)
    (root / "summary.json").write_bytes(canonical_json_bytes(artifact) + b"\n")


def test_factorial_comparison_recovers_main_and_interaction_effects(
    tmp_path: Path,
) -> None:
    roots = {
        "labeled_original": tmp_path / "baseline",
        "opaque_original": tmp_path / "opaque",
        "labeled_reordered": tmp_path / "reordered",
        "opaque_reordered": tmp_path / "combined",
    }
    specifications = (
        ("labeled_original", BASELINE_CAMPAIGN_ID, "dev", 0.0),
        ("opaque_original", OPAQUE_ORIGINAL_CAMPAIGN_ID, "opaque_original_v4", -1.0),
        (
            "labeled_reordered",
            LABELED_REORDERED_CAMPAIGN_ID,
            "labeled_reordered_v4",
            -2.0,
        ),
        ("opaque_reordered", COMBINED_CAMPAIGN_ID, "blinded_v3", -4.0),
    )
    for condition, campaign_id, split, delta in specifications:
        _write_artifact(
            roots[condition], campaign_id=campaign_id, split=split, margin_delta=delta
        )

    result = build_factorial_comparison(condition_run_roots=roots)

    assert result["readiness"]["factorial_qualified"] is True
    assert result["integrity"]["upper_bounds_match"] is True
    effects = result["aggregate_effects"]
    assert (
        effects["identity_at_original_order"]["contribution_margin_usd"][
            "case_cluster_mean"
        ]
        == -1.0
    )
    assert (
        effects["order_with_labels"]["contribution_margin_usd"]["case_cluster_mean"]
        == -2.0
    )
    assert (
        effects["identity_main_effect"]["contribution_margin_usd"]["case_cluster_mean"]
        == -1.5
    )
    assert (
        effects["order_main_effect"]["contribution_margin_usd"]["case_cluster_mean"]
        == -2.5
    )
    assert (
        effects["identity_order_interaction"]["contribution_margin_usd"][
            "case_cluster_mean"
        ]
        == -1.0
    )
    assert effects["identity_order_interaction"]["contribution_margin_usd"][
        "case_cluster_bootstrap_95_interval"
    ] == [-1.0, -1.0]


def test_factorial_canary_uses_declared_condition_request(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    provider = SequenceResponseProvider((json.dumps({"action": "defer"}),))

    result = asyncio.run(
        run_panel_canary(
            path=path,
            campaign_id=OPAQUE_ORIGINAL_CAMPAIGN_ID,
            case_path=OPAQUE_ORIGINAL_PATHS[0],
            provider_factory=lambda: provider,
        )
    )

    assert result["status"] == "admitted"
    assert result["campaign_id"] == OPAQUE_ORIGINAL_CAMPAIGN_ID
    assert result["request_sha256"] == provider.requests[0].request_sha256
    assert result["scored"] is False
    assert "raw_response" not in path.read_text()
