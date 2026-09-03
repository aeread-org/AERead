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
from aeread_families.datacenter_development_terms.public_affirm_only_campaign import (
    MODEL_ORDER,
    _campaign_summary,
    _cases_by_slug,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_affirm_only_cases import (
    AFFIRM_ONLY_SUFFIX,
    DERIVED_SPLIT,
    MANIFEST_PATH,
    load_public_affirm_only_cases,
    load_public_affirm_only_manifest,
    public_affirm_only_pack_sha256,
)
from aeread_families.datacenter_development_terms.public_affirm_only_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.datacenter_development_terms.public_cases import (
    load_public_cases,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_affirm_only_pack_is_prompt_only_five_cluster_derivation() -> None:
    base = load_public_cases()
    derived = load_public_affirm_only_cases()

    assert len(base) == len(derived) == 5
    assert len(public_affirm_only_pack_sha256()) == 64
    assert {case.split for case in derived} == {DERIVED_SPLIT}
    assert len(
        {
            case.payload["public_case"]["independence_cluster_id"]
            for case in derived
        }
    ) == 5
    for base_case, derived_case in zip(base, derived, strict=True):
        base_public = base_case.payload["public_case"]
        derived_public = derived_case.payload["public_case"]
        changed = {
            key
            for key in set(base_public) | set(derived_public)
            if base_public.get(key) != derived_public.get(key)
        }
        assert changed == {"case_id", "prompt"}
        assert derived_public["prompt"] == base_public["prompt"] + AFFIRM_ONLY_SUFFIX
        assert derived_case.world_seed == base_case.world_seed
        assert derived_case.payload["oracle"] == base_case.payload["oracle"]
        assert derived_case.content_sha256 == case_content_sha256(derived_case)


def test_affirm_only_cases_hide_oracles_and_source_metadata() -> None:
    plugin = DataCenterTermsPlugin()
    for case in load_public_affirm_only_cases():
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


@pytest.mark.parametrize("field", ["base_pack_sha256", "prompt_suffix"])
def test_affirm_only_manifest_rejects_derivation_drift(
    tmp_path: Path,
    field: str,
) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest[field] = "0" * 64 if field.endswith("sha256") else " changed"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="derivation manifest differs"):
        load_public_affirm_only_manifest(path)


def test_affirm_only_campaign_is_bridged_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 45
    assert design["planned_pair_count"] == 45
    assert design["case_count"] == 5
    assert design["independent_cluster_count"] == 5
    assert design["worst_case_declared_cost_usd"] == 0.9
    assert design["baseline_bridge"] == contract["baseline_bridge"]
    assert {cell["model_id"] for cell in design["cells"]} == set(MODEL_ORDER)
    assert all(cell["wording_condition"] == "affirm_only" for cell in design["cells"])
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert contract["execution"]["sdk_retries"] == 0
    assert contract["execution"]["response_cache"] is False
    assert contract["execution"]["provider_fallbacks"] is False
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert contract["analysis"]["inferential_model_ranking_allowed"] is False
    assert contract["analysis"]["project_generalization_allowed"] is False


def test_affirm_only_contract_rejects_bridge_or_route_drift(tmp_path: Path) -> None:
    contract = load_contract()
    candidates = (
        {
            **contract,
            "baseline_bridge": {
                **contract["baseline_bridge"],
                "public_two_model": {
                    **contract["baseline_bridge"]["public_two_model"],
                    "trajectory_sha256": "0" * 64,
                },
            },
        },
        {
            **contract,
            "models": {
                **contract["models"],
                "qwen3_235b_novita": {
                    **contract["models"]["qwen3_235b_novita"],
                    "provider": "unsealed-provider",
                },
            },
        },
    )
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"contract-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_affirm_only_passes_reexecuted_gate_and_admission(tmp_path: Path) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "affirm_only_campaign",
            stop_after="profile_admission",
        )
    )

    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 45
    gate = json.loads(
        (
            tmp_path
            / "affirm_only_campaign/provider_free_validation/summary.json"
        ).read_text()
    )
    assert gate["mode"] == "reexecuted_derived_pack_environment_scorer_and_cases"
    assert gate["case_count"] == 5


def test_affirm_only_live_cell_executes_scores_and_replays(tmp_path: Path) -> None:
    contract = load_contract()
    design = build_design(contract)
    cell = next(
        row
        for row in design["cells"]
        if row["case_slug"] == "ground-lease-commencement-boundary"
        and row["model_id"] == "gptoss120b_coreweave"
        and row["inference_seed"] == 314001
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
        _run_live_cell(
            contract,
            cell,
            cases=_cases_by_slug(),
            run_root=tmp_path / "affirm_only_live",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )

    assert result["status"] == "completed"
    assert result["inclusion_status"] == "included"
    assert result["metrics"]["score"] == 1.0
    assert result["replay_verified"] is True


def _completed_rows() -> list[dict[str, object]]:
    contract = load_contract()
    rows = []
    for cell in build_design(contract)["cells"]:
        rows.append(
            {
                **cell,
                "status": "completed",
                "inclusion_status": "included",
                "replay_verified": True,
                "usage": {
                    "reported_cost_usd": 0.001,
                    "input_tokens": 1,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                },
                "metrics": {
                    "score": 0.8,
                    "hard_gate_pass": True,
                    "state_accuracy": 1.0,
                    "amount_accuracy": 1.0,
                    "required_action_recall": 0.5,
                    "required_claim_recall": 0.5,
                    "evidence_coverage": 1.0,
                    "forbidden_actions": [],
                    "forbidden_claims": [],
                },
                "failure": None,
            }
        )
    return rows


def test_affirm_only_summary_preserves_baseline_and_new_missingness() -> None:
    contract = load_contract()
    rows = _completed_rows()
    summary = _campaign_summary(contract, rows)

    assert summary["planned_cells"] == 45
    assert summary["completed_cells"] == 45
    assert summary["baseline_operational_failure_cells"] == 3
    assert summary["planned_pair_count"] == 45
    assert summary["reportable_pair_count"] == 42

    failed = copy.deepcopy(rows)
    target = next(
        row
        for row in failed
        if row["model_id"] == "gptoss120b_coreweave"
        and row["case_slug"] == "ground-lease-commencement-boundary"
        and row["inference_seed"] == 314001
    )
    target.update(
        {
            "status": "operational_failure",
            "inclusion_status": "excluded",
            "replay_verified": False,
            "usage": None,
            "metrics": None,
            "failure": {
                "failure_class": "retryable_infrastructure",
                "failure_condition": "rate_limit",
            },
        }
    )
    with_failure = _campaign_summary(contract, failed)

    assert with_failure["completed_cells"] == 44
    assert with_failure["operational_failure_cells"] == 1
    assert with_failure["cost_qualifier"] == "lower_bound"
    assert with_failure["reportable_pair_count"] == 41
    pair = next(
        pair
        for pair in with_failure["paired_wording_contrasts"]
        if pair["pair_key"]
        == "ground-lease-commencement-boundary__gptoss120b_coreweave__seed_314001"
    )
    assert pair["pair_reportable"] is False
    assert pair["score_delta"] is None


def test_affirm_only_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_affirm_only_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_affirm_only_publication.py"
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
    assert manifest["pack_sha256"] == public_affirm_only_pack_sha256()
    assert len(manifest["source_receipt_sha256s"]) == 45
    assert len(set(manifest["source_receipt_sha256s"])) == 45
    assert len(manifest["source_result_sha256s"]) == 45
    assert len(set(manifest["source_result_sha256s"])) == 45
    assert all(value is False for value in manifest["sanitization"].values())
    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in PROHIBITED_PUBLIC_TEXT)


def test_affirm_only_publication_preserves_observed_replication_result() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_development_terms_public_affirm_only_v1"
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

    assert summary["planned_cells"] == 45
    assert summary["completed_cells"] == 41
    assert summary["included_cells"] == 41
    assert summary["operational_failure_cells"] == 4
    assert summary["failure_conditions"] == ["rate_limit"] * 4
    assert summary["baseline_operational_failure_cells"] == 3
    assert summary["reported_cost_usd"] == 0.0070164666
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["reportable_pair_count"] == 41
    assert summary["independent_cluster_count"] == 5
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["all_completed_receipts_replayed"] is True
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False
    assert summary["project_generalization_allowed"] is False

    model_contrasts = {
        row["model_id"]: row for row in summary["model_contrast_summaries"]
    }
    assert model_contrasts["mistral32_deepinfra"]["reportable_pairs"] == 11
    assert model_contrasts["mistral32_deepinfra"]["mean_score_delta"] == 0.0
    assert model_contrasts["qwen3_235b_novita"]["hard_gate_rescues"] == 1
    assert model_contrasts["qwen3_235b_novita"][
        "affirm_only_hard_gate_pass_rate"
    ] == 0.8
    assert model_contrasts["gptoss120b_coreweave"]["hard_gate_rescues"] == 3
    assert model_contrasts["gptoss120b_coreweave"][
        "affirm_only_hard_gate_pass_rate"
    ] == 1.0
    assert all(
        row["hard_gate_regressions"] == 0 for row in model_contrasts.values()
    )

    case_contrasts = {
        row["case_slug"]: row for row in summary["case_contrast_summaries"]
    }
    assert case_contrasts["credit-facility-availability-and-rounding"][
        "mean_score_delta"
    ] < 0
    assert case_contrasts["large-load-study-to-service-gates"][
        "mean_score_delta"
    ] < 0
    assert case_contrasts["linked-land-power-construction-underwriting"][
        "hard_gate_rescues"
    ] == 3
    assert case_contrasts["phased-colocation-financing-and-rfs"][
        "hard_gate_rescues"
    ] == 1

    assert len(trajectories) == 45
    assert len(receipts) == 45
    excluded = [row for row in trajectories if row["status"] != "completed"]
    assert {row["cell_key"] for row in excluded} == {
        "large-load-study-to-service-gates__mistral32_deepinfra__seed_314002",
        "large-load-study-to-service-gates__mistral32_deepinfra__seed_314003",
        "linked-land-power-construction-underwriting__mistral32_deepinfra__seed_314001",
        "linked-land-power-construction-underwriting__mistral32_deepinfra__seed_314002",
    }
    assert all(row["inclusion_status"] == "excluded" for row in excluded)
    assert all(
        row["failure"]
        == {
            "failure_class": "retryable_infrastructure",
            "failure_condition": "rate_limit",
        }
        for row in excluded
    )
    completed = [row for row in trajectories if row["status"] == "completed"]
    assert all(row["route_verified"] is True for row in completed)
    assert all(row["replay_verified"] is True for row in completed)
    hard_gate_failures = [
        row for row in completed if not row["metrics"]["hard_gate_pass"]
    ]
    assert {row["cell_key"] for row in hard_gate_failures} == {
        "linked-land-power-construction-underwriting__qwen3_235b_novita__seed_314001",
        "linked-land-power-construction-underwriting__qwen3_235b_novita__seed_314002",
        "linked-land-power-construction-underwriting__qwen3_235b_novita__seed_314003",
    }
    assert all(row["metrics"]["score"] == 0.0 for row in hard_gate_failures)
    assert all(
        set(row["metrics"]["forbidden_actions"])
        == {"treat_executed_assignment_as_effective", "underwrite_as_fixed_price_epc"}
        for row in hard_gate_failures
    )

    assert len(pairs) == 45
    reportable = [row for row in pairs if row["pair_reportable"] == "True"]
    missing = [row for row in pairs if row["pair_reportable"] == "False"]
    assert len(reportable) == 41
    assert len(missing) == 4
    assert sum(row["hard_gate_rescue"] == "True" for row in reportable) == 4
    assert sum(row["hard_gate_regression"] == "True" for row in reportable) == 0
    assert {
        row["pair_key"]
        for row in reportable
        if row["hard_gate_rescue"] == "True"
    } == {
        "linked-land-power-construction-underwriting__gptoss120b_coreweave__seed_314001",
        "linked-land-power-construction-underwriting__gptoss120b_coreweave__seed_314002",
        "linked-land-power-construction-underwriting__gptoss120b_coreweave__seed_314003",
        "phased-colocation-financing-and-rfs__qwen3_235b_novita__seed_314002",
    }
