"""Public release tests: no archived campaigns, credentials or paid calls."""
import asyncio
import json

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.refund import v2_5_release as release
from aeread_families.refund import v2_5_payment_units_v51 as units

EXPECTED = {"core": 24, "policy": 76, "v3_common": 8, "v3_intake": 24,
            "v3_payments": 18, "v3_customer": 16, "v4_payments": 8,
            "v4_customer": 4, "v5_intake": 8, "v51_payments": 12, "v5_customer": 6,
            "v71_intake": 32, "v71_customer": 32}


@pytest.mark.parametrize("panel", release.PANELS)
def test_public_cohorts_build_without_campaign_archives(panel):
    setup = release.build_setup(panel, "policy", 301)
    assert len(setup.plan.cells) == EXPECTED[panel]
    assert setup.plan.evaluation_blocks[0].subject_seats == ("policy",)
    assert all(p.model.provider == "scripted" for p in setup.plan.agent_profiles)
    assert all(set(c.profile_by_seat) == set(release.ROLES) for c in setup.plan.cells)


@pytest.mark.parametrize("seat", release.ROLES)
def test_units_contract_and_schema_for_every_controlled_seat(seat):
    original = units.v5.build_run(units.v5.build_panels()["payments"], active_agents=(seat,))
    amended = units.amend_setup(original)
    assert amended.plan.run_plan_id != original.plan.run_plan_id
    for before, after in zip(original.plan.cases, amended.plan.cases):
        assert canonical_json_bytes(before.payload["case"]) == canonical_json_bytes(after.payload["case"])
        plugin = units.UnitsPlugin()
        case = plugin.validate_payload(after.payload)
        assert plugin.build_scorer(case) == units.v5.ExtensionPlugin().build_scorer(case)
        obs = plugin.observe(case, plugin.initial_state(case, None), "payments",
            next(p for p in plugin.phases(case) if p.phase_id == "payments_execute"))
        assert obs["execution_contract"]["amount_units"] == units.UNIT_CONTRACT
    for before, after in zip(original.plan.agent_profiles, amended.plan.agent_profiles):
        if "payments" not in before.profile_id:
            assert canonical_json_bytes(before) == canonical_json_bytes(after)
        else:
            assert units.UNIT_RULE in amended.prompt_sources[after.prompt.prompt_id]
            assert "NOT cents" in after.harness.config["output_schema"]["properties"]["amount"]["description"]


def test_unit_contract_tampering_fails_admission():
    setup = release.build_setup("v51_payments")
    raw = json.loads(canonical_json_bytes(setup.plan.cases[0].payload))
    raw["payment_units_contract"]["output_amount_units"] = "cents"
    with pytest.raises(ValueError, match="unit contract"):
        units.UnitsPlugin().validate_payload(raw)


@pytest.fixture(scope="module")
def public_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("release_parent") / "run"
    result = asyncio.run(release.conformance(root, panels=("v51_payments",), seats=("payments",)))
    assert result["planned"] == result["completed"] == 12
    assert result["paid_calls"] == result["operational_exclusions"] == 0
    assert all(row["independent_replay"] and row["full_score"] for row in result["rows"])
    return root


def test_public_factory_reconstructs_exact_plan(public_run, monkeypatch):
    monkeypatch.setenv("AEREAD_REFUND_V25_RUN_ROOT", str(public_run))
    receipt = json.loads(next(public_run.rglob("evaluation_receipt.json")).read_bytes())
    setup = release.replay_setup(receipt)
    assert setup.plan.run_plan_id == receipt["run_plan_id"]
    with pytest.raises(ValueError, match="uniquely bind"):
        release.replay_setup({**receipt, "run_plan_id": "foreign_plan"})
    monkeypatch.delenv("AEREAD_REFUND_V25_RUN_ROOT")
    with pytest.raises(ValueError, match="Set AEREAD"):
        release.replay_setup(receipt)


def test_public_run_cannot_be_restarted(public_run):
    with pytest.raises(FileExistsError):
        asyncio.run(release.conformance(public_run))


def test_paid_entrypoint_fails_before_credentials_or_client(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Paid initialization is not qualified by this release")
    monkeypatch.setattr(release.core.legacy, "ArenaChatClient", forbidden)
    monkeypatch.setattr(release.core.legacy, "_load_env_file", forbidden)
    with pytest.raises(ValueError, match="provider-free"):
        asyncio.run(release.core.legacy.run(output=tmp_path / "paid", provider="arena"))
    assert not (tmp_path / "paid").exists()


def test_v21_approval_is_not_a_v25_approval(monkeypatch, tmp_path):
    qc = tmp_path / "qc"
    qc.mkdir()
    (qc / "human_qc.json").write_text(json.dumps({
        "family_version": "2.1.0", "decision": "approved", "scope": "developmental_design"}))
    monkeypatch.setattr(release.core.legacy, "QC_ROOT", tmp_path)
    with pytest.raises(ValueError, match="own explicit developmental"):
        release.core.legacy._contribution()
