"""The lemons refusal pilot: contract, frozen pack, gates, halt rule, analysis."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.contract import ContractError, read_sealed
from aeread.shared_runner.task.execution import ProviderFailure, ProviderResult
from aeread_families.housing import lemons
from aeread_families.housing import lemons_campaign as lc


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs" / "housing_lemons_refusal_pilot_v1.json"


def _contract_dict() -> dict:
    return json.loads(CONTRACT_PATH.read_bytes())


def _write(tmp_path: Path, value: dict, name: str = "contract.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _reduced_contract(tmp_path: Path, *, halt_after: int = 3) -> Path:
    """The same campaign with one world per stratum, so live stages stay small.
    The seed lists are what the selection rule yields from the same stream."""
    value = _contract_dict()
    value["world_pack"]["worlds_per_stratum"] = 1
    value["variance_pilot"]["world_seeds"] = [100001, 100002]
    value["variance_pilot"]["strata"] = {
        "favourite_is_lemon": [100001],
        "favourite_is_sound": [100002],
    }
    value["controls"]["max_consecutive_operational_failures"] = halt_after
    return _write(tmp_path, value)


class PolicyClient:
    """A live client that plays a scripted lemons policy, optionally failing a
    window of calls so a stage halts and resumes."""

    def __init__(self, policy: str = "inspect_then_sign", fail_window=None) -> None:
        self.policy = policy
        self.fail_window = fail_window
        self.calls = 0

    async def complete(self, request) -> ProviderResult:
        self.calls += 1
        if self.fail_window and self.fail_window[0] <= self.calls <= self.fail_window[1]:
            raise ProviderFailure("provider_5xx", "down", retryable=False, status_code=503)
        payload = json.loads(request.input_text)
        action = lemons.TENANT_POLICIES[self.policy](payload["observation"], payload["phase_id"])
        return ProviderResult(
            response_id=f"fake_{self.calls}",
            requested_model=request.model,
            resolved_model=request.revision,
            output_text=json.dumps(action),
            finish_reason="stop",
            input_tokens=10,
            cached_input_tokens=0,
            output_tokens=5,
            cost_usd=0.001,
            raw_response={},
        )


# ---------------------------------------------------------------------------
# Contract and pack
# ---------------------------------------------------------------------------


def test_contract_loads_and_every_drift_is_refused(tmp_path):
    contract = lc.load_contract(CONTRACT_PATH)
    assert contract["campaign_id"] == lc.CAMPAIGN_ID
    assert len(contract["variance_pilot"]["world_seeds"]) == 24
    mutations = {
        "environment": lambda v: v["environment"].update(lemon_loss=900.0),
        "admission rule": lambda v: v["admission_rule"].update(lemon_count_min=0),
        "controls": lambda v: v["controls"].update(max_action_attempts=1),
        "consecutive": lambda v: v["controls"].update(max_consecutive_operational_failures=0),
        "ceiling": lambda v: v["controls"].update(tenant_cost_ceiling_usd=-1),
        "route": lambda v: v["route"].update(canonical_model="google/gemini-3.8-flash"),
        "unknown route": lambda v: v["route"].update(route_id="mystery"),
        "controls panel": lambda v: v.update(scripted_controls=["pass"]),
        "strata": lambda v: v["variance_pilot"]["strata"]["favourite_is_lemon"].append(100031),
        "overlap": lambda v: v["variance_pilot"]["world_seeds"].__setitem__(0, 100000),
        "claim": lambda v: v["variance_pilot"].update(winner_claim_allowed=True),
        "analysis": lambda v: v["analysis"].update(bootstrap_seed=0),
        "extra field": lambda v: v.update(extra=1),
        "schema": lambda v: v.update(schema_version="aeread.housing_lemons_campaign/0.2"),
    }
    for label, mutate in mutations.items():
        value = _contract_dict()
        mutate(value)
        with pytest.raises(ContractError):
            lc.load_contract(_write(tmp_path, value, f"{label}.json"))


def test_pack_is_what_the_seed_stream_yields():
    contract = lc.load_contract(CONTRACT_PATH)
    selected = lc.select_world_pack(contract)
    assert selected["full_trajectory"] == contract["full_trajectory"]["world_seeds"]
    assert selected["strata"] == contract["variance_pilot"]["strata"]
    assert selected["variance_pilot"] == contract["variance_pilot"]["world_seeds"]
    assert selected["scanned_seed_count"] == 31 and selected["excluded_seed_count"] == 6
    for seed in contract["variance_pilot"]["world_seeds"]:
        row = lc.world_row(contract, seed)
        assert row["admitted"] and row["stratum"] == lc._stratum_of(contract, seed)
        world = lc._make_world(contract["environment"], seed)
        favourite = lc.favourite_listing(world)
        assert (world.quality[favourite] == lemons.LEMON) == (row["stratum"] == "favourite_is_lemon")


def test_design_and_provider_free_gates_pass_offline(tmp_path):
    result = asyncio.run(
        lc.execute_campaign(
            contract_path=CONTRACT_PATH,
            output_root=tmp_path / "campaign",
            through="provider_free_validation",
        )
    )
    assert result["gate_summaries"]["design_contract"]["status"] == "passed"
    assert result["gate_summaries"]["provider_free_validation"]["status"] == "passed"
    design = read_sealed(tmp_path / "campaign" / "design_contract" / "summary.json")
    assert design["world_count"] == 25 and design["planned_live_cells"] == 49
    assert design["worst_case_declared_cost_usd"] == 14.7
    assert design["stage_cost_ceilings_usd"] == 6.5
    assert design["plans"][1]["prompt_id"] == "housing_tenant_lemons_v1"
    assert design["plans"][1]["tenant_profile_id"] == "housing_lemons_gemini_38_flash_tenant_v1"
    summary = read_sealed(tmp_path / "campaign" / "provider_free_validation" / "summary.json")
    assert summary["provider_cost_usd"] == 0.0 and summary["runner_matches_offline_gate"] is True
    assert len(summary["rows"]) == 75
    by_policy = {}
    for row in summary["rows"]:
        by_policy.setdefault(row["policy"], []).append(row["tenant_net_payoff"])
    assert all(value == 0.0 for value in by_policy["pass"])
    assert max(by_policy["sign_anything"]) < 0 < min(by_policy["inspect_then_sign"])
    history = json.loads((tmp_path / "campaign" / "gate_history.json").read_bytes())
    assert [record["gate_id"] for record in history["records"]] == [
        "design_contract",
        "provider_free_validation",
    ]
    # Resumed rows are read back, not recomputed: a second run is instant and idempotent.
    again = asyncio.run(
        lc.execute_campaign(
            contract_path=CONTRACT_PATH,
            output_root=tmp_path / "campaign",
            through="provider_free_validation",
        )
    )
    assert all(item["status"] == "already_passed" for item in again["gate_summaries"].values())


# ---------------------------------------------------------------------------
# Live gates with a fake client
# ---------------------------------------------------------------------------


def test_profile_admission_probes_every_lemons_schema(tmp_path):
    contract = lc.load_contract(_reduced_contract(tmp_path))
    client = PolicyClient()
    artifact = asyncio.run(lc.run_profile_admission(contract, client=client))
    assert artifact["status"] == "passed" and artifact["probe_count"] == 9
    assert {row["action_schema"] for row in artifact["results"]} == set(lc.ADMISSION_SCHEMAS)
    assert client.calls == 9
    with pytest.raises(ValueError, match="semantically invalid"):
        lc._validate_admission_action(
            "housing_inspect_v1",
            json.dumps({"decision": "inspect", "listing_id": 99}),
            lc._admission_observations(contract["environment"], 73_001)["housing_inspect_v1"],
        )


def test_live_stages_run_halt_and_resume_without_paying_twice(tmp_path):
    contract_path = _reduced_contract(tmp_path, halt_after=2)
    root = tmp_path / "campaign"
    good = PolicyClient()
    result = asyncio.run(
        lc.execute_campaign(contract_path=contract_path, output_root=root, through="full_trajectory", client=good)
    )
    assert result["gate_summaries"]["full_trajectory"]["status"] == "passed"
    full = read_sealed(root / "full_trajectory" / "summary.json")
    assert full["completed_cells"] == 1 and full["claim_status"] == "integration_only"
    row = full["rows"][0]
    assert row["status"] == "completed" and row["replay_verified"] is True
    assert row["tenant_net_payoff"] == row["reference_total"]  # the fake plays the reference

    # The pilot: the first cell completes, then the provider goes down for a window
    # long enough to fail two cells in a row; the stage halts and seals the rest.
    calls_per_cell = good.calls  # full trajectory was one cell of the same size
    flaky = PolicyClient(fail_window=(calls_per_cell + 1, 10**9))
    halted = asyncio.run(
        lc.execute_campaign(contract_path=contract_path, output_root=root, through="variance_pilot", client=flaky)
    )
    assert halted["gate_summaries"]["variance_pilot"]["status"] == "failed"
    assert "halted after 2 consecutive" in halted["gate_summaries"]["variance_pilot"]["message"]
    summary = read_sealed(root / "variance_pilot" / "summary.json")
    statuses = [row["status"] for row in summary["rows"]]
    assert statuses == ["completed", "operational_failure", "operational_failure", "not_attempted"]
    assert summary["halted_at"] == "world_100002__rep_0"  # cells run world, then replicate
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["rows"][3]["failure_condition"] == "halted_after_consecutive_operational_failures"
    history = json.loads((root / "gate_history.json").read_bytes())
    assert history["records"][-1]["status"] == "failed"

    # A second attempt reuses the completed cell and pays only for the rest.
    resumed_client = PolicyClient()
    resumed = asyncio.run(
        lc.execute_campaign(contract_path=contract_path, output_root=root, through="variance_pilot", client=resumed_client)
    )
    assert resumed["gate_summaries"]["variance_pilot"]["status"] == "passed"
    summary = read_sealed(root / "variance_pilot" / "attempt_2" / "summary.json")
    assert summary["completed_cells"] == 4 and summary["complete_pack"] is True
    assert summary["rows"][0]["reused_from_attempt"] == 1
    assert all("reused_from_attempt" not in row for row in summary["rows"][1:])
    assert resumed_client.calls < 4 * calls_per_cell
    analysis = summary["analysis"]
    assert analysis["completed_cells"] == 4 and analysis["reference_worlds"] == 3
    assert analysis["overall"]["live_minus_reference_net_payoff"]["point"] == 0.0
    assert analysis["overall"]["abstention_correctness_rate"]["point"] == 1.0
    assert analysis["by_stratum"]["favourite_is_lemon"]["worlds"] == 1
    assert analysis["winner_claim_allowed"] is False
    assert summary["rows"][0]["commit_decisions"]

    # Publication: a sanitized, digest-bound bundle with the trajectory grain.
    bundle = tmp_path / "evidence" / "housing" / lc.CAMPAIGN_ID
    published = lc.publish(contract_path=contract_path, run_root=root, publication_root=bundle)
    assert published["live_cells"] == 5 and published["control_cells"] == 9
    assert published["trajectory_rows"] > 0 and published["receipts"] == 14
    manifest = json.loads((bundle / "publication_manifest.json").read_bytes())
    assert manifest["campaign_id"] == lc.CAMPAIGN_ID and manifest["winner_claim_allowed"] is False
    assert set(manifest["artifacts"]) >= {
        "README.md", "reports/design.json", "reports/variance_pilot.json", "reports/analysis.json",
        "qc/provider_free_validation.json", "qc/profile_admission.json", "tables/cells.jsonl",
        "tables/scripted_controls.jsonl", "trajectories/sanitized.jsonl",
        "reports/variance_pilot_attempt_1.json",
    }
    assert manifest["prior_pilot_attempts"] == 1
    first_attempt = json.loads((bundle / "reports/variance_pilot_attempt_1.json").read_bytes())
    assert [row["status"] for row in first_attempt["rows"]] == [
        "completed", "operational_failure", "operational_failure", "not_attempted",
    ]
    for relative, digest in manifest["artifacts"].items():
        payload = (bundle / relative).read_bytes()
        assert __import__("hashlib").sha256(payload).hexdigest() == digest
        lc.assert_public_payload(relative, payload)
    with pytest.raises(ValueError, match="not empty"):
        lc.publish(contract_path=contract_path, run_root=root, publication_root=bundle)


def test_analysis_is_deterministic_and_world_clustered():
    contract = lc.load_contract(CONTRACT_PATH)
    seeds = contract["variance_pilot"]["world_seeds"][:6]
    live = [
        {
            "status": "completed",
            "world_seed": seed,
            "replicate_index": replicate,
            "stratum": lc._stratum_of(contract, seed),
            "tenant_net_payoff": 100.0 + index * 10 + replicate,
            "within_case_score": 0.1 * (index + 1),
            "abstention_correctness_rate": 1.0 if index % 2 else 0.5,
            "uninspected_lemon_signings": index % 3,
        }
        for index, seed in enumerate(seeds)
        for replicate in range(2)
    ] + [{"status": "operational_failure", "world_seed": seeds[0], "replicate_index": 2, "stratum": "favourite_is_lemon"}]
    controls = [
        {"policy": "inspect_then_sign", "status": "completed", "world_seed": seed, "tenant_net_payoff": 120.0}
        for seed in seeds
    ] + [
        {"policy": "sign_anything", "status": "completed", "world_seed": seed, "tenant_net_payoff": -500.0}
        for seed in seeds
    ]
    first = lc.analyze_pilot(live, controls, contract)
    second = lc.analyze_pilot(live, controls, contract)
    assert first == second
    overall = first["overall"]
    assert overall["worlds"] == 6 and overall["cells"] == 12
    assert overall["tenant_net_payoff"]["ci95"][0] <= overall["tenant_net_payoff"]["point"] <= overall["tenant_net_payoff"]["ci95"][1]
    assert overall["live_minus_reference_net_payoff"]["point"] == pytest.approx(
        sum((100.0 + i * 10 + 0.5) - 120.0 for i in range(6)) / 6
    )
    assert overall["cells_below_sign_anything"] == 0
    assert first["missingness_fraction"] == pytest.approx(1 / 13)
    assert list(first["predeclared"]["endpoint_order"]) == list(lc.ENDPOINT_ORDER)
    # A single-world stratum reports its point without an interval.
    lonely = lc.analyze_pilot(live[:2], controls, contract)
    assert lonely["overall"]["tenant_net_payoff"]["ci95"] is None


def test_an_incomplete_pilot_publishes_only_on_a_stated_reason(tmp_path):
    contract_path = _reduced_contract(tmp_path, halt_after=3)
    root = tmp_path / "campaign"
    asyncio.run(
        lc.execute_campaign(contract_path=contract_path, output_root=root, through="full_trajectory", client=PolicyClient())
    )
    # The first pilot call fails, so the first cell is lost and the rest complete:
    # the gate fails on an incomplete pack, but the stage ran to the end.
    lossy = PolicyClient(fail_window=(1, 1))
    result = asyncio.run(
        lc.execute_campaign(contract_path=contract_path, output_root=root, through="variance_pilot", client=lossy)
    )
    assert result["gate_summaries"]["variance_pilot"]["message"] == "variance_pilot pack is incomplete"
    bundle = tmp_path / "evidence" / "incomplete"
    with pytest.raises(ValueError, match="no passed attempt"):
        lc.publish(contract_path=contract_path, run_root=root, publication_root=bundle)
    with pytest.raises(ValueError, match="stated reason"):
        lc.publish(contract_path=contract_path, run_root=root, publication_root=bundle, incomplete_pilot_reason=" ")

    published = lc.publish(
        contract_path=contract_path, run_root=root, publication_root=bundle,
        incomplete_pilot_reason="HL-O-07, owner's decision",
    )
    assert published["live_cells"] == 5
    manifest = json.loads((bundle / "publication_manifest.json").read_bytes())
    assert manifest["pilot_gate_status"] == "failed_incomplete_pack"
    assert manifest["incomplete_pilot_reason"] == "HL-O-07, owner's decision"
    assert manifest["missing_pilot_cells"] == ["world_100001__rep_0"]
    readme = (bundle / "README.md").read_text()
    assert "**Incomplete pack.**" in readme and "`world_100001__rep_0` is typed missingness" in readme
    analysis = json.loads((bundle / "reports/analysis.json").read_bytes())
    assert analysis["completed_cells"] == 3 and analysis["missingness_fraction"] == 0.25

    # Once an attempt passes, the reason is refused: a complete pilot publishes normally.
    asyncio.run(
        lc.execute_campaign(contract_path=contract_path, output_root=root, through="variance_pilot", client=PolicyClient())
    )
    with pytest.raises(ValueError, match="passed; publish it without"):
        lc.publish(
            contract_path=contract_path, run_root=root, publication_root=tmp_path / "evidence" / "again",
            incomplete_pilot_reason="HL-O-07",
        )
    complete = lc.publish(contract_path=contract_path, run_root=root, publication_root=tmp_path / "evidence" / "complete")
    manifest = json.loads((tmp_path / "evidence" / "complete" / "publication_manifest.json").read_bytes())
    assert "pilot_gate_status" not in manifest and complete["live_cells"] == 5
