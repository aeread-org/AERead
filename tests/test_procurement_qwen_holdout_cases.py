from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation.confirmatory_case_matrix import (
    economic_world_sha256,
)
from aeread_families.procurement_allocation.environment import (
    ProcurementAllocationPlugin,
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation.qwen_holdout_case_matrix import (
    CASE_SLUGS,
    OPAQUE_PATHS,
    PRIOR_PATHS,
    STRATA_BY_SLUG,
    build_qwen_holdout_case_matrix,
    write_qwen_holdout_case_matrix,
)
from aeread_families.procurement_allocation.runner import run_fixture_script


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_qwen_holdout_is_new_opaque_digest_stable_and_mechanism_targeted() -> None:
    cases = build_qwen_holdout_case_matrix()
    prior = [_load(path) for path in PRIOR_PATHS]
    prior_content = {case["content_sha256"] for case in prior}
    prior_worlds = {economic_world_sha256(case) for case in prior}
    prior_seeds = {case["world_seed"] for case in prior}

    assert len(cases) == len(CASE_SLUGS) == 6
    assert set(STRATA_BY_SLUG) == set(CASE_SLUGS)
    assert len(set(STRATA_BY_SLUG.values())) == 5
    assert len({case["world_seed"] for case in cases}) == 6
    assert {case["world_seed"] for case in cases}.isdisjoint(prior_seeds)
    assert {case["content_sha256"] for case in cases}.isdisjoint(prior_content)
    assert {economic_world_sha256(case) for case in cases}.isdisjoint(prior_worlds)

    for raw in cases:
        assert raw["split"] == "qwen_holdout_v1_opaque"
        ids = [supplier["supplier_id"] for supplier in raw["payload"]["suppliers"]]
        names = [
            supplier["listing"]["supplier_name"]
            for supplier in raw["payload"]["suppliers"]
        ]
        assert all(re.fullmatch(r"supplier_[0-9a-f]{12}", value) for value in ids)
        assert all(re.fullmatch(r"Supplier [0-9A-F]{12}", value) for value in names)
        case = CaseManifest.from_dict(raw)
        assert case_content_sha256(case) == case.content_sha256
        ProcurementAllocationPlugin().validate_payload(case.payload)


def test_qwen_holdout_oracles_require_split_capacity_and_minimum_service() -> None:
    cases = dict(
        zip(CASE_SLUGS, build_qwen_holdout_case_matrix(), strict=True)
    )
    bounds = {
        slug: solve_full_information_upper_bound(raw["payload"])
        for slug, raw in cases.items()
    }

    assert all(bound.contribution_margin_usd > 0 for bound in bounds.values())
    assert all(bound.actions_required <= 10 for bound in bounds.values())
    assert bounds["dual_component_split"].actions_required == 9
    assert bounds["minimum_service_capacity"].actions_required == 9
    assert bounds["minimum_service_capacity"].completed_kits == 18
    assert bounds["minimum_service_budget"].completed_kits == 18
    assert bounds["minimum_service_budget"].cash_spend_usd <= 50.0

    for slug in CASE_SLUGS[:4]:
        counts: dict[str, int] = {}
        for line in bounds[slug].award_plan:
            counts[line["component"]] = counts.get(line["component"], 0) + 1
        assert max(counts.values()) >= 2
    assert set(
        line["component"] for line in bounds["dual_component_split"].award_plan
    ) == set(cases["dual_component_split"]["payload"]["objective"]["bom"])
    assert all(
        sum(
            line["component"] == component
            for line in bounds["dual_component_split"].award_plan
        )
        == 2
        for component in cases["dual_component_split"]["payload"]["objective"][
            "bom"
        ]
    )


def test_qwen_holdout_oracle_awards_are_reachable_through_public_actions(
    tmp_path: Path,
) -> None:
    generated = write_qwen_holdout_case_matrix(root=tmp_path / "cases")
    for case_path in generated:
        raw = _load(case_path)
        upper = solve_full_information_upper_bound(raw["payload"])
        assert all(line["mode"] == "base" for line in upper.award_plan)
        actions: list[dict] = []
        for line in upper.award_plan:
            supplier_id = line["supplier_id"]
            actions.extend(
                [
                    {
                        "action": "request_quote",
                        "supplier_id": supplier_id,
                        "message": "Issue the exact-variant formal offer.",
                    },
                    {
                        "action": "request_sample",
                        "supplier_id": supplier_id,
                        "message": "Provide the exact-variant qualification sample.",
                    },
                ]
            )
        actions.append(
            {
                "action": "submit_award",
                "award_lines": [
                    {
                        "offer_id": f"offer_{line['supplier_id']}_v1",
                        "quantity": line["quantity"],
                    }
                    for line in upper.award_plan
                ],
            }
        )
        assert len(actions) == upper.actions_required
        _, execution, provider = asyncio.run(
            run_fixture_script(
                [json.dumps(action, sort_keys=True) for action in actions],
                evidence_root=tmp_path / "runs" / case_path.stem,
                case_path=case_path,
            )
        )
        outcome = execution.episode_result.outcome
        assert provider.exhausted
        assert outcome["feasible"] is True
        assert outcome["contribution_margin_usd"] == upper.contribution_margin_usd
        assert outcome["completed_kits"] == upper.completed_kits


def test_qwen_holdout_observation_hides_private_terms() -> None:
    case = CaseManifest.from_dict(build_qwen_holdout_case_matrix()[0])
    plugin = ProcurementAllocationPlugin()
    state = plugin.initial_state(case.payload, None)
    observation = plugin.observe(
        case.payload,
        state,
        "buyer",
        plugin.phases(case.payload)[0],
    )
    serialized = json.dumps(observation, sort_keys=True)
    assert "private_terms" not in serialized
    assert '"capacity":' not in serialized
    assert '"order_step":' not in serialized
    assert '"verified_yield_rate":' not in serialized


def test_tracked_qwen_holdout_cases_match_generator(tmp_path: Path) -> None:
    generated = write_qwen_holdout_case_matrix(root=tmp_path / "opaque")
    for candidate, tracked in zip(generated, OPAQUE_PATHS, strict=True):
        assert candidate.read_bytes() == tracked.read_bytes()
