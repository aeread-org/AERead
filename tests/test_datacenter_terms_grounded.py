from __future__ import annotations

import pytest

import asyncio
import csv
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development_terms.environment import (
    DataCenterTermsPlugin,
)
from aeread_families.datacenter_development_terms.grounded_campaign import (
    _campaign_summary,
    _cases_by_slug,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.grounded_cases import (
    CLUSTER_ID,
    grounded_pack_sha256,
    load_authoring_records,
    load_grounded_cases,
)
from aeread_families.datacenter_development_terms.grounded_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.datacenter_development_terms.grounded_glm_campaign import (
    _run_live_cell as run_glm_live_cell,
    build_design as build_glm_design,
    load_contract as load_glm_contract,
    run_campaign as run_glm_campaign,
)
from aeread_families.datacenter_development_terms.grounded_glm_publication import (
    PROHIBITED_PUBLIC_TEXT as GLM_PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.datacenter_development_terms.runner import (
    build_openrouter_setup,
    datacenter_terms_output_schema,
)
from aeread_families.datacenter_development_terms.campaign import _route
from aeread_families.single_offer.runner import FixedResponseProvider


def test_grounded_pack_preserves_lineage_and_cluster_limits() -> None:
    manifest, records, catalog = load_authoring_records()

    assert manifest["case_count"] == 4
    assert manifest["evidence_basis"] == (
        "verified_before_sanitization_user_provided_pack"
    )
    assert manifest["independence_cluster_count"] == 1
    assert manifest["inference_status"] == "diagnostic_only"
    assert {row["independence_cluster_id"] for row in records} == {CLUSTER_ID}
    assert catalog["original_artifacts_included"] is False
    assert catalog["public_reproducibility"] is False
    assert all(
        source["verification"] == "verified_before_sanitization"
        and source["original_included"] is False
        for source in catalog["sources"].values()
    )
    assert len(grounded_pack_sha256()) == 64


def test_grounded_cases_are_hash_pinned_and_hide_private_oracles() -> None:
    plugin = DataCenterTermsPlugin()
    cases = load_grounded_cases()

    assert len(cases) == 4
    assert len({case.content_sha256 for case in cases}) == 4
    for case in cases:
        assert case.content_sha256 == case_content_sha256(case)
        family_case = plugin.validate_payload(case.payload)
        state = plugin.initial_state(family_case, run=None)
        observation = plugin.observe(
            family_case,
            state,
            "analyst",
            plugin.phases(family_case)[0],
        )
        encoded = canonical_json_bytes(observation).decode("utf-8")
        assert '"oracle"' not in encoded
        assert '"source_refs"' not in encoded
        assert '"terminal_when"' not in encoded
        assert '"failure_mechanisms"' not in encoded


def test_grounded_output_schemas_are_case_specific_without_gold_choices() -> None:
    contract = load_contract()
    route = _route(contract["models"]["qwen3_235b_novita"])
    for case in load_grounded_cases():
        slug = case.case_id.rsplit(".", 1)[-1]
        setup = build_openrouter_setup(
            route,
            seed=313001,
            case_slug=slug,
            case_manifest=case,
            max_cost_usd=0.02,
        )
        schema = datacenter_terms_output_schema(case)
        configured = setup.plan.agent_profiles[0].harness.config["output_schema"]
        assert canonical_json_bytes(configured) == canonical_json_bytes(schema)
        assert set(schema["properties"]) == {
            "case_id",
            "states",
            "amounts",
            "actions",
            "claims",
            "evidence_ids",
            "external_actions_attempted",
        }


def test_grounded_campaign_is_paired_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["case_count"] == 4
    assert design["independent_cluster_count"] == 1
    assert design["planned_cells"] == 24
    assert design["planned_pair_count"] == 12
    assert design["worst_case_declared_cost_usd"] == 0.48
    assert design["worst_case_declared_cost_usd"] <= design[
        "campaign_max_cost_usd"
    ]
    assert {cell["source_cluster_id"] for cell in design["cells"]} == {
        CLUSTER_ID
    }
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert contract["analysis"]["inferential_model_ranking_allowed"] is False
    assert contract["analysis"]["project_generalization_allowed"] is False
    assert contract["analysis"]["population_causal_effect_allowed"] is False


def test_grounded_campaign_passes_provider_free_and_admission_gates(
    tmp_path: Path,
) -> None:
    summary = asyncio.run(
        run_campaign(
            run_root=tmp_path / "grounded_campaign",
            stop_after="profile_admission",
        )
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 24


def test_grounded_live_cell_executes_scores_and_replays(tmp_path: Path) -> None:
    contract = load_contract()
    design = build_design(contract)
    cases = _cases_by_slug()
    cell = next(
        row
        for row in design["cells"]
        if row["case_slug"] == "contract-execution-cutoffs"
        and row["model_id"] == "qwen3_235b_novita"
        and row["inference_seed"] == 313001
    )
    case = cases[cell["case_slug"]]
    gold = case.payload["oracle"]["gold"]
    response = {
        "case_id": case.case_id,
        "states": gold["states"],
        "amounts": gold["amounts"],
        "actions": gold["required_actions"],
        "claims": gold["required_claims"],
        "evidence_ids": gold["required_evidence_ids"],
        "external_actions_attempted": [],
    }

    result = asyncio.run(
        _run_live_cell(
            contract,
            cell,
            cases=cases,
            run_root=tmp_path / "live_cell",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )

    assert result["status"] == "completed"
    assert result["inclusion_status"] == "included"
    assert result["metrics"]["score"] == 1.0
    assert result["replay_verified"] is True


def test_grounded_summary_keeps_operational_failure_as_missing_pair() -> None:
    contract = load_contract()
    rows = []
    for cell in build_design(contract)["cells"]:
        excluded = cell["cell_key"] == (
            "colo-quote-normalization__qwen3_235b_novita__seed_313001"
        )
        rows.append(
            {
                **cell,
                "status": "operational_failure" if excluded else "completed",
                "inclusion_status": "excluded" if excluded else "included",
                "replay_verified": not excluded,
                "elapsed_seconds": 1.0,
                "usage": (
                    None
                    if excluded
                    else {
                        "reported_cost_usd": 0.001,
                        "input_tokens": 1,
                        "cached_input_tokens": 0,
                        "output_tokens": 1,
                    }
                ),
                "metrics": (
                    None
                    if excluded
                    else {
                        "score": 0.8,
                        "hard_gate_pass": True,
                        "state_accuracy": 1.0,
                        "amount_accuracy": 1.0,
                        "required_action_recall": 0.5,
                        "required_claim_recall": 0.5,
                        "evidence_coverage": 1.0,
                    }
                ),
                "failure": (
                    {
                        "failure_class": "retryable_infrastructure",
                        "failure_condition": "rate_limit",
                    }
                    if excluded
                    else None
                ),
            }
        )

    summary = _campaign_summary(contract, rows)
    missing = [
        pair
        for pair in summary["paired_case_seed_contrasts"]
        if not pair["pair_reportable"]
    ]
    assert summary["operational_failure_cells"] == 1
    assert summary["included_cells"] == 23
    assert summary["reportable_pair_count"] == 11
    assert len(missing) == 1
    assert missing[0]["model_scores"] is None
    assert missing[0]["qwen_minus_mistral"] is None
    assert summary["cost_qualifier"] == "lower_bound"


def test_grounded_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_grounded_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "grounded_publication.py"
        ).read_bytes()
    ).hexdigest()
    helper_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert manifest["publisher_helper_sha256"] == helper_hash
    assert manifest["pack_sha256"] == grounded_pack_sha256()
    assert len(manifest["source_receipt_sha256s"]) == 24
    assert len(set(manifest["source_receipt_sha256s"])) == 24
    assert len(manifest["source_result_sha256s"]) == 24
    assert len(set(manifest["source_result_sha256s"])) == 24
    assert all(value is False for value in manifest["sanitization"].values())
    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in PROHIBITED_PUBLIC_TEXT)


def test_grounded_publication_preserves_case_variance_and_hard_gate() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_development_terms_grounded_v1"
    )
    summary = json.loads((publication / "reports/summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    receipts = (
        publication / "receipts/projections.jsonl"
    ).read_text().splitlines()
    with (publication / "tables/paired_results.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))

    assert summary["planned_cells"] == 24
    assert summary["completed_cells"] == 24
    assert summary["included_cells"] == 24
    assert summary["operational_failure_cells"] == 0
    assert summary["reportable_pair_count"] == 12
    assert summary["independent_cluster_count"] == 1
    assert summary["reported_cost_usd"] == 0.0030291624
    assert summary["cost_qualifier"] == "exact"
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["all_completed_receipts_replayed"] is True
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False
    assert summary["project_generalization_allowed"] is False
    assert summary["population_causal_effect_allowed"] is False

    assert len(trajectories) == 24
    assert len(receipts) == 24
    assert all(row["status"] == "completed" for row in trajectories)
    assert all(row["inclusion_status"] == "included" for row in trajectories)
    assert all(row["route_verified"] is True for row in trajectories)
    assert all(row["replay_verified"] is True for row in trajectories)
    assert {row["source_cluster_id"] for row in trajectories} == {CLUSTER_ID}
    hard_gate_failures = [
        row for row in trajectories if not row["metrics"]["hard_gate_pass"]
    ]
    assert len(hard_gate_failures) == 1
    failure = hard_gate_failures[0]
    assert failure["cell_key"] == (
        "deployment-location-power-reconciliation__"
        "mistral32_deepinfra__seed_313002"
    )
    assert failure["metrics"]["score"] == 0.0
    assert failure["metrics"]["component_mean"] == 0.5833333333333333
    assert failure["metrics"]["forbidden_claims"] == [
        "countersigned_means_hardware_received"
    ]

    assert len(pairs) == 12
    assert all(row["pair_reportable"] == "True" for row in pairs)
    quote_pairs = [
        row for row in pairs if row["case_slug"] == "colo-quote-normalization"
    ]
    assert len(quote_pairs) == 3
    assert all(float(row["qwen_minus_mistral"]) < 0 for row in quote_pairs)
    non_quote_pairs = [row for row in pairs if row not in quote_pairs]
    assert len(non_quote_pairs) == 9
    assert all(float(row["qwen_minus_mistral"]) > 0 for row in non_quote_pairs)


@pytest.mark.local_run("datacenter_development_terms_grounded_v1")
def test_grounded_glm_addon_is_hash_bridged_bounded_and_noninferential() -> None:
    contract = load_glm_contract()
    design = build_glm_design(contract)

    assert design["planned_cells"] == 12
    assert design["case_count"] == 4
    assert design["independent_cluster_count"] == 1
    assert design["worst_case_declared_cost_usd"] == 0.24
    assert design["bridge"] == contract["bridge"]
    assert all(cell["model_id"] == "glm53_reka" for cell in design["cells"])
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert contract["analysis"]["inferential_model_ranking_allowed"] is False
    assert contract["analysis"]["project_generalization_allowed"] is False


@pytest.mark.local_run("datacenter_development_terms_grounded_v1")
def test_grounded_glm_addon_passes_inherited_gate_and_admission(
    tmp_path: Path,
) -> None:
    summary = asyncio.run(
        run_glm_campaign(
            run_root=tmp_path / "glm_campaign",
            stop_after="profile_admission",
        )
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 12
    provider_free = json.loads(
        (
            tmp_path
            / "glm_campaign/provider_free_validation/summary.json"
        ).read_text()
    )
    assert provider_free["mode"] == (
        "inherited_same_pack_environment_scorer_and_cases"
    )


@pytest.mark.local_run("datacenter_development_terms_grounded_v1")
def test_grounded_glm_live_cell_executes_and_replays(tmp_path: Path) -> None:
    contract = load_glm_contract()
    design = build_glm_design(contract)
    cell = next(
        row
        for row in design["cells"]
        if row["case_slug"] == "colo-quote-normalization"
        and row["inference_seed"] == 313001
    )
    case = _cases_by_slug()[cell["case_slug"]]
    gold = case.payload["oracle"]["gold"]
    response = {
        "case_id": case.case_id,
        "states": gold["states"],
        "amounts": gold["amounts"],
        "actions": gold["required_actions"],
        "claims": gold["required_claims"],
        "evidence_ids": gold["required_evidence_ids"],
        "external_actions_attempted": [],
    }

    result = asyncio.run(
        run_glm_live_cell(
            contract,
            cell,
            run_root=tmp_path / "glm_live",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )

    assert result["status"] == "completed"
    assert result["metrics"]["score"] == 1.0
    assert result["replay_verified"] is True


def test_grounded_glm_publication_is_sealed_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_grounded_glm_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "grounded_glm_publication.py"
        ).read_bytes()
    ).hexdigest()
    helper_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert manifest["publisher_helper_sha256"] == helper_hash
    assert len(manifest["source_receipt_sha256s"]) == 12
    assert len(set(manifest["source_receipt_sha256s"])) == 12
    assert len(manifest["source_result_sha256s"]) == 12
    assert len(set(manifest["source_result_sha256s"])) == 12
    assert all(value is False for value in manifest["sanitization"].values())
    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in GLM_PROHIBITED_PUBLIC_TEXT)


def test_grounded_glm_publication_separates_capability_and_reliability() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_development_terms_grounded_glm_v1"
    )
    summary = json.loads((publication / "reports/summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    receipts = (
        publication / "receipts/projections.jsonl"
    ).read_text().splitlines()
    with (publication / "tables/three_model_bridge.csv").open(newline="") as handle:
        bridge = list(csv.DictReader(handle))

    assert summary["planned_cells"] == 12
    assert summary["completed_cells"] == 4
    assert summary["included_cells"] == 4
    assert summary["operational_failure_cells"] == 8
    assert summary["failure_conditions"] == ["rate_limit"] * 8
    assert summary["bridge_reportable_count"] == 4
    assert summary["reported_cost_usd"] == 0.0007468065
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["model_summary"]["completion_rate"] == 1 / 3
    assert summary["model_summary"]["hard_gate_pass_rate"] == 1.0
    assert summary["model_summary"]["mean_score"] == 0.9633333333333333
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False
    assert summary["project_generalization_allowed"] is False

    assert len(trajectories) == 12
    assert len(receipts) == 12
    included = [row for row in trajectories if row["inclusion_status"] == "included"]
    excluded = [row for row in trajectories if row["inclusion_status"] == "excluded"]
    assert len(included) == 4
    assert len(excluded) == 8
    assert all(row["route_verified"] is True for row in included)
    assert all(row["replay_verified"] is True for row in included)
    assert all(row["metrics"]["hard_gate_pass"] is True for row in included)
    assert all(
        summary["model_summary"]["min_score"] <= row["metrics"]["score"] <= 1.0
        for row in included
    )
    assert all(row["route_verified"] is False for row in excluded)
    assert all(row["metrics"] is None for row in excluded)
    assert all(row["failure"]["failure_condition"] == "rate_limit" for row in excluded)

    assert len(bridge) == 12
    reportable = [row for row in bridge if row["bridge_reportable"] == "True"]
    assert len(reportable) == 4
    assert all(
        float(row["glm_score"])
        > max(float(row["mistral_score"]), float(row["qwen_score"]))
        for row in reportable
    )
