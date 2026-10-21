"""The version 2 OpenRouter driver and report: what they keep from version 1, the schema, the seeds, the freeze,
and provider-free cells whose traces the report re-drives to the recorded margin.

Nothing here makes a provider call.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "tools" / "cli_subjects"))

import pay_or_test_openrouter as v1  # noqa: E402
import pay_or_test_v2_openrouter as driver  # noqa: E402
import pay_or_test_v2_report as report  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_v2_case_matrix as pack_module  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_v2_reference as reference  # noqa: E402
from aeread_families.procurement_allocation.environment import ACTION_FIELDS  # noqa: E402
from aeread_families.procurement_allocation.runner import SequenceResponseProvider  # noqa: E402
from tests.test_pay_or_test_openrouter import MUTATIONS, RESIDUAL, STRICT_FORM, _admits, _replies  # noqa: E402

PILOT = pack_module.case_paths(split=pack_module.PILOT_PACK_ID)
COMMITTED = pack_module.case_paths()


def _credit(remaining: float):
    return lambda: {"total_credits_usd": 100.0, "total_usage_usd": 100.0 - remaining, "remaining_usd": remaining}


# --- what version 2 keeps from version 1 ----------------------------------------------------


@pytest.mark.parametrize("subject", ["gemini38_flash", "gpt6_luna"])
def test_each_route_is_the_version_one_pin_with_only_its_profile_id_changed(subject: str) -> None:
    mine, theirs = driver.SUBJECTS[subject], v1.SUBJECTS[subject]
    assert dataclasses.replace(mine["route"], profile_id=theirs["route"].profile_id) == theirs["route"]
    assert mine["route"].profile_id == f"procurement_pay_or_test_v2_{subject}_v1" != theirs["route"].profile_id
    assert {k: v for k, v in mine.items() if k != "route"} == {k: v for k, v in theirs.items() if k != "route"}


def test_the_subjects_are_the_two_the_plan_requires() -> None:
    assert sorted(driver.SUBJECTS) == ["gemini38_flash", "gpt6_luna"]


def test_every_control_but_the_seeds_and_the_ceilings_is_version_ones() -> None:
    kept = {k: v for k, v in v1.CONTROLS.items() if k not in ("inference_seed", "total_cost_ceiling_usd", "replicates")}
    assert {k: v for k, v in driver.CONTROLS.items() if k not in ("inference_seeds", "total_cost_ceiling_usd")} == kept
    assert driver.CONTROLS["max_cost_usd_per_trajectory"] == 0.30
    assert driver.CONTROLS["max_consecutive_operational_failures"] == 3
    assert driver.RETRY_POLICY is v1.RETRY_POLICY and driver.HALT_RULE == v1.HALT_RULE
    assert driver.action_output_schema is v1.action_output_schema


def test_the_seeds_are_the_plans() -> None:
    assert driver.CONTROLS["inference_seeds"] == {"gate": [87001], "pilot": [87001, 87002],
                                                  "confirmatory": [87001, 87002]}


def test_the_prompt_is_version_twos_shared_source_brief() -> None:
    assert driver.PROMPT["prompt_id"] == "procurement_allocation_pay_or_test_shared_source_v1"
    assert "same_source_probability" in driver.PROMPT["text"]


# --- panels, packs and identities -----------------------------------------------------------


def test_the_gate_plays_the_pilot_packs_first_world_and_the_pilot_plays_all_twelve() -> None:
    manifest = json.loads((pack_module.pack_root(pack_module.PILOT_PACK_ID) / "pack.json").read_text())
    (gate,) = driver.case_paths("gate")
    assert gate.stem == manifest["worlds"][0]["slug"] and gate.parent.name == pack_module.PILOT_PACK_ID
    assert [p.stem for p in driver.case_paths("pilot")] == sorted(w["slug"] for w in manifest["worlds"])
    assert len(driver.case_paths("pilot")) == 12


def test_the_pilot_and_the_committed_pack_scan_disjoint_seed_ranges() -> None:
    ranges = []
    for split in pack_module.SPLITS:
        specs = pack_module.world_specs(split)
        ranges.append((specs[0]["seed_block"], specs[-1]["seed_block"] + pack_module.SEEDS_PER_WORLD))
    (a0, a1), (b0, b1) = sorted(ranges)
    assert a1 <= b0


def test_identities_never_reuse_a_version_one_root_and_are_what_the_report_reads() -> None:
    names = {driver.default_run_root(s, p).name for s in driver.SUBJECTS for p in ("gate", "pilot")}
    assert len(names) == 4 and all(n.startswith(report.PREFIX) for n in names)
    assert not any(driver.default_run_root(s, "pilot").name == v1.default_run_root(s, "panel").name for s in driver.SUBJECTS)


def test_the_confirmatory_panel_refuses_without_a_freeze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver, "FREEZE_PATH", tmp_path / "absent.json")
    with pytest.raises(FileNotFoundError, match="committed freeze"):
        driver.model_plan("gpt6_luna", "confirmatory")


@pytest.mark.parametrize("subject", sorted(driver.SUBJECTS))
def test_the_profile_seals_the_play_seed_and_the_plan_seals_the_reference(subject: str) -> None:
    path = driver.case_paths("gate")[0]
    for seed in (87001, 87002):
        setup = driver.build_setup(subject, path, seed)
        (profile,) = setup.plan.agent_profiles
        assert profile.sampling.seed == seed
    plan = driver.model_plan(subject, "pilot")
    digest = hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest()
    assert plan["headline_reference"]["sha256"] == digest == plan["sources"][driver.HEADLINE_REFERENCE]
    assert plan["planned_trajectory_count"] == 24 and plan["inference_seeds"] == [87001, 87002]
    assert plan["sources"] == driver.source_digests() and plan["driver"]["sha256"] == driver.DRIVER_SHA256
    assert plan["controls"]["total_cost_ceiling_usd"] == driver.ceiling(subject, "pilot")


# --- the action schema agrees with the family parser on every version 2 world -------------


@pytest.mark.parametrize("path", [*PILOT, *COMMITTED], ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_on_every_v2_world_the_schema_and_the_parser_agree_but_for_the_residual(path: Path) -> None:
    payload = driver._payload(path)
    schema = driver.action_output_schema(payload)
    hit = set()
    for action, reply in _replies(payload).items():
        assert _admits(schema, reply) and driver.parse_reply(path, json.dumps(reply))["ok"], action
        for field, label, value in MUTATIONS:
            mutated = {**copy.deepcopy(reply), field: copy.deepcopy(value)}
            admitted, accepted = _admits(schema, mutated), driver.parse_reply(path, json.dumps(mutated))["ok"]
            if field not in ACTION_FIELDS[action]:
                assert accepted, (action, field, label)
            elif (action, field, label) in RESIDUAL:
                assert admitted and not accepted, (action, field, label)
                hit.add(RESIDUAL[(action, field, label)])
            elif (action, field, label) in STRICT_FORM:
                assert accepted and not admitted, (action, field, label)
            else:
                assert admitted == accepted, (action, field, label, admitted, accepted)
    assert hit == set(driver.SCHEMA_RESIDUAL)


# --- provider-free cells: sealed, replayed, and re-driven by the report -------------------


def _strict(payload: dict, wire: dict) -> str:
    """A reference wire action written the way a strict route returns it: every field, null where unused."""
    supplier = wire.get("supplier_id") or payload["suppliers"][0]["supplier_id"]
    return json.dumps({"action": wire["action"], "supplier_id": supplier, "message": wire.get("message") or "Proceed.",
                       "fields": None, "offer_id": None, "proposal": None, "award_lines": wire.get("award_lines"),
                       "reason": wire.get("reason") or "Proceed."})


def _scripted(path: Path, rule=None) -> tuple[SequenceResponseProvider, list[dict]]:
    payload = driver._payload(path)
    actions = reference.play(payload, rule)
    return SequenceResponseProvider(tuple(_strict(payload, a) for a in actions)), actions


@pytest.mark.parametrize("subject", sorted(driver.SUBJECTS))
def test_a_provider_free_gate_is_sealed_replayed_and_priced_by_the_report(tmp_path: Path, subject: str) -> None:
    runs = tmp_path / "runs" / "procurement_allocation"
    root = runs / driver.default_run_root(subject, "gate").name
    provider = SequenceResponseProvider((json.dumps({"action": "defer", "reason": "provider-free gate"}),))
    artifact = asyncio.run(driver.run(subject, "gate", root, resume=False, provider_factory=lambda: provider,
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {"candidate_id": s}))
    (row,) = artifact["rows"]
    assert artifact["halted"] is None and row["status"] == "completed" and row["receipt_replayed"] is True
    (request,) = provider.requests
    assert request.seed == 87001 and request.max_output_tokens == 4096 and request.timeout_seconds == 300.0
    assert request.temperature == (None if subject == "gpt6_luna" else 0.0)
    assert driver.verify(subject, "gate", root)["verified"] is True
    out = report.report(runs, "gate")
    (play,) = out["plays"][subject]
    world = json.loads((pack_module.pack_root(pack_module.PILOT_PACK_ID) / "pack.json").read_text())["worlds"][0]
    # Walking away at once gives up the best policy's whole value over walking away.
    assert play["decision_loss_usd"] == pytest.approx(world["best_policy_value_usd"] - (-600.0), abs=0.01)
    with pytest.raises(FileExistsError):
        asyncio.run(driver.run(subject, "gate", root, resume=False, provider_factory=lambda: provider,
                               credit_fn=_credit(20.0), preflight_fn=lambda s: {}))


@pytest.mark.parametrize("rule_name", [None, "one_step_value", "pay_premium"])
def test_the_report_re_drives_a_scripted_trace_to_its_recorded_margin(tmp_path: Path, rule_name) -> None:
    """A cell whose replies are a scripted policy's actions: the report's replay gives the margin the run sealed,
    and its decision loss is the one ``score_actions`` gives that policy's actions."""
    subject = "gpt6_luna"
    path = driver.case_paths("gate")[0]
    payload = driver._payload(path)
    rule = None if rule_name is None else reference.RULES[rule_name]
    provider, actions = _scripted(path, rule)
    runs = tmp_path / "runs" / "procurement_allocation"
    root = runs / driver.default_run_root(subject, "gate").name
    artifact = asyncio.run(driver.run(subject, "gate", root, resume=False, provider_factory=lambda: provider,
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    (row,) = artifact["rows"]
    assert row["status"] == "completed" and row["action_count"] == len(actions)
    manifest, payloads = report.load_pack(pack_module.PILOT_PACK_ID)
    scored = report.score_run(root, manifest, payloads)  # raises if the replayed margin differs from the row's
    (play,) = scored["plays"]
    assert play["margin_usd"] == pytest.approx(row["contribution_margin_usd"], abs=1e-6)
    expected = reference.score_actions(payload, actions)["decision_loss_usd"]
    assert play["decision_loss_usd"] == pytest.approx(expected, abs=1e-6)
    if rule_name is None:
        assert play["decision_loss_usd"] < 1e-6


def test_the_pilot_runs_seed_by_seed_and_the_report_reads_both_plays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every world is played under 87001 before any under 87002, and a world's value is the mean of its plays."""
    paths = driver.case_paths("pilot")[:2]
    monkeypatch.setattr(driver, "case_paths", lambda panel: paths)
    runs = tmp_path / "runs" / "procurement_allocation"
    root = runs / driver.default_run_root("gpt6_luna", "pilot").name
    defer = json.dumps({"action": "defer", "reason": "provider-free"})
    provider = SequenceResponseProvider((defer,) * 4)
    monkeypatch.setitem(driver.CONTROLS, "max_parallel_cells", 1)
    artifact = asyncio.run(driver.run("gpt6_luna", "pilot", root, resume=False, provider_factory=lambda: provider,
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    assert [r["inference_seed"] for r in artifact["rows"]] == [87001, 87001, 87002, 87002]
    assert [request.seed for request in provider.requests] == [87001, 87001, 87002, 87002]
    assert driver.verify("gpt6_luna", "pilot", root)["verified"] is True


def test_three_failed_cells_in_a_row_stop_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Refused:
        async def complete(self, request):
            raise driver.ProviderFailure("provider_rejected", "refused", retryable=False)

    monkeypatch.setitem(driver.CONTROLS, "max_parallel_cells", 1)
    root = tmp_path / "runs" / "procurement_allocation" / "pilot"
    artifact = asyncio.run(driver.run("gpt6_luna", "pilot", root, resume=False, provider_factory=Refused,
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    assert artifact["halted"] == "consecutive operational failures"
    assert [row["status"] for row in artifact["rows"]] == ["operational_failure"] * 3


def test_a_wave_that_could_pass_the_ceiling_is_not_launched_and_nothing_runs_under_the_credit_floor(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ceilings = copy.deepcopy(driver.CONTROLS["total_cost_ceiling_usd"])
    ceilings["gate"]["gpt6_luna"] = 0.29
    monkeypatch.setitem(driver.CONTROLS, "total_cost_ceiling_usd", ceilings)
    root = tmp_path / "runs" / "procurement_allocation" / "gate"
    artifact = asyncio.run(driver.run("gpt6_luna", "gate", root, resume=False, provider_factory=lambda: pytest.fail("called"),
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    assert artifact["rows"] == [] and artifact["halted"].startswith("total cost ceiling")
    other = tmp_path / "runs" / "procurement_allocation" / "floor"
    with pytest.raises(RuntimeError, match="under the 10.00 floor"):
        asyncio.run(driver.run("gemini38_flash", "gate", other, resume=False, credit_fn=_credit(9.99),
                               preflight_fn=lambda s: {}, provider_factory=lambda: pytest.fail("called")))
    assert not other.exists()


# --- the freeze ------------------------------------------------------------------------


def _record(worlds: int) -> dict:
    from aeread.shared_runner.run.contract import sealed
    return sealed({"schema_version": "test", "worlds": worlds, "inputs": {}})


def test_a_freeze_seals_the_run_and_refuses_any_later_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "freeze.json"
    pilot = tmp_path / "pilot.json"
    pilot.write_text(json.dumps({"variance": {"sizing": {"record": _record(20)}}}))
    freeze = driver.write_freeze(pilot, pack_module.PACK_ID, path)
    assert driver.load_freeze(path) == freeze
    assert freeze["pack"]["pack_id"] == "pay_or_test_v2" and len(freeze["pack"]["cases"]) == 24
    assert freeze["declared"]["minimum_meaningful_effect_usd"] == 10.0
    with pytest.raises(FileExistsError):
        driver.write_freeze(pilot, pack_module.PACK_ID, path)
    tampered = {**freeze, "inference_seeds": [1, 2]}
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="own digest"):
        driver.load_freeze(path)
    moved = {**freeze, "sources": {**freeze["sources"], "tools/cli_subjects/pay_or_test_v2_openrouter.py": "0" * 64}}
    moved["freeze_sha256"] = hashlib.sha256(driver.canonical_json_bytes(
        {k: v for k, v in moved.items() if k != "freeze_sha256"})).hexdigest()
    path.write_text(json.dumps(moved))
    with pytest.raises(ValueError, match="changed after the freeze"):
        driver.load_freeze(path)


def test_a_freeze_refuses_a_pack_smaller_than_the_sizing_or_past_the_cap(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs 30"):
        driver.build_freeze(pack_module.PACK_ID, _record(30), pilot_report_sha256="0" * 64)
    with pytest.raises(ValueError, match="past 96"):
        driver.build_freeze(pack_module.PACK_ID, _record(97), pilot_report_sha256="0" * 64)


# --- the declared analysis --------------------------------------------------------------


def test_holm_steps_down_and_stops_at_the_first_failure() -> None:
    out = report.holm({"a": 0.001, "b": 0.03, "c": 0.04})
    assert [out[k]["holm_alpha"] for k in "abc"] == pytest.approx([0.05 / 3, 0.025, 0.05])
    assert [out[k]["rejects"] for k in "abc"] == [True, False, False]
    assert out["b"]["holm_p"] == pytest.approx(0.06) and out["c"]["holm_p"] == pytest.approx(0.06)


def test_a_paired_t_matches_scipy() -> None:
    from scipy import stats
    d = [3.0, -1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    out = report.paired_t(d, [0.95])
    assert out["p"] == pytest.approx(stats.ttest_1samp(d, 0.0).pvalue)
    low, high = stats.t.interval(0.95, len(d) - 1, loc=sum(d) / len(d), scale=stats.sem(d))
    assert out["intervals_usd"]["0.9500"] == [round(low, 2), round(high, 2)]


def test_the_probe_is_a_first_sample_on_a_cheaper_member_of_a_kind_that_is_not_awarded() -> None:
    world = {"newcomers": [{"supplier_id": "a", "kind": "k", "sample_fee_usd": 20.0},
                           {"supplier_id": "b", "kind": "k", "sample_fee_usd": 200.0},
                           {"supplier_id": "c", "kind": "m", "sample_fee_usd": 25.0}]}
    sample = lambda sid: {"action": "request_sample", "supplier_id": sid}  # noqa: E731
    assert report.probe_of(world, [sample("a"), sample("b")], "b") is True
    assert report.probe_of(world, [sample("a")], "a") is False
    assert report.probe_of(world, [sample("b"), sample("a")], "a") is False
    assert report.probe_of(world, [sample("c")], None) is False
