"""The agreement case's v2 confirmatory driver (``tools/cli_subjects/agreement_confirmatory_v2_cli.py``), with no model called.

What ``docs/families/datacenter/agreement_confirmatory_v2_plan.md`` asks of the driver, each checked here:

1. The arms are Section 3's: IF 320, HH 160 and CF 160 negotiations on the v2 pack, the pilot's 96 on the pilot pack
   (amendment 3), at the declared plays and parallelism, with ceilings at twice the estimate.
2. The hashed sources are v1's driver's plus the v2 pack module, the isolation module and this driver; v1's are unedited.
3. Through the kernel the scripted dry run on v2 worlds loses nothing with the oracle pair and the draft's midpoint with
   the draft pair, and every receipt replays offline.
4. A sealed failure receipt is counted as one, not as a failed replay (DC-T-22).
5. A confirmatory arm freezes only with an estimate measured on its own pilot; a probe that shows a violation refuses
   the freeze; the isolated Claude runner works in a fresh neutral directory and carries the CLI's refusal reason.
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
import agreement_confirmatory_cli as v1  # noqa: E402
import agreement_confirmatory_v2_cli as conf  # noqa: E402
import cli_isolation as iso  # noqa: E402
import codex_exec_client as codex  # noqa: E402
from aeread_families.datacenter_development import agreement_admitted_pack_v2 as pv2  # noqa: E402
from aeread_families.datacenter_development import agreement_pack as ap  # noqa: E402

RUNTIMES = {"claude_code": {"runtime_version": "test", "runtime_sha256": "0" * 64},
            codex.PROVIDER: {"runtime_version": "test", "runtime_sha256": "1" * 64}}
PROBES = {"probes": {}, "violations": {}}


def codes(pack: str, n: int) -> list[str]:
    return sorted(w["case_id"].rsplit(".", 1)[-1] for w in ap.load(pack)[0]["worlds"])[:n]


def test_the_arms_are_the_plans() -> None:
    n = {k: a.negotiations for k, a in conf.ARMS.items()}
    assert n == {"dry": 160, "pilot_IF": 48, "pilot_HH": 24, "pilot_CF": 24, "IF": 320, "HH": 160, "CF": 160}
    assert n["IF"] + n["HH"] + n["CF"] == 640 and n["pilot_IF"] + n["pilot_HH"] + n["pilot_CF"] == 96
    assert {k: (a.plays, a.parallel) for k, a in conf.ARMS.items() if k != "dry"} == {
        "pilot_IF": (2, 4), "pilot_HH": (1, 3), "pilot_CF": (1, 4), "IF": (2, 4), "HH": (1, 3), "CF": (1, 4)}
    assert {conf.ARMS[k].pack for k in ("IF", "HH", "CF", "dry")} == {pv2.ADMITTED.pack}
    assert {conf.ARMS[k].pack for k in ("pilot_IF", "pilot_HH", "pilot_CF")} == {pv2.PILOT.pack}
    for k in ("pilot_IF", "pilot_HH", "pilot_CF"):
        e = conf.v1_estimate(conf.ARMS[k])
        c = conf.controls_for(conf.ARMS[k], e)
        assert c["max_cost_usd_total"] == round(2 * e["list_usd"], 2) and c["max_wall_minutes"] == round(2 * e["wall_minutes"], 1)
        assert (c["reasoning_effort"], c["timeout_seconds"], c["max_action_attempts"], c["prompt_variant"]) == ("low", 300.0, 1, "v1")
    for pairing in conf.IF_PAIRINGS:
        assert base.PAIRINGS[pairing][1] == v1.SCRIPTED_PUBLIC
    for pairing in conf.CF_PAIRINGS:
        assert base.PAIRINGS[pairing][0] == v1.SCRIPTED_PUBLIC
    assert len({a.campaign_id for a in conf.ARMS.values()}) == len(conf.ARMS)
    assert not {a.campaign_id for a in conf.ARMS.values()} & {a.campaign_id for a in v1.ARMS.values()}


def test_the_hashed_sources_are_v1s_plus_the_v2_modules() -> None:
    assert conf.SOURCES[: len(v1.SOURCES)] == v1.SOURCES
    assert set(conf.SOURCES) - set(v1.SOURCES) == {"src/aeread_families/datacenter_development/agreement_admitted_pack_v2.py",
                                                   "tools/cli_subjects/cli_isolation.py", "tools/cli_subjects/agreement_confirmatory_v2_cli.py"}
    assert all((ROOT / rel).is_file() for rel in conf.SOURCES)


def test_a_plan_seals_the_isolation_and_resolves_v2_ids() -> None:
    arm = conf.ARMS["pilot_HH"]
    plan = conf.plan_for(arm, RUNTIMES, conf.v1_estimate(arm), PROBES, worlds=codes(pv2.PILOT.pack, 2))
    assert plan["isolation"]["declaration"] == dict(iso.DECLARATION) and plan["isolation"]["freeze_probe"] == PROBES
    assert plan["pack_json_sha256"] == conf.PACK_SHA256[pv2.PILOT.pack]
    assert all("v2" in run for run in (conf._setups(plan, RUNTIMES)[p].plan.run_spec.run_spec_id for p in arm.pairings))


@pytest.fixture(scope="module")
def dry(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("dry")
    worlds = sorted(ap.load(pv2.ADMITTED.pack)[0]["worlds"], key=lambda w: w["case_id"])
    chosen = ([w for w in worlds if w["draft_beats_no_deal"]][:2] + [w for w in worlds if not w["draft_beats_no_deal"] and w["available_surplus"] > 0][:2]
              + [w for w in worlds if w["available_surplus"] <= 0][:2])
    arm = conf.ARMS["dry"]
    plan = conf.plan_for(arm, {}, conf.v1_estimate(arm), PROBES, worlds=[w["case_id"].rsplit(".", 1)[-1] for w in chosen])
    (directory / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
    asyncio.run(v1.run_cells(directory, plan, conf._setups(plan, {}), {}))
    return directory


def test_through_the_kernel_the_dry_run_on_v2_worlds_passes_and_replays(dry: Path) -> None:
    assert v1.dry_run_failures(dry) == []
    result = conf.verify(dry)
    assert result["replayed"] == 12 and result["failed"] == [] and result["without_receipt"] == []


class Failing:
    runtime_metadata = {}

    async def complete(self, request):
        raise RuntimeError("service unavailable (test)")


def test_a_sealed_failure_receipt_is_counted_as_one_not_as_a_failed_replay(tmp_path: Path) -> None:
    arm = conf.ARMS["pilot_CF"]
    plan = conf.plan_for(arm, RUNTIMES, conf.v1_estimate(arm), PROBES, worlds=codes(pv2.PILOT.pack, 1))
    plan["plans"] = plan["plans"][:1]
    (tmp_path / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
    asyncio.run(v1.run_cells(tmp_path, plan, conf._setups(plan, RUNTIMES), {"claude_code": Failing(), codex.PROVIDER: Failing()}))
    result = conf.verify(tmp_path)
    assert result["failed"] == [] and len(result["sealed_failure_receipts"]) == 1 and result["replayed"] == 0


def test_a_confirmatory_arm_freezes_only_with_its_own_pilots_estimate(tmp_path: Path) -> None:
    good = {"arms": {"IF": {"measured_on": conf.ARMS["pilot_IF"].campaign_id, "list_usd": 16.0, "wall_minutes": 70.0}}}
    assert conf.estimate_check(conf.ARMS["IF"], good) == []
    assert conf.estimate_check(conf.ARMS["HH"], good)
    assert conf.estimate_check(conf.ARMS["IF"], {"arms": {"IF": {**good["arms"]["IF"], "measured_on": "elsewhere"}}})
    with pytest.raises(SystemExit, match="estimate record"):
        conf.freeze(tmp_path / "IF", "IF", None)
    assert not (tmp_path / "IF").exists()


def test_a_probe_violation_refuses_the_freeze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def clients(_providers):
        return {"claude_code": object()}

    async def bad_probe(_clients):
        return {"probes": {"claude_code": {}}, "violations": {"claude_code": ["claude_code: MCP servers ['github']"]}}

    monkeypatch.setattr(conf, "_git", lambda *a: "" if a[0] == "status" else "0" * 40)
    monkeypatch.setattr(conf, "discover", clients)
    monkeypatch.setattr(conf, "probe", bad_probe)
    with pytest.raises(SystemExit, match="isolation probe"):
        conf.freeze(tmp_path / "p", "pilot_IF", None)
    assert not (tmp_path / "p").exists()


def test_the_isolated_claude_runner_uses_a_neutral_directory_and_carries_the_refusal(tmp_path: Path) -> None:
    show = "import json, os; print(json.dumps({'cwd': os.getcwd()}))"
    code, out, _ = asyncio.run(conf._isolated_claude_runner((sys.executable, "-c", show), b""))
    cwd = json.loads(out)["cwd"]
    assert code == 0 and "aeread" not in cwd.lower() and str(iso.REAL_HOME) not in cwd and not Path(cwd).exists()
    refuse = "import json; print(json.dumps({'result': 'credit balance too low', 'api_error_status': 400})); raise SystemExit(1)"
    code, _, err = asyncio.run(conf._isolated_claude_runner((sys.executable, "-c", refuse), b""))
    assert code == 1 and b"credit balance too low" in err and b"400" in err
