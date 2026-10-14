"""The scripted controls of the v14 price pack and the $0-ceiling rule (``price_controls``)."""

from __future__ import annotations

import json

import pytest

from aeread_families.housing import price_controls as pc


@pytest.fixture(scope="module")
def report():
    return json.loads((pc.OUT / "reports/controls.json").read_text())


def test_the_controls_regenerate_to_the_committed_bytes() -> None:
    assert pc.check()


def test_controls_are_ordered_as_their_information_says(report) -> None:
    # No-op at $0; the weak control below it on the primary; the baseline and the reference above;
    # the ceiling above everything. Main pack, mean of the two arms.
    main = report["scopes"]["main"]
    level = {name: main["controls"][name]["primary_v1"]["mean"] for name in pc.CONTROLS}
    assert level["pass"] == 0.0
    assert level["sign_anything"] < level["pass"] < level["inspect_then_sign"] < level["inspect_lowball"] < main["ceiling"]["per_world"]
    assert main["controls"]["inspect_lowball"]["primary_v1"]["mean"] == 291.67 and main["ceiling"]["per_world"] == 370.11
    # Controls that never sign blind score the same under every measure.
    for name in ("pass", "inspect_then_sign", "inspect_lowball"):
        assert len({main["controls"][name][m]["mean"] for m in pc.MEASURES}) == 1


def test_every_model_beats_the_no_op_and_the_weak_control(report) -> None:
    for model, contrasts in report["beatability_main_pack_primary_v1"].items():
        for name in ("pass", "sign_anything"):
            assert contrasts[name]["lo"] > 0, (model, name)


def test_zero_ceiling_rule_is_applied_and_reported(report) -> None:
    assert report["zero_ceiling_rule"]["rule_id"] == "housing_price_zero_ceiling_v1"
    main, holdout = report["scopes"]["main"], report["scopes"]["holdout"]
    assert len(main["zero_ceiling_cells"]) == 7 and len(holdout["zero_ceiling_cells"]) == 3
    assert all(arm == "pooled" for _, arm in main["zero_ceiling_cells"] + holdout["zero_ceiling_cells"])
    assert report["scopes"]["main_favourite_is_sound"]["zero_ceiling_cells"] == []
    reference = main["controls"]["inspect_lowball"]
    assert reference["realized_share_of_ceiling"]["zero_ceiling_cells_excluded"] == 7
    assert reference["realized_share_of_ceiling"]["cells"] == 520 - 7
    # They stay in the net measure: every main world, both arms, is in the reference's mean.
    assert reference["net_realized"]["n"] == 260
    # The published ratio kept them; the rule's ratio differs, and both are reported per model.
    glm = main["models"]["GLM"]
    assert glm["realized_share_of_ceiling"]["share"] != glm["realized_share_of_ceiling_as_published"]


def test_the_best_informed_tenant_is_named_as_left_out(report) -> None:
    assert "best_informed" in report["not_included"]


def test_the_check_fails_when_a_control_moves(monkeypatch) -> None:
    # Counterexample: a weaker reference (one that never inspects) and the committed bytes no longer
    # regenerate; the reproduction against the published bundle stops it first.
    monkeypatch.setitem(pc.CONTROLS, "inspect_lowball", pc.CONTROLS["sign_anything"])
    with pytest.raises(ValueError, match="reference or ceiling differs"):
        pc.check()
