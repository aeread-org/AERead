"""Publish provider-free Housing environment and verifier golden receipts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import (
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    execute_plan_cell,
)

from .runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
    finalize_housing_execution,
    finalize_housing_failure,
    replay_housing_receipt,
)


CONTRACT_SCHEMA_VERSION = "aeread.housing_qc_goldens/0.1"
BUNDLE_SCHEMA_VERSION = "aeread.housing_qc_bundle/0.1"
_ROOT_FIELDS = {
    "schema_version",
    "bundle_id",
    "claim_status",
    "created_date",
    "external_provider_calls_allowed",
    "scenarios",
    "publication",
}
_SCENARIO_FIELDS = {
    "scenario_id",
    "tenant_fixture",
    "world_seed",
    "tenants",
    "listings",
    "rounds",
    "common_weight",
    "expected_receipt_status",
    "expected_inclusion_status",
    "expected_within_case_score",
    "expected_action_failure",
}
_FIXTURES = {
    "scripted",
    "noop",
    "invalid_listing",
    "malformed",
    "provider_failure",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output["artifact_sha256"] = _sha256_bytes(canonical_json_bytes(output))
    return output


def _write_immutable(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise ValueError(
                f"refusing to replace different published evidence: {path}"
            )
        return
    path.write_bytes(value)


def load_contract(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict) or set(value) != _ROOT_FIELDS:
        raise ValueError("Housing QC golden contract fields are invalid")
    if value["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported Housing QC golden contract schema")
    if value["bundle_id"] != "housing_qc_goldens_v1":
        raise ValueError("unsupported Housing QC golden bundle identity")
    if value["claim_status"] != "provider_free_environment_and_verifier_qc":
        raise ValueError("Housing QC goldens cannot carry a model-performance claim")
    if value["external_provider_calls_allowed"] is not False:
        raise ValueError("Housing QC goldens must prohibit external provider calls")
    scenarios = value["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) != 6:
        raise ValueError("Housing QC requires exactly six golden scenarios")
    scenario_ids: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != _SCENARIO_FIELDS:
            raise ValueError("Housing QC golden scenario fields are invalid")
        scenario_id = scenario["scenario_id"]
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ValueError("Housing QC scenario IDs must be non-empty strings")
        if scenario_id in scenario_ids:
            raise ValueError("Housing QC scenario IDs must be unique")
        scenario_ids.add(scenario_id)
        if scenario["tenant_fixture"] not in _FIXTURES:
            raise ValueError("Housing QC scenario uses an unknown fixture")
        for field in ("world_seed", "tenants", "listings", "rounds"):
            if isinstance(scenario[field], bool) or not isinstance(
                scenario[field], int
            ):
                raise ValueError(f"Housing QC {field} must be an integer")
        if min(scenario["tenants"], scenario["listings"], scenario["rounds"]) < 1:
            raise ValueError("Housing QC dimensions must be positive")
        if not isinstance(scenario["common_weight"], (int, float)):
            raise ValueError("Housing QC common_weight must be numeric")
    if set(value["publication"]) != {
        "local_source",
        "raw_provider_responses_included",
        "model_reasoning_included",
        "receipt_projection",
    }:
        raise ValueError("Housing QC publication contract is invalid")
    if value["publication"]["raw_provider_responses_included"] is not False:
        raise ValueError("raw provider responses must remain local")
    if value["publication"]["model_reasoning_included"] is not False:
        raise ValueError("model reasoning must remain local")
    return value


def _fixture_result(
    request: ProviderRequest, text: str, fixture: str
) -> ProviderResult:
    return ProviderResult(
        response_id=f"housing_qc_{fixture}_{request.provider_call_id}",
        requested_model=request.model,
        resolved_model=request.revision or request.model,
        output_text=text,
        finish_reason="stop",
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        raw_response={"fixture": fixture, "output_text": text},
    )


class HousingQCTenantProvider:
    """Deterministic negative-control provider used only by the QC bundle."""

    def __init__(self, fixture: str) -> None:
        if fixture not in _FIXTURES - {"scripted"}:
            raise ValueError("Housing QC fixture provider requires a negative fixture")
        self.fixture = fixture

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if self.fixture == "provider_failure":
            raise ProviderFailure(
                "provider_contract",
                "declared Housing QC provider failure",
                retryable=False,
            )
        payload = json.loads(request.input_text)
        phase_id = payload["phase_id"]
        if self.fixture == "malformed":
            text = "not-json"
        elif self.fixture == "invalid_listing" and phase_id == "contact":
            text = json.dumps(
                {"decision": "offer", "listing_id": 999, "rent": 1.0},
                sort_keys=True,
                separators=(",", ":"),
            )
        elif phase_id == "contact":
            text = '{"decision":"pass","listing_id":null,"rent":null}'
        elif phase_id == "commit":
            text = '{"decision":"pass","hold_id":null}'
        else:  # pragma: no cover - tenant profiles never receive respond phases
            raise ProviderFailure(
                "provider_contract",
                f"Housing QC tenant received unexpected phase {phase_id!r}",
                retryable=False,
            )
        return _fixture_result(request, text, self.fixture)


def _setup_for_scenario(scenario: Mapping[str, Any]):
    fixture = scenario["tenant_fixture"]
    if fixture == "scripted":
        tenant_provider = "housing_scripted_tenant"
        tenant_model = "housing_scripted_tenant_v1"
        provider = HousingScriptedTenantProvider()
    else:
        tenant_provider = f"housing_qc_{fixture}"
        tenant_model = f"housing_qc_{fixture}_v1"
        provider = HousingQCTenantProvider(fixture)
    setup = build_housing_smoke(
        tenant_provider=tenant_provider,
        tenant_model=tenant_model,
        tenant_revision="1.0.0",
        world_seed=scenario["world_seed"],
        num_tenants=scenario["tenants"],
        num_listings=scenario["listings"],
        rounds=scenario["rounds"],
        common_weight=scenario["common_weight"],
    )
    return setup, tenant_provider, provider


def _action_failure_summary(execution: Any) -> dict[str, Any]:
    parse_codes: list[str] = []
    legality_reasons: list[str] = []
    for phase in execution.episode_result.phase_instances:
        for action in phase.actions:
            if not action.parse.ok:
                parse_codes.append(action.parse.error_code)
            elif action.legality is not None and not action.legality.legal:
                legality_reasons.append(action.legality.reason)
    return {
        "parse_failure_count": len(parse_codes),
        "parse_failure_codes": sorted(set(parse_codes)),
        "legality_failure_count": len(legality_reasons),
        "legality_failure_reasons": sorted(set(legality_reasons)),
    }


def _within_case_score(receipt: Any) -> float | None:
    if not receipt.scores:
        return None
    metric = receipt.scores[0].metrics.get("within_case_score")
    return None if metric is None else float(metric.value)


def _assert_expected(scenario: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    if row["receipt_status"] != scenario["expected_receipt_status"]:
        raise ValueError(f"{scenario['scenario_id']} receipt status drifted")
    if row["inclusion_status"] != scenario["expected_inclusion_status"]:
        raise ValueError(f"{scenario['scenario_id']} inclusion status drifted")
    expected_score = scenario["expected_within_case_score"]
    actual_score = row["within_case_score"]
    if expected_score is None:
        if actual_score is not None:
            raise ValueError(f"{scenario['scenario_id']} unexpectedly normalized")
    elif actual_score != float(expected_score):
        raise ValueError(f"{scenario['scenario_id']} score drifted")
    expected_failure = scenario["expected_action_failure"]
    if expected_failure == "none" and (
        row["parse_failure_count"] or row["legality_failure_count"] or row["failure"]
    ):
        raise ValueError(f"{scenario['scenario_id']} had an unexpected failure")
    if expected_failure == "parse" and row["parse_failure_count"] < 1:
        raise ValueError(f"{scenario['scenario_id']} did not record a parse failure")
    if expected_failure == "legality" and row["legality_failure_count"] < 1:
        raise ValueError(f"{scenario['scenario_id']} did not record an illegal action")
    if expected_failure == "provider" and (
        not row["failure"] or row["failure"]["condition"] != "provider_contract"
    ):
        raise ValueError(f"{scenario['scenario_id']} did not retain provider failure")


async def _run_scenario(
    scenario: Mapping[str, Any], *, run_root: Path
) -> tuple[dict[str, Any], Any]:
    setup, tenant_provider, provider = _setup_for_scenario(scenario)
    cell = setup.plan.cells[0]
    execution = None
    try:
        execution = await execute_plan_cell(
            plan=setup.plan,
            cell_id=cell.cell_id,
            registry=setup.registry,
            evidence_root=run_root / scenario["scenario_id"],
            prompt_sources=setup.prompt_sources,
            providers={
                tenant_provider: provider,
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            harnesses=setup.harnesses,
            episode_attempt_ordinal=0,
        )
        receipt = finalize_housing_execution(setup=setup, execution=execution)
        replayed = replay_housing_receipt(
            setup=setup,
            receipt=receipt,
            evidence_root=run_root / scenario["scenario_id"],
        )
        replay_verified = canonical_json_bytes(replayed) == canonical_json_bytes(
            receipt
        )
        outcome = execution.episode_result.outcome
        action_failures = _action_failure_summary(execution)
        cost_usd = execution.total_cost_usd
    except Exception as error:
        receipt = finalize_housing_failure(
            setup=setup,
            cell_id=cell.cell_id,
            evidence_root=run_root / scenario["scenario_id"],
            error=error,
        )
        replay_verified = False
        outcome = None
        action_failures = {
            "parse_failure_count": 0,
            "parse_failure_codes": [],
            "legality_failure_count": 0,
            "legality_failure_reasons": [],
        }
        cost_usd = 0.0
    failure = None
    if receipt.failure is not None:
        failure = {
            "failure_class": receipt.failure.failure_class,
            "condition": receipt.failure.condition,
        }
    row = {
        "scenario_id": scenario["scenario_id"],
        "category": scenario["expected_action_failure"],
        "world_seed": scenario["world_seed"],
        "run_plan_id": receipt.run_plan_id,
        "cell_id": receipt.cell_id,
        "episode_attempt_id": receipt.episode_attempt_id,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_status": receipt.status,
        "inclusion_status": receipt.inclusion_status,
        "replay_level": receipt.replay_level,
        "replay_verified": replay_verified,
        "within_case_score": _within_case_score(receipt),
        "social_welfare": None if outcome is None else outcome["social_welfare"],
        "oracle_upper_bound": None if outcome is None else outcome["oracle_total"],
        "failure": failure,
        "cost_usd": cost_usd,
        **action_failures,
    }
    _assert_expected(scenario, row)
    return row, receipt


async def execute_bundle(
    *, contract_path: str | Path, run_root: str | Path, publish_root: str | Path
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    rows: list[dict[str, Any]] = []
    receipt_refs: list[dict[str, Any]] = []
    for scenario in contract["scenarios"]:
        row, receipt = await _run_scenario(scenario, run_root=Path(run_root))
        receipt_path = (
            Path(publish_root) / "receipts" / f"{scenario['scenario_id']}.json"
        )
        receipt_bytes = canonical_json_bytes(receipt) + b"\n"
        _write_immutable(receipt_path, receipt_bytes)
        receipt_refs.append(
            {
                "scenario_id": scenario["scenario_id"],
                "path": f"receipts/{scenario['scenario_id']}.json",
                "file_sha256": _sha256_bytes(receipt_bytes),
                "receipt_sha256": receipt.receipt_sha256,
            }
        )
        rows.append(row)
    report = _sealed(
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "bundle_id": contract["bundle_id"],
            "created_date": contract["created_date"],
            "status": "passed",
            "claim_status": contract["claim_status"],
            "external_provider_calls": 0,
            "provider_cost_usd": sum(row["cost_usd"] for row in rows),
            "scenario_count": len(rows),
            "implementation_sha256": _sha256_bytes(Path(__file__).read_bytes()),
            "contract_sha256": _sha256_bytes(Path(contract_path).read_bytes()),
            "local_source": contract["publication"]["local_source"],
            "raw_provider_responses_included": False,
            "model_reasoning_included": False,
            "receipts": receipt_refs,
            "scenarios": rows,
        }
    )
    report_path = Path(publish_root) / "reports" / "qc_bundle.json"
    _write_immutable(report_path, canonical_json_bytes(report) + b"\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract", default="configs/housing_qc_goldens_v1.json"
    )
    parser.add_argument(
        "--run-root", type=Path, default=Path("runs/housing_qc_goldens_v1")
    )
    parser.add_argument(
        "--publish-root", type=Path, default=Path("evidence/housing_qc_goldens_v1")
    )
    arguments = parser.parse_args(argv)
    result = asyncio.run(
        execute_bundle(
            contract_path=arguments.contract,
            run_root=arguments.run_root,
            publish_root=arguments.publish_root,
        )
    )
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
