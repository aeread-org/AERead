"""The scripted controls of the v14 price pack and the $0-ceiling rule (``price_controls``)."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from aeread_families.housing import price_controls as pc


#: Regenerated files are compared with their committed copies with every float to this relative tolerance and every
#: other value exactly (HL-T-12). The p-values come from scipy's t distribution: CI's Python 3.10 job installs scipy
#: 1.14 (scipy 1.16 dropped 3.10) and the committed files were written under 1.18, so p-values differ by at most
#: 1e-14 relative, while counts, labels, means and intervals agree exactly.
REL_TOL = 1e-9


def _close(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, float) or isinstance(right, float):
            return left == right or math.isclose(left, right, rel_tol=REL_TOL, abs_tol=0.0)
        return left == right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(_close(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_close(a, b) for a, b in zip(left, right))
    return left == right


def _regenerates(files: Mapping[str, bytes], out: Path) -> bool:
    """Each regenerated file equals its committed copy: JSON and JSONL value by value under ``_close``, the rest byte
    for byte."""
    for name, payload in files.items():
        committed = (out / name).read_bytes() if (out / name).is_file() else None
        if committed is None:
            return False
        if name.endswith(".jsonl"):
            ours, theirs = payload.decode().splitlines(), committed.decode().splitlines()
            if len(ours) != len(theirs) or not all(_close(json.loads(a), json.loads(b)) for a, b in zip(ours, theirs)):
                return False
        elif name.endswith(".json"):
            if not _close(json.loads(payload), json.loads(committed)):
                return False
        elif payload != committed:
            return False
    return True


@pytest.fixture(scope="module")
def report():
    return json.loads((pc.OUT / "reports/controls.json").read_text())


def test_the_controls_regenerate_to_the_committed_bytes() -> None:
    """Every float to ``REL_TOL``, everything else exactly (HL-T-12); ``--check`` still compares bytes."""
    assert _regenerates(pc._files(), pc.OUT)


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
