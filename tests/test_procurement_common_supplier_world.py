"""Two buyers are only comparable if they faced the same market.

Four properties, each tested by trying to break it rather than by asserting it:
identical listings and private terms, identical rules and starting conditions,
independent episodes, and responses that still differ when the buyers act
differently. The last matters as much as the first three: a design that produced
identical transcripts would be holding the buyer's behaviour fixed, which is the
thing under measurement.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.procurement_allocation.common_supplier_world import (
    SHARED_WORLD_BLOCKS,
    SharedPopulationError,
    assert_shared_population,
    build_arm_cases,
    independence_report,
    paired_world_report,
    replay_script,
    supplier_population_sha256,
)

PANEL = (
    Path(__file__).resolve().parents[1]
    / "cases"
    / "procurement_allocation_v1"
    / "duediligence_v1"
    / "labeled"
)
ARMS = ("buyer_a", "buyer_b")


@pytest.fixture()
def base_case() -> dict:
    return json.loads(sorted(PANEL.glob("*.json"))[0].read_text(encoding="utf-8"))


@pytest.fixture()
def arms(base_case: dict) -> dict:
    return build_arm_cases(base_case, ARMS)


def _supplier_id(case: dict, index: int = 0) -> str:
    return str(case["payload"]["suppliers"][index]["supplier_id"])


# --- identical listings, private terms, rules and starting conditions --------


def test_arms_share_one_population(arms: dict) -> None:
    digest = assert_shared_population(arms)
    assert digest == supplier_population_sha256(arms["buyer_a"]["payload"])


def test_every_supplier_field_is_identical_public_and_private(arms: dict) -> None:
    """Not just the listing: private terms are the ones a buyer cannot see."""
    a = arms["buyer_a"]["payload"]["suppliers"]
    b = arms["buyer_b"]["payload"]["suppliers"]
    assert a == b
    assert all("private_terms" in supplier for supplier in a)


def test_arms_differ_only_in_identity(arms: dict) -> None:
    a, b = arms["buyer_a"], arms["buyer_b"]
    assert a["case_id"] != b["case_id"]
    assert a["split"] != b["split"]
    assert a["content_sha256"] != b["content_sha256"]
    assert {k: v for k, v in a.items() if k not in {"case_id", "split", "content_sha256"}} == {
        k: v for k, v in b.items() if k not in {"case_id", "split", "content_sha256"}
    }


def test_each_arm_is_a_valid_self_describing_case(arms: dict) -> None:
    for case in arms.values():
        assert case_content_sha256(CaseManifest.from_dict(case)) == case["content_sha256"]


@pytest.mark.parametrize("block", SHARED_WORLD_BLOCKS)
def test_changing_any_shared_block_breaks_the_pairing(arms: dict, block: str) -> None:
    """Each block is load-bearing, so each one is mutated in turn."""
    broken = copy.deepcopy(arms)
    payload = broken["buyer_b"]["payload"]
    if block == "suppliers":
        payload["suppliers"][0]["private_terms"]["base_unit_price_usd"] += 0.01
    elif block == "objective":
        payload["objective"]["deadline_days"] += 1
    elif block == "interaction":
        payload["interaction"]["max_actions"] += 1
    else:
        payload["policy"]["award_requires"] = list(payload["policy"]["award_requires"])[:1]
    with pytest.raises(SharedPopulationError) as raised:
        assert_shared_population(broken)
    assert block in str(raised.value)


#: The invariants named in the design decision, mapped to this schema. Each is
#: mutated in turn, so the list is enforced rather than merely documented.
NAMED_INVARIANTS = {
    "capacity": ("capacity", 5),
    "quality": ("quality.verified_yield_rate", -0.05),
    "delivery": ("lead_time_days", 3),
    "reservation_price": ("negotiation.floor_unit_price_usd", 0.05),
    "negotiation_rules": ("negotiation.minimum_moq", 5),
    "payment_terms": ("payment_terms_days", 15),
    "order_step": ("order_step", 5),
}


@pytest.mark.parametrize("name", sorted(NAMED_INVARIANTS))
def test_each_named_supplier_invariant_is_enforced(arms: dict, name: str) -> None:
    """Capacity, quality, delivery, reservation price and negotiation rules.

    A comparison that let any of these move between conditions would be
    comparing buyers against different markets while reporting one number.
    """
    path, delta = NAMED_INVARIANTS[name]
    broken = copy.deepcopy(arms)
    terms = broken["buyer_b"]["payload"]["suppliers"][0]["private_terms"]
    *parents, leaf = path.split(".")
    for parent in parents:
        terms = terms[parent]
    assert leaf in terms, f"{name} is not stored at {path}"
    terms[leaf] = round(terms[leaf] + delta, 6)
    with pytest.raises(SharedPopulationError):
        assert_shared_population(broken)


def test_a_hidden_private_term_change_is_caught(arms: dict) -> None:
    """The failure this exists to prevent: same listings, different truth."""
    broken = copy.deepcopy(arms)
    quality = broken["buyer_b"]["payload"]["suppliers"][0]["private_terms"]["quality"]
    quality["verified_yield_rate"] = round(quality["verified_yield_rate"] - 0.05, 6)
    with pytest.raises(SharedPopulationError):
        assert_shared_population(broken)


def test_a_single_arm_is_not_a_comparison(base_case: dict) -> None:
    with pytest.raises(SharedPopulationError):
        assert_shared_population({"only": base_case})
    with pytest.raises(ValueError):
        build_arm_cases(base_case, ("solo",))
    with pytest.raises(ValueError):
        build_arm_cases(base_case, ("same", "same"))


# --- independent episodes ----------------------------------------------------


def _script(case: dict, index: int) -> list[dict]:
    supplier = _supplier_id(case, index)
    return [
        {"action": "request_quote", "supplier_id": supplier, "message": "quote"},
        {"action": "request_sample", "supplier_id": supplier, "message": "sample"},
    ]


def test_one_arms_episode_does_not_reach_another(arms: dict) -> None:
    """Played alone, in order, and reversed, every arm must land identically."""
    payload = arms["buyer_a"]["payload"]
    scripts = {"buyer_a": _script(arms["buyer_a"], 0), "buyer_b": _script(arms["buyer_b"], 1)}
    report = independence_report(payload, scripts)
    assert report["independent"], report["contaminated_arms"]


def test_replay_does_not_mutate_the_payload_it_was_given(arms: dict) -> None:
    """A plugin that wrote back into the case would contaminate every later arm."""
    payload = arms["buyer_a"]["payload"]
    before = json.dumps(payload, sort_keys=True)
    replay_script(payload, _script(arms["buyer_a"], 0))
    replay_script(payload, _script(arms["buyer_b"], 1))
    assert json.dumps(payload, sort_keys=True) == before


def test_the_same_script_twice_gives_the_same_episode(arms: dict) -> None:
    payload = arms["buyer_a"]["payload"]
    script = _script(arms["buyer_a"], 0)
    assert replay_script(payload, script) == replay_script(payload, script)


# --- same suppliers, not the same transcript ---------------------------------


def test_different_actions_still_produce_different_replies(arms: dict) -> None:
    """Sameness is in the rules and the starting state, never in the transcript.

    If two buyers acting differently saw the same conversation, the environment
    would be ignoring what they did, and the comparison would measure nothing.
    """
    payload = arms["buyer_a"]["payload"]
    first = replay_script(payload, _script(arms["buyer_a"], 0))
    second = replay_script(payload, _script(arms["buyer_b"], 1))
    assert first["conversation"] != second["conversation"]
    assert set(first["offers"]) != set(second["offers"])


def test_a_longer_script_sees_strictly_more(arms: dict) -> None:
    payload = arms["buyer_a"]["payload"]
    short = replay_script(payload, _script(arms["buyer_a"], 0)[:1])
    long = replay_script(payload, _script(arms["buyer_a"], 0))
    assert not short["quality_evidence"]
    assert long["quality_evidence"]


# --- the published report ----------------------------------------------------


def test_report_carries_the_digest_and_the_independence_check(arms: dict) -> None:
    scripts = {"buyer_a": _script(arms["buyer_a"], 0), "buyer_b": _script(arms["buyer_b"], 1)}
    report = paired_world_report(arms, scripts)
    assert report["supplier_population_sha256"] == assert_shared_population(arms)
    assert report["arms"] == sorted(ARMS)
    assert report["independence"]["independent"] is True
    assert report["supplier_count"] == len(arms["buyer_a"]["payload"]["suppliers"])


def test_report_refuses_to_describe_an_unshared_comparison(arms: dict) -> None:
    broken = copy.deepcopy(arms)
    broken["buyer_b"]["payload"]["objective"]["target_kits"] += 1
    with pytest.raises(SharedPopulationError):
        paired_world_report(broken)


# --- the independence check must be able to say no ---------------------------
#
# J-09: hardcoding the check's result to "clean" passed every test above, so the
# guard was unfalsifiable. Against the real environment it never fires, which is
# exactly the condition under which a check should be distrusted.


def test_the_independence_check_detects_a_leaky_replay(arms: dict) -> None:
    """A replay that remembers previous episodes must be reported, not excused."""
    seen: list[str] = []

    def leaky(payload, script):
        seen.append(str(script))
        # Deliberately order-dependent: the result changes with call history,
        # which is precisely what contamination looks like.
        return {"calls_before_this_one": len(seen)}

    scripts = {"buyer_a": _script(arms["buyer_a"], 0), "buyer_b": _script(arms["buyer_b"], 1)}
    report = independence_report(arms["buyer_a"]["payload"], scripts, replay=leaky)
    assert report["independent"] is False
    assert report["contaminated_arms"] == sorted(scripts)


def test_the_independence_check_passes_a_genuinely_pure_replay(arms: dict) -> None:
    """The other half: it must not cry contamination over a clean replay."""

    def pure(payload, script):
        return {"actions": [dict(action) for action in script]}

    scripts = {"buyer_a": _script(arms["buyer_a"], 0), "buyer_b": _script(arms["buyer_b"], 1)}
    report = independence_report(arms["buyer_a"]["payload"], scripts, replay=pure)
    assert report["independent"] is True
    assert report["contaminated_arms"] == []
