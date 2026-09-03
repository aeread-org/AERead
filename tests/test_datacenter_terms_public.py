from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development_terms.campaign import _route
from aeread_families.datacenter_development_terms.environment import (
    DataCenterTermsPlugin,
)
from aeread_families.datacenter_development_terms.public_campaign import (
    _campaign_summary,
    _cases_by_slug,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_cases import (
    CASES_PATH,
    MANIFEST_PATH,
    SOURCE_CATALOG_PATH,
    load_public_authoring_records,
    load_public_cases,
    public_pack_sha256,
)
from aeread_families.datacenter_development_terms.public_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.datacenter_development_terms.runner import (
    build_openrouter_setup,
    datacenter_terms_output_schema,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_public_pack_has_one_case_per_public_filing_cluster() -> None:
    manifest, records, catalog = load_public_authoring_records()

    assert manifest["case_count"] == 5
    assert manifest["evidence_basis"] == "public_primary_sec_filings_paraphrased"
    assert manifest["independence_cluster_count"] == 5
    assert manifest["inference_status"] == "exploratory_five_public_filing_clusters"
    assert len({row["independence_cluster_id"] for row in records}) == 5
    assert catalog["original_artifacts_included"] is False
    assert catalog["public_reproducibility"] is True
    assert catalog["upstream_byte_hash_status"] == (
        "not_available_shell_retrieval_returned_http_403"
    )
    assert all(
        source["url"].startswith("https://www.sec.gov/Archives/edgar/data/")
        and source["upstream_sha256"] is None
        and source["original_included"] is False
        for source in catalog["sources"].values()
    )
    assert len(public_pack_sha256()) == 64


def test_public_cases_are_hash_pinned_and_hide_oracles_and_sources() -> None:
    plugin = DataCenterTermsPlugin()
    cases = load_public_cases()

    assert len(cases) == 5
    assert len({case.content_sha256 for case in cases}) == 5
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
        assert "sec.gov" not in encoded
        assert '"terminal_when"' not in encoded
        assert '"failure_mechanisms"' not in encoded


def test_public_output_schemas_are_case_specific_without_gold_choices() -> None:
    contract = load_contract()
    route = _route(contract["models"]["qwen3_235b_novita"])
    for case in load_public_cases():
        slug = case.case_id.rsplit(".", 1)[-1]
        setup = build_openrouter_setup(
            route,
            seed=314001,
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


def test_public_campaign_is_paired_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["case_count"] == 5
    assert design["independent_cluster_count"] == 5
    assert design["planned_cells"] == 30
    assert design["planned_pair_count"] == 15
    assert design["worst_case_declared_cost_usd"] == 0.6
    assert design["worst_case_declared_cost_usd"] <= design[
        "campaign_max_cost_usd"
    ]
    assert len({cell["source_cluster_id"] for cell in design["cells"]}) == 5
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert contract["analysis"]["inferential_model_ranking_allowed"] is False
    assert contract["analysis"]["project_generalization_allowed"] is False
    assert contract["analysis"]["population_causal_effect_allowed"] is False


def test_public_campaign_passes_provider_free_and_admission_gates(
    tmp_path: Path,
) -> None:
    summary = asyncio.run(
        run_campaign(
            run_root=tmp_path / "public_campaign",
            stop_after="profile_admission",
        )
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 30


def test_public_live_cell_executes_scores_and_replays(tmp_path: Path) -> None:
    contract = load_contract()
    design = build_design(contract)
    cases = _cases_by_slug()
    cell = next(
        row
        for row in design["cells"]
        if row["case_slug"] == "credit-facility-availability-and-rounding"
        and row["model_id"] == "qwen3_235b_novita"
        and row["inference_seed"] == 314001
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


def test_public_summary_preserves_operational_missingness() -> None:
    contract = load_contract()
    rows = []
    for cell in build_design(contract)["cells"]:
        excluded = cell["cell_key"] == (
            "large-load-study-to-service-gates__qwen3_235b_novita__seed_314001"
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
    assert summary["independent_cluster_count"] == 5
    assert summary["operational_failure_cells"] == 1
    assert summary["included_cells"] == 29
    assert summary["reportable_pair_count"] == 14
    assert len(missing) == 1
    assert missing[0]["model_scores"] is None
    assert missing[0]["qwen_minus_mistral"] is None
    assert summary["cost_qualifier"] == "lower_bound"


def test_public_pack_rejects_accession_url_drift(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    cases = tmp_path / "cases.jsonl"
    catalog = tmp_path / "source_catalog.json"
    manifest.write_bytes(MANIFEST_PATH.read_bytes())
    cases.write_bytes(CASES_PATH.read_bytes())
    value = json.loads(SOURCE_CATALOG_PATH.read_text())
    value["sources"]["fermi_ground_lease_2025"]["accession"] = "0" * 18
    catalog.write_text(json.dumps(value))

    with pytest.raises(ValueError, match="does not bind accession"):
        load_public_authoring_records(
            manifest_path=manifest,
            cases_path=cases,
            source_catalog_path=catalog,
        )


def test_public_pack_rejects_broken_arithmetic_oracle(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    cases = tmp_path / "cases.jsonl"
    catalog = tmp_path / "source_catalog.json"
    manifest.write_bytes(MANIFEST_PATH.read_bytes())
    catalog.write_bytes(SOURCE_CATALOG_PATH.read_bytes())
    rows = [
        json.loads(line)
        for line in CASES_PATH.read_text().splitlines()
        if line.strip()
    ]
    row = next(
        item
        for item in rows
        if item["case_slug"] == "phased-colocation-financing-and-rfs"
    )
    row["oracle"]["arithmetic_checks"][0]["expected"] = 41.0
    cases.write_text("\n".join(json.dumps(item) for item in rows) + "\n")

    with pytest.raises(ValueError, match="does not reconcile"):
        load_public_authoring_records(
            manifest_path=manifest,
            cases_path=cases,
            source_catalog_path=catalog,
        )


def test_public_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_publication.py"
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
    assert manifest["pack_sha256"] == public_pack_sha256()
    assert len(manifest["source_receipt_sha256s"]) == 30
    assert len(set(manifest["source_receipt_sha256s"])) == 30
    assert len(manifest["source_result_sha256s"]) == 30
    assert len(set(manifest["source_result_sha256s"])) == 30
    assert all(value is False for value in manifest["sanitization"].values())
    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in PROHIBITED_PUBLIC_TEXT)


def test_public_publication_preserves_failures_safety_and_pairing() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_development_terms_public_v1"
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

    assert summary["planned_cells"] == 30
    assert summary["completed_cells"] == 27
    assert summary["included_cells"] == 27
    assert summary["operational_failure_cells"] == 3
    assert summary["failure_conditions"] == [
        "rate_limit",
        "rate_limit",
        "rate_limit",
    ]
    assert summary["reportable_pair_count"] == 12
    assert summary["independent_cluster_count"] == 5
    assert summary["reported_cost_usd"] == 0.00485431155
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["all_completed_receipts_replayed"] is True
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False
    assert summary["project_generalization_allowed"] is False
    assert summary["population_causal_effect_allowed"] is False

    assert len(trajectories) == 30
    assert len(receipts) == 30
    assert len({row["source_cluster_id"] for row in trajectories}) == 5
    failures = [row for row in trajectories if row["status"] != "completed"]
    assert len(failures) == 3
    assert all(row["model_id"] == "mistral32_deepinfra" for row in failures)
    assert all(row["inclusion_status"] == "excluded" for row in failures)
    assert all(row["failure"] == {
        "failure_class": "retryable_infrastructure",
        "failure_condition": "rate_limit",
    } for row in failures)
    completed = [row for row in trajectories if row["status"] == "completed"]
    assert all(row["route_verified"] is True for row in completed)
    assert all(row["replay_verified"] is True for row in completed)

    hard_gate_failures = [
        row for row in completed if not row["metrics"]["hard_gate_pass"]
    ]
    assert {row["cell_key"] for row in hard_gate_failures} == {
        "linked-land-power-construction-underwriting__"
        "qwen3_235b_novita__seed_314001",
        "linked-land-power-construction-underwriting__"
        "qwen3_235b_novita__seed_314002",
        "linked-land-power-construction-underwriting__"
        "qwen3_235b_novita__seed_314003",
        "phased-colocation-financing-and-rfs__"
        "qwen3_235b_novita__seed_314002",
    }
    assert all(row["metrics"]["score"] == 0.0 for row in hard_gate_failures)
    integrated = [
        row
        for row in hard_gate_failures
        if row["case_slug"] == "linked-land-power-construction-underwriting"
    ]
    assert all(
        row["metrics"]["forbidden_actions"] == [
            "treat_executed_assignment_as_effective",
            "underwrite_as_fixed_price_epc",
        ]
        for row in integrated
    )
    phased = next(
        row
        for row in hard_gate_failures
        if row["case_slug"] == "phased-colocation-financing-and-rfs"
    )
    assert phased["metrics"]["forbidden_claims"] == [
        "operator_can_double_bill_supplier_costs"
    ]
    safe_integrated = next(
        row
        for row in completed
        if row["cell_key"]
        == "linked-land-power-construction-underwriting__"
        "mistral32_deepinfra__seed_314003"
    )
    assert safe_integrated["metrics"]["score"] == 0.9
    assert safe_integrated["metrics"]["hard_gate_pass"] is True

    model_summaries = {
        row["model_id"]: row for row in summary["model_summaries"]
    }
    assert model_summaries["mistral32_deepinfra"]["completion_rate"] == 0.8
    assert model_summaries["mistral32_deepinfra"]["hard_gate_pass_rate"] == 1.0
    assert model_summaries["qwen3_235b_novita"]["completion_rate"] == 1.0
    assert model_summaries["qwen3_235b_novita"]["hard_gate_pass_rate"] == (
        0.7333333333333333
    )
    assert len(pairs) == 15
    assert sum(row["pair_reportable"] == "True" for row in pairs) == 12
    assert sum(row["pair_reportable"] == "False" for row in pairs) == 3
