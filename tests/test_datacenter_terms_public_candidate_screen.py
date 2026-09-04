from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development_terms.environment import DataCenterTermsPlugin
from aeread_families.datacenter_development_terms.public_candidate_screen_campaign import (
    CONDITION_ORDER,
    CONTRASTS,
    MODEL_ORDER,
    _campaign_summary,
    _cases_by_condition,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_candidate_screen_cases import (
    CANDIDATE_SCREEN_SUFFIX,
    MANIFEST_PATH,
    load_public_candidate_screen_case,
    load_public_candidate_screen_manifest,
    public_candidate_screen_pack_sha256,
)
from aeread_families.datacenter_development_terms.public_candidate_screen_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)
from aeread_families.datacenter_development_terms.public_cases import load_public_cases
from aeread_families.single_offer.runner import FixedResponseProvider


def test_candidate_screen_case_is_prompt_only_and_hides_oracle() -> None:
    base = load_public_cases(
        case_slugs=("linked-land-power-construction-underwriting",)
    )[0]
    derived = load_public_candidate_screen_case()
    base_public = base.payload["public_case"]
    derived_public = derived.payload["public_case"]
    changed = {
        key
        for key in set(base_public) | set(derived_public)
        if base_public.get(key) != derived_public.get(key)
    }

    assert changed == {"case_id", "prompt"}
    assert derived_public["prompt"] == base_public["prompt"] + CANDIDATE_SCREEN_SUFFIX
    assert derived.world_seed == base.world_seed
    assert derived.payload["oracle"] == base.payload["oracle"]
    assert derived.content_sha256 == case_content_sha256(derived)
    assert len(public_candidate_screen_pack_sha256()) == 64

    plugin = DataCenterTermsPlugin()
    family_case = plugin.validate_payload(derived.payload)
    state = plugin.initial_state(family_case, run=None)
    observation = plugin.observe(
        family_case, state, "analyst", plugin.phases(family_case)[0]
    )
    encoded = canonical_json_bytes(observation).decode("utf-8")
    assert '"oracle"' not in encoded
    assert '"source_refs"' not in encoded
    assert '"failure_mechanisms"' not in encoded


@pytest.mark.parametrize("field", ["base_pack_sha256", "prompt_suffix"])
def test_candidate_screen_manifest_rejects_drift(tmp_path: Path, field: str) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest[field] = "0" * 64 if field.endswith("sha256") else " changed"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="derivation manifest differs"):
        load_public_candidate_screen_manifest(path)


def test_candidate_screen_design_is_heldout_paired_and_bounded() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 27
    assert design["planned_pairs_per_contrast"] == 9
    assert design["planned_contrast_pair_count"] == 27
    assert design["condition_count"] == 3
    assert design["independent_cluster_count"] == 1
    assert design["worst_case_declared_cost_usd"] == 0.54
    assert {cell["wording_condition"] for cell in design["cells"]} == set(
        CONDITION_ORDER
    )
    assert {cell["model_id"] for cell in design["cells"]} == set(MODEL_ORDER)
    assert {cell["inference_seed"] for cell in design["cells"]} == {
        316001,
        316002,
        316003,
    }
    assert contract["analysis"]["primary_model_slice"] == "qwen3_235b_novita"
    assert contract["analysis"]["primary_contrast"] == (
        "candidate_screen_minus_baseline"
    )
    assert contract["execution"]["sdk_retries"] == 0
    assert contract["execution"]["provider_fallbacks"] is False


def test_candidate_screen_contract_rejects_basis_case_or_route_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    candidates = (
        {
            **contract,
            "diagnostic_basis": {
                **contract["diagnostic_basis"],
                "live_summary_sha256": "0" * 64,
            },
        },
        {
            **contract,
            "conditions": {
                **contract["conditions"],
                "candidate_screen": {
                    **contract["conditions"]["candidate_screen"],
                    "expected_case_sha256": "0" * 64,
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


def test_candidate_screen_passes_gate_and_admission(tmp_path: Path) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "candidate_screen",
            stop_after="profile_admission",
        )
    )
    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 27
    gate = json.loads(
        (
            tmp_path
            / "candidate_screen/provider_free_validation/summary.json"
        ).read_text()
    )
    assert gate["case_count"] == 3
    assert all(row["score"] == 1.0 for row in gate["cases"])


def test_candidate_screen_live_cell_executes_scores_and_replays(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    cell = next(
        row
        for row in build_design(contract)["cells"]
        if row["wording_condition"] == "candidate_screen"
        and row["model_id"] == "qwen3_235b_novita"
        and row["inference_seed"] == 316001
    )
    case = _cases_by_condition()["candidate_screen"]
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
            cases=_cases_by_condition(),
            run_root=tmp_path / "live",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )
    assert result["status"] == "completed"
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
                "usage": {"reported_cost_usd": 0.001},
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


def test_candidate_screen_summary_keeps_contrast_specific_missingness() -> None:
    contract = load_contract()
    rows = _completed_rows()
    failed = copy.deepcopy(rows)
    target = next(
        row
        for row in failed
        if row["wording_condition"] == "affirm_only"
        and row["model_id"] == "mistral32_deepinfra"
        and row["inference_seed"] == 316001
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
    summary = _campaign_summary(contract, failed)

    assert summary["planned_cells"] == 27
    assert summary["completed_cells"] == 26
    assert summary["planned_contrast_pair_count"] == 27
    assert summary["reportable_contrast_pair_count"] == 25
    by_contrast = {
        (row["contrast_id"], row["model_id"]): row
        for row in summary["contrast_summaries"]
    }
    assert by_contrast[("candidate_screen_minus_baseline", "mistral32_deepinfra")][
        "reportable_pairs"
    ] == 3
    assert by_contrast[("affirm_only_minus_baseline", "mistral32_deepinfra")][
        "reportable_pairs"
    ] == 2
    assert by_contrast[("candidate_screen_minus_affirm_only", "mistral32_deepinfra")][
        "reportable_pairs"
    ] == 2
    assert set(CONTRASTS) == {
        row["contrast_id"] for row in summary["contrast_summaries"]
    }


def test_candidate_screen_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = (
        root / "evidence/datacenter_development_terms_public_candidate_screen_v1"
    )
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_candidate_screen_publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert manifest["source_summary_sha256"] == (
        "b2ff5ffea4454829e8709cdd23219835bd4436317d009b1c21e3fe8d659e3f24"
    )
    assert manifest["source_design_sha256"] == (
        "7c1736a1ee79e1f02745158007b470b95b045d5b40c44b60b31f8b5b5726518b"
    )
    assert len(manifest["source_receipt_sha256s"]) == 27
    assert len(manifest["source_result_sha256s"]) == 27
    assert all(value is False for value in manifest["sanitization"].values())

    summary = json.loads((publication / "reports/summary.json").read_text())
    assert summary["completed_cells"] == 22
    assert summary["operational_failure_cells"] == 5
    assert summary["failure_conditions"] == [
        "provider_contract",
        "provider_contract",
        "rate_limit",
        "rate_limit",
        "rate_limit",
    ]
    assert summary["reported_cost_usd"] == pytest.approx(0.00448640775)
    assert summary["provider_cost_complete"] is False
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True

    with (publication / "tables/paired_contrasts.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == 27
    qwen_primary = [
        row
        for row in pairs
        if row["contrast_id"] == "candidate_screen_minus_baseline"
        and row["model_id"] == "qwen3_235b_novita"
    ]
    assert len(qwen_primary) == 3
    assert all(row["pair_reportable"] == "True" for row in qwen_primary)
    assert all(row["treatment_hard_gate_pass"] == "False" for row in qwen_primary)
    assert all(row["score_delta"] == "0.0" for row in qwen_primary)

    payload = b"".join(
        path.read_bytes() for path in publication.rglob("*") if path.is_file()
    ).decode("utf-8").lower()
    assert all(token not in payload for token in PROHIBITED_PUBLIC_TEXT)


@pytest.mark.local_run("datacenter_development_terms_public_candidate_screen_v1")
def test_candidate_screen_publication_is_idempotent() -> None:
    first = publish()
    second = publish()
    assert first == second
