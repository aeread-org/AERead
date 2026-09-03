from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development_terms.environment import (
    DataCenterTermsPlugin,
)
from aeread_families.datacenter_development_terms.public_mechanism_campaign import (
    MODEL_ORDER,
    _campaign_summary,
    _cases_by_slug,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_mechanism_cases import (
    AFFIRM_ONLY_SUFFIX,
    CASES_PATH,
    SOURCE_CATALOG_PATH,
    load_public_mechanism_authoring_records,
    load_public_mechanism_cases,
    mechanism_and_condition,
    public_mechanism_pack_sha256,
)
from aeread_families.datacenter_development_terms.public_mechanism_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(canonical_json_bytes(row).decode("utf-8") + "\n" for row in rows),
        encoding="utf-8",
    )


def test_public_mechanism_pack_is_paired_and_source_bounded() -> None:
    manifest, records, catalog = load_public_mechanism_authoring_records()
    cases = load_public_mechanism_cases()

    assert manifest["case_count"] == 6
    assert manifest["mechanism_count"] == 3
    assert manifest["independence_cluster_count"] == 1
    assert manifest["wording_conditions"] == ["baseline", "affirm_only"]
    assert len(catalog["sources"]) == 1
    assert len(cases) == 6
    assert len(public_mechanism_pack_sha256()) == 64
    by_mechanism: dict[str, dict[str, object]] = {}
    for record, case in zip(records, cases, strict=True):
        slug = record["case_slug"]
        mechanism, condition = mechanism_and_condition(slug)
        by_mechanism.setdefault(mechanism, {})[condition] = (record, case)
        assert case.content_sha256 == case_content_sha256(case)
    for pair in by_mechanism.values():
        baseline_record, baseline_case = pair["baseline"]
        affirm_record, affirm_case = pair["affirm_only"]
        assert affirm_record["prompt"] == baseline_record["prompt"] + AFFIRM_ONLY_SUFFIX
        assert affirm_record["observations"] == baseline_record["observations"]
        assert affirm_record["oracle"] == baseline_record["oracle"]
        assert affirm_record["title"] == baseline_record["title"]
        assert affirm_case.world_seed == baseline_case.world_seed


def test_public_mechanism_cases_hide_oracles_and_sources() -> None:
    plugin = DataCenterTermsPlugin()
    for case in load_public_mechanism_cases():
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


def test_public_mechanism_loader_rejects_pair_or_source_corruption(
    tmp_path: Path,
) -> None:
    records = [json.loads(line) for line in CASES_PATH.read_text().splitlines()]
    corrupted_records = copy.deepcopy(records)
    corrupted_records[1]["observations"][0]["content"] += " Changed."
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(cases_path, corrupted_records)
    with pytest.raises(ValueError, match="paired field observations differs"):
        load_public_mechanism_authoring_records(cases_path=cases_path)

    catalog = json.loads(SOURCE_CATALOG_PATH.read_text())
    catalog["sources"]["core_denton_project_terms_2026"]["url"] = (
        "https://example.com/not-sec"
    )
    catalog_path = tmp_path / "source_catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="SEC source entry differs"):
        load_public_mechanism_authoring_records(source_catalog_path=catalog_path)


def test_public_mechanism_loader_rejects_overlapping_oracle_labels(
    tmp_path: Path,
) -> None:
    records = [json.loads(line) for line in CASES_PATH.read_text().splitlines()]
    corrupted = copy.deepcopy(records)
    for row in corrupted[:2]:
        required = row["oracle"]["gold"]["required_actions"][0]
        row["oracle"]["gold"]["forbidden_actions"].append(required)
    cases_path = tmp_path / "overlap.jsonl"
    _write_jsonl(cases_path, corrupted)
    with pytest.raises(ValueError, match="required and forbidden labels overlap"):
        load_public_mechanism_authoring_records(cases_path=cases_path)


def test_public_mechanism_campaign_is_paired_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 54
    assert design["planned_pair_count"] == 27
    assert design["case_count"] == 6
    assert design["mechanism_count"] == 3
    assert design["wording_condition_count"] == 2
    assert design["independent_cluster_count"] == 1
    assert design["worst_case_declared_cost_usd"] == 1.08
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert len({cell["pair_key"] for cell in design["cells"]}) == 27
    assert all(
        sum(other["pair_key"] == cell["pair_key"] for other in design["cells"]) == 2
        for cell in design["cells"]
    )
    assert contract["execution"]["concurrency"] == 3
    assert contract["execution"]["max_concurrent_cells_per_route_provider"] == 1
    assert contract["execution"]["sdk_retries"] == 0
    assert contract["execution"]["response_cache"] is False
    assert contract["execution"]["provider_fallbacks"] is False
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert contract["analysis"]["inferential_model_ranking_allowed"] is False
    assert contract["analysis"]["project_generalization_allowed"] is False


def test_public_mechanism_contract_rejects_route_and_pair_drift(tmp_path: Path) -> None:
    contract = load_contract()
    mutations = []
    route = copy.deepcopy(contract)
    route["models"]["gptoss120b_coreweave"][
        "max_completion_price_per_million"
    ] = "0.18"
    mutations.append(route)
    pair = copy.deepcopy(contract)
    pair["cases"]["assignment-consent-m02"]["world_seed"] = 999
    mutations.append(pair)
    for index, candidate in enumerate(mutations):
        path = tmp_path / f"contract_{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_public_mechanism_passes_provider_free_and_admission(tmp_path: Path) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "mechanism_campaign",
            stop_after="profile_admission",
        )
    )

    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 54
    gate = json.loads(
        (
            tmp_path
            / "mechanism_campaign/provider_free_validation/summary.json"
        ).read_text()
    )
    assert gate["status"] == "passed"
    assert len(gate["cases"]) == 6
    assert all(row["score"] == 1.0 for row in gate["cases"])


def test_public_mechanism_live_cell_executes_scores_and_replays(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    design = build_design(contract)
    cell = next(
        row
        for row in design["cells"]
        if row["case_slug"] == "gmp-change-order-m02"
        and row["model_id"] == "gptoss120b_coreweave"
        and row["inference_seed"] == 315001
    )
    cases = _cases_by_slug()
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
            run_root=tmp_path / "mechanism_live",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )

    assert result["status"] == "completed"
    assert result["inclusion_status"] == "included"
    assert result["metrics"]["score"] == 1.0
    assert result["replay_verified"] is True


def test_public_mechanism_summary_preserves_pair_missingness() -> None:
    contract = load_contract()
    rows = []
    excluded_key = (
        "gmp-change-order-m02__gptoss120b_coreweave__seed_315001"
    )
    for cell in build_design(contract)["cells"]:
        excluded = cell["cell_key"] == excluded_key
        baseline = cell["wording_condition"] == "baseline"
        rows.append(
            {
                **cell,
                "status": "operational_failure" if excluded else "completed",
                "inclusion_status": "excluded" if excluded else "included",
                "replay_verified": not excluded,
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
                        "score": 0.0 if baseline else 0.8,
                        "hard_gate_pass": not baseline,
                        "state_accuracy": 1.0,
                        "amount_accuracy": 1.0,
                        "required_action_recall": 1.0,
                        "required_claim_recall": 1.0,
                        "evidence_coverage": 1.0,
                        "forbidden_actions": ["unsafe"] if baseline else [],
                        "forbidden_claims": [],
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

    assert summary["planned_cells"] == 54
    assert summary["completed_cells"] == 53
    assert summary["operational_failure_cells"] == 1
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["reportable_pair_count"] == 26
    missing = [
        pair
        for pair in summary["paired_wording_contrasts"]
        if not pair["pair_reportable"]
    ]
    assert len(missing) == 1
    assert missing[0]["pair_key"] == (
        "gmp_change_order__gptoss120b_coreweave__seed_315001"
    )
    assert missing[0]["score_delta"] is None
    assert missing[0]["hard_gate_rescue"] is None
    model_summaries = {
        row["model_id"]: row for row in summary["model_contrast_summaries"]
    }
    assert model_summaries["mistral32_deepinfra"]["hard_gate_rescues"] == 9
    assert model_summaries["qwen3_235b_novita"]["hard_gate_rescues"] == 9
    assert model_summaries["gptoss120b_coreweave"]["hard_gate_rescues"] == 8
    assert all(
        row["hard_gate_regressions"] == 0
        for row in summary["model_contrast_summaries"]
    )
    assert set(MODEL_ORDER) == set(model_summaries)


def test_public_mechanism_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_mechanism_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_mechanism_publication.py"
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
    assert manifest["pack_sha256"] == public_mechanism_pack_sha256()
    assert len(manifest["source_receipt_sha256s"]) == 54
    assert len(set(manifest["source_receipt_sha256s"])) == 54
    assert len(manifest["source_result_sha256s"]) == 54
    assert len(set(manifest["source_result_sha256s"])) == 54
    assert all(value is False for value in manifest["sanitization"].values())
    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in PROHIBITED_PUBLIC_TEXT)


def test_public_mechanism_publication_preserves_observed_mechanism_result() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_development_terms_public_mechanism_v1"
    )
    summary = json.loads((publication / "reports/summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    receipts = (publication / "receipts/projections.jsonl").read_text().splitlines()
    with (publication / "tables/paired_wording_contrasts.csv").open(
        newline=""
    ) as handle:
        pairs = list(csv.DictReader(handle))

    assert summary["planned_cells"] == 54
    assert summary["completed_cells"] == 53
    assert summary["included_cells"] == 53
    assert summary["operational_failure_cells"] == 1
    assert summary["failure_conditions"] == ["rate_limit"]
    assert summary["reported_cost_usd"] == 0.0051079545
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["reportable_pair_count"] == 26
    assert summary["independent_cluster_count"] == 1
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["all_completed_receipts_replayed"] is True
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False
    assert summary["project_generalization_allowed"] is False

    conditions = {
        row["wording_condition"]: row for row in summary["condition_summaries"]
    }
    assert conditions["baseline"]["completed_cells"] == 27
    assert conditions["baseline"]["hard_gate_pass_rate"] == 8 / 9
    assert conditions["affirm_only"]["completed_cells"] == 26
    assert conditions["affirm_only"]["hard_gate_pass_rate"] == 1.0

    model_contrasts = {
        row["model_id"]: row for row in summary["model_contrast_summaries"]
    }
    assert model_contrasts["mistral32_deepinfra"]["hard_gate_rescues"] == 0
    assert model_contrasts["mistral32_deepinfra"]["missing_pairs"] == 1
    assert model_contrasts["qwen3_235b_novita"]["hard_gate_rescues"] == 1
    assert model_contrasts["gptoss120b_coreweave"]["hard_gate_rescues"] == 2
    assert all(
        row["hard_gate_regressions"] == 0 for row in model_contrasts.values()
    )
    mechanism_contrasts = {
        row["mechanism_id"]: row
        for row in summary["mechanism_contrast_summaries"]
    }
    assert mechanism_contrasts["assignment_consent"]["hard_gate_rescues"] == 0
    assert mechanism_contrasts["land_power_cotermination"]["hard_gate_rescues"] == 0
    assert mechanism_contrasts["gmp_change_order"]["hard_gate_rescues"] == 3
    assert mechanism_contrasts["gmp_change_order"]["mean_score_delta"] == 1 / 3

    assert len(trajectories) == 54
    assert len(receipts) == 54
    excluded = [row for row in trajectories if row["status"] != "completed"]
    assert [row["cell_key"] for row in excluded] == [
        "land-power-cotermination-m02__mistral32_deepinfra__seed_315002"
    ]
    assert excluded[0]["inclusion_status"] == "excluded"
    assert excluded[0]["failure"] == {
        "failure_class": "retryable_infrastructure",
        "failure_condition": "rate_limit",
    }
    completed = [row for row in trajectories if row["status"] == "completed"]
    assert all(row["route_verified"] is True for row in completed)
    assert all(row["replay_verified"] is True for row in completed)
    hard_gate_failures = [
        row for row in completed if not row["metrics"]["hard_gate_pass"]
    ]
    assert {row["cell_key"] for row in hard_gate_failures} == {
        "gmp-change-order-m01__gptoss120b_coreweave__seed_315001",
        "gmp-change-order-m01__gptoss120b_coreweave__seed_315003",
        "gmp-change-order-m01__qwen3_235b_novita__seed_315003",
    }
    assert all(row["metrics"]["score"] == 0.0 for row in hard_gate_failures)
    assert all(
        row["metrics"]["forbidden_actions"] == ["underwrite_as_fixed_price_epc"]
        for row in hard_gate_failures
    )
    assert all(row["metrics"]["forbidden_claims"] == [] for row in hard_gate_failures)
    assert all(row["wording_condition"] == "baseline" for row in hard_gate_failures)

    assert len(pairs) == 27
    reportable = [row for row in pairs if row["pair_reportable"] == "True"]
    missing = [row for row in pairs if row["pair_reportable"] == "False"]
    assert len(reportable) == 26
    assert len(missing) == 1
    assert sum(row["hard_gate_rescue"] == "True" for row in reportable) == 3
    assert sum(row["hard_gate_regression"] == "True" for row in reportable) == 0
    assert all(
        row["mechanism_id"] == "gmp_change_order"
        for row in reportable
        if row["hard_gate_rescue"] == "True"
    )
