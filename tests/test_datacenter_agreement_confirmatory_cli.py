"""The agreement confirmatory's driver (``tools/cli_subjects/agreement_confirmatory_cli.py``), with no model called.

What the plan (``docs/families/datacenter/agreement_confirmatory_plan.md``, "Before the confirmatory runs", step 1) asks of
the driver, each checked here:

1. The arms are the plan's: 96 pilot negotiations, 120 in H, 240 in F and 720 in A, at the plan's parallelism, with
   the development controls, and each campaign's list-price and wall-time ceilings frozen at twice the plan's estimate.
2. The firm population is the publicly drawn style (``agreement_admitted_pack.public_negotiator_move``), played through
   the base driver's scripted seat; the base driver and its pack list are not edited.
3. The hashed sources are the base driver's, plus the admitted pack module and the driver itself.
4. A campaign stops starting negotiations after five consecutive operational failures, types the rest
   ``not_attempted_halt``, and an operational failure between successes does not count towards it.
5. Through the kernel scheduler the oracle pair loses 0 and the draft pair loses its midpoint on admitted worlds; the
   dry-run check and the offline replay each catch a record or evidence that was changed afterwards.
6. A sizing record that needs more deal worlds than the pack gives refuses the freeze.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "cli_subjects"))

import agreement_cli as base  # noqa: E402
import agreement_confirmatory_cli as conf  # noqa: E402
import codex_exec_client as codex  # noqa: E402
from aeread_families.datacenter_development import agreement_admitted_pack as aap  # noqa: E402
from aeread_families.datacenter_development import agreement_pack as ap  # noqa: E402

RUNTIMES = {"claude_code": {"runtime_version": "test", "runtime_sha256": "0" * 64},
            codex.PROVIDER: {"runtime_version": "test", "runtime_sha256": "1" * 64}}


def codes(pack: str, n: int) -> list[str]:
    return sorted(w["case_id"].rsplit(".", 1)[-1] for w in ap.load(pack)[0]["worlds"])[:n]


def test_the_arms_are_the_plans_negotiations_parallelism_and_ceilings() -> None:
    arms = {k: a for k, a in conf.ARMS.items() if k != "dry"}
    assert {k: a.negotiations for k, a in arms.items()} == {"pilot": 96, "H": 120, "F": 240, "A": 720}
    assert sum(a.negotiations for a in arms.values()) == 1176
    assert {k: a.parallel for k, a in arms.items()} == {"pilot": 4, "H": 3, "F": 4, "A": 6}
    controls = {k: conf.controls_for(a) for k, a in arms.items()}
    assert {k: c["max_cost_usd_total"] for k, c in controls.items()} == {"pilot": 8.8, "H": 25.8, "F": 22.0, "A": 69.2}
    assert {k: c["max_wall_minutes"] for k, c in controls.items()} == {"pilot": 36.0, "H": 112.0, "F": 88.0, "A": 204.0}
    for c in controls.values():
        assert (c["reasoning_effort"], c["timeout_seconds"], c["max_action_attempts"], c["prompt_variant"]) == ("low", 300.0, 1, "v1")
        assert c["halt_after_consecutive_operational_failures"] == 5
    assert conf.ARMS["pilot"].pack == aap.PILOT.pack and conf.ARMS["pilot"].plays == 2
    assert {conf.ARMS[k].pack for k in ("H", "F", "A")} == {aap.ADMITTED.pack}


def test_the_firm_population_is_the_publicly_drawn_style_through_the_base_drivers_scripted_seat() -> None:
    assert base.scripted_policy("negotiator_drawn_public_v1") is aap.public_negotiator_move
    assert base.scripted_policy("negotiator_drawn") is not aap.public_negotiator_move  # the development style is untouched
    for pairing in conf.F_PAIRINGS:
        sides = base.PAIRINGS[pairing]
        assert conf.SCRIPTED_PUBLIC in sides and set(sides) - {conf.SCRIPTED_PUBLIC} <= set(conf.MODELS)
    assert len(conf.F_PAIRINGS) == 4 and len(conf.A_PAIRINGS) == 12 and len(set(conf.A_PAIRINGS)) == 12
    # the scripted seat answers with the public style's move
    _, cases = ap.load(aap.ADMITTED.pack)
    payload = next(iter(cases.values()))["payload"]
    client = base.ScriptedClient(payload, {"integrator": f"negotiator_{conf.PUBLIC}"})
    assert client.policies["integrator"] is aap.public_negotiator_move
    assert "drawn_public_v1" not in base.SOURCES[0] and tuple(ap.PACKS) == ("agreement_dev_v1", "agreement_dev_walkaway_v1", "agreement_confirm_v1",
                                                                          "agreement_confirm_swap_client_v1", "agreement_confirm_swap_integrator_v1")


def test_the_hashed_sources_are_the_base_drivers_plus_the_admitted_pack_module_and_the_driver() -> None:
    assert conf.SOURCES[: len(base.SOURCES)] == base.SOURCES
    assert set(conf.SOURCES) - set(base.SOURCES) == {"src/aeread_families/datacenter_development/agreement_admitted_pack.py",
                                                     "tools/cli_subjects/agreement_confirmatory_cli.py"}
    assert all((ROOT / rel).is_file() for rel in conf.SOURCES)


def test_the_halt_counts_consecutive_operational_failures_only() -> None:
    halt = conf.Halt(5)
    for i in range(4):
        halt.record({"cell_key": f"a{i}", "status": "invalid_measurement", "error": "x"})
    halt.record({"cell_key": "ok", "status": "ok"})
    halt.record({"cell_key": "skip", "status": "not_attempted_budget"})
    assert not halt.fired and halt.streak == 0
    for i in range(5):
        halt.record({"cell_key": f"b{i}", "status": "invalid_measurement", "error": "x"})
    assert halt.fired and halt.fired_after == "b4"


class Failing:
    """A provider that is down: every call raises."""

    runtime_metadata = {}

    async def complete(self, request):
        raise RuntimeError("service unavailable (test)")


def test_a_campaign_stops_after_five_consecutive_operational_failures_and_types_the_rest(tmp_path: Path) -> None:
    plan = conf.plan_for(conf.ARMS["H"], RUNTIMES, worlds=codes(aap.ADMITTED.pack, 8))
    plan["plans"] = plan["plans"][:1]
    plan["controls"]["max_parallel_cells"] = 1
    setups = conf._setups(plan, RUNTIMES)
    summary = asyncio.run(conf.run_cells(tmp_path, plan, setups, {"claude_code": Failing(), codex.PROVIDER: Failing()}))
    records = [json.loads(p.read_text()) for p in sorted((tmp_path / "cells").glob("*.json"))]
    failed = [r for r in records if r.get("error")]
    halted = [r for r in records if r["status"] == "not_attempted_halt"]
    assert len(records) == 8 and len(failed) == 5 and len(halted) == 3
    assert all("service unavailable" in r["error"] for r in failed) and summary["halted_after"] in {r["cell_key"] for r in failed}
    # a relaunch keeps every record as it stands: nothing is rerun
    again = asyncio.run(conf.run_cells(tmp_path, plan, setups, {}))
    assert again["status"] == summary["status"]


@pytest.fixture(scope="module")
def dry(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("dry")
    worlds = sorted(ap.load(aap.ADMITTED.pack)[0]["worlds"], key=lambda w: w["case_id"])
    # two worlds where the draft beats walking away, two where it does not, two with no deal worth signing
    chosen = ([w for w in worlds if w["draft_beats_no_deal"]][:2] + [w for w in worlds if not w["draft_beats_no_deal"] and w["available_surplus"] > 0][:2]
              + [w for w in worlds if w["available_surplus"] <= 0][:2])
    plan = conf.plan_for(conf.ARMS["dry"], {}, worlds=[w["case_id"].rsplit(".", 1)[-1] for w in chosen])
    (directory / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
    asyncio.run(conf.run_cells(directory, plan, conf._setups(plan, {}), {}))
    return directory


def test_through_the_kernel_the_oracle_pair_loses_nothing_and_the_draft_pair_its_midpoint(dry: Path) -> None:
    assert conf.dry_run_failures(dry) == []
    result = conf.verify(dry)
    assert result["replayed"] == 12 and result["failed"] == [] and result["without_receipt"] == []


def test_the_dry_run_check_and_the_offline_replay_catch_a_changed_record_or_evidence(dry: Path, tmp_path: Path) -> None:
    import shutil
    copy = tmp_path / "copy"
    shutil.copytree(dry, copy)
    path = next(p for p in sorted((copy / "cells").glob("draft_*.json")) if json.loads(p.read_text())["termination"] == "signed")
    record = json.loads(path.read_text())
    record["grade"]["joint_value_lost"] += 1.0
    record["signed"]["price"] += 1.0
    path.write_text(json.dumps(record))
    failures = conf.dry_run_failures(copy)
    assert any("predicted" in f for f in failures) and any("midpoint" in f for f in failures)
    events = next((copy / "evidence" / record["cell_key"]).rglob("events.jsonl"))
    text = events.read_text()
    assert '"occurred_at":"2026' in text
    events.write_text(text.replace('"occurred_at":"2026', '"occurred_at":"2025', 1))
    assert [f["cell_key"] for f in conf.verify(copy)["failed"]] == [record["cell_key"]]


def test_a_sizing_record_needing_more_deal_worlds_than_the_pack_gives_refuses_the_freeze(tmp_path: Path) -> None:
    good = {"pilot_pack": aap.PILOT.pack, "deal_worlds_needed": 30}
    assert conf.sizing_check(good) == []
    assert conf.sizing_check({**good, "deal_worlds_needed": 43})
    assert conf.sizing_check({**good, "pilot_pack": "agreement_dev_v1"})
    with pytest.raises(SystemExit):
        conf.freeze(tmp_path / "H", "H", None)
    record = tmp_path / "sizing.json"
    record.write_text(json.dumps({**good, "deal_worlds_needed": 60}))
    with pytest.raises(SystemExit, match="amendment"):
        conf.freeze(tmp_path / "H2", "H", record)
    assert not (tmp_path / "H2").exists()
