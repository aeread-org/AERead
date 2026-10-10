"""The agreement case's two briefs: v1 is what every published negotiation saw; the other states the client's walk-away cost."""
from __future__ import annotations

import pytest

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development.agreement_environment import BRIEF_FIELD, AgreementPlugin, _world


def _cases(pack: str) -> list[dict]:
    built, _ = ap.build(pack)
    return built


def test_the_committed_packs_are_what_the_generator_writes() -> None:
    for pack in ap.PACKS:
        _, committed = ap.load(pack)
        assert {c["case_id"]: c["content_sha256"] for c in _cases(pack)} == {c["case_id"]: c["content_sha256"] for c in committed.values()}


def test_v1_cases_carry_no_brief_field_and_the_new_pack_differs_only_by_it() -> None:
    old, new = _cases("agreement_dev_v1"), _cases("agreement_dev_walkaway_v1")
    assert len(old) == len(new) == 58
    assert all(BRIEF_FIELD not in c["payload"] for c in old)
    for a, b in zip(old, new):
        assert {k: v for k, v in b["payload"].items() if k != BRIEF_FIELD} == a["payload"]
        assert b["payload"][BRIEF_FIELD] == "walkaway_stated_v1"


def test_the_stated_walk_away_cost_is_the_one_the_grade_uses() -> None:
    plugin = AgreementPlugin()
    for case in _cases("agreement_dev_walkaway_v1"):
        payload = plugin.validate_payload(case["payload"])
        cw, it = _world(payload)
        state = ag.initial_state(cw)
        seen = plugin.observe(payload, state, "client", None)["brief"]
        plain = ag.brief(cw, "client")
        added = [line for line in seen.split("\n") if line not in plain.split("\n")]
        assert len(added) == 1 and f"Walking away therefore costs you ${cw.best_outside[1]:,.1f}k".replace(".0k", "k") in added[0].replace(".0k", "k")
        assert plugin.observe(payload, state, "integrator", None)["brief"] == ag.brief(cw, "integrator", it)


def test_an_unknown_or_redundant_brief_version_is_refused() -> None:
    payload = dict(_cases("agreement_dev_v1")[0]["payload"])
    for bad in ("v1", "anything"):
        with pytest.raises(ValueError):
            AgreementPlugin().validate_payload({**payload, BRIEF_FIELD: bad})
