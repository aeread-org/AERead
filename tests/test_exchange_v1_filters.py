"""Tests for the D1b arena acceptance filters (provider-free admission gate)."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402
from aeread import exchange_v1_baselines as bl  # noqa: E402
from aeread import exchange_v1_filters as fl  # noqa: E402
from aeread import exchange_v1_validity as validity  # noqa: E402

CONFIG_DIR = ROOT / "configs" / "exchange_economy"
MANIFEST = CONFIG_DIR / "v1_manifest.json"


def _record(
    *,
    random_gain=1.0,
    greedy=5.0,
    heuristic=8.0,
    info=10.0,
    hidden=None,
    greedy_applied=1,
):
    hidden = max(0.0, info - heuristic) if hidden is None else hidden
    ordering = {
        "random_lt_greedy": validity.ValidityInequality(
            "random_mean_gain", "greedy_gain", random_gain, greedy, passed=random_gain < greedy - 1e-9),
        "greedy_lt_stronger_heuristic": validity.ValidityInequality(
            "greedy_gain", "stronger_heuristic_gain", greedy, heuristic, passed=greedy < heuristic - 1e-9),
        "stronger_heuristic_lt_information_constrained": validity.ValidityInequality(
            "stronger_heuristic_gain", "information_constrained_gain", heuristic, info, passed=heuristic < info - 1e-9),
    }
    return bl.BaselineRecord(
        config_name="synthetic", config_path="synthetic.json", sha256="0" * 64,
        rounds=5, seed=0, no_op_gain=0.0, random_mean_gain=random_gain,
        greedy_gain=greedy, stronger_heuristic_gain=heuristic,
        information_constrained_gain=info, hidden_discovery_gain=hidden,
        greedy_applied_rounds=greedy_applied, stronger_heuristic_applied_rounds=1,
        information_constrained_applied_rounds=1,
        greedy_social_optimum_welfare_gain=0.0, social_optimum_welfare_gain=0.0,
        ordering=ordering,
    )


def _config(**pressure_overrides):
    base = ex.load_experiment_config(CONFIG_DIR / "v1_main.json")
    if pressure_overrides:
        base = ex.replace(
            base,
            institution_pressure=ex.replace(base.institution_pressure, **pressure_overrides),
        )
    return base


def _decide(record, *, strict=False, thresholds=None, config=None):
    return fl.evaluate_arena(config or _config(), record, thresholds=thresholds, strict=strict)


# --- one test per contract rejection reason ---

def test_rejects_no_meaningful_surplus():
    decision = _decide(_record(random_gain=0.0, greedy=0.0, heuristic=0.0, info=0.0, greedy_applied=0))
    assert not decision.accepted
    assert fl.REASON_NO_SURPLUS in decision.rejection_reasons


def test_rejects_no_ir_safe_path():
    decision = _decide(_record(greedy=0.0, greedy_applied=0))
    assert fl.REASON_NO_IR_SAFE_PATH in decision.rejection_reasons
    lenient = fl.FilterThresholds(require_ir_safe_path=False)
    assert fl.REASON_NO_IR_SAFE_PATH not in _decide(
        _record(greedy=0.0, greedy_applied=0), thresholds=lenient).rejection_reasons


def test_rejects_excessive_random_capture():
    decision = _decide(_record(random_gain=6.0, greedy=7.0, heuristic=8.0, info=10.0))
    assert fl.REASON_RANDOM_CAPTURE in decision.rejection_reasons
    ok = _decide(_record(random_gain=4.9, greedy=7.0, heuristic=8.0, info=10.0))
    assert fl.REASON_RANDOM_CAPTURE not in ok.rejection_reasons


def test_rejects_excessive_greedy_capture():
    decision = _decide(_record(greedy=9.6, heuristic=9.8, info=10.0))
    assert fl.REASON_GREEDY_CAPTURE in decision.rejection_reasons


def test_rejects_insufficient_greedy_floor():
    decision = _decide(_record(greedy=0.1, heuristic=8.0, info=10.0))
    assert fl.REASON_GREEDY_FLOOR in decision.rejection_reasons


def test_rejects_excessive_hidden_knowledge_gap():
    decision = _decide(_record(greedy=1.0, heuristic=1.0, info=10.0, hidden=9.9))
    assert fl.REASON_HIDDEN_GAP in decision.rejection_reasons


def test_rejects_search_cost_domination():
    config = _config(search_cost_per_public_round=1.0)  # 1.0 * 10 agents * 15 rounds = 150 >> info 10
    decision = _decide(_record(), config=config)
    assert fl.REASON_SEARCH_COST in decision.rejection_reasons
    assert fl.REASON_SEARCH_COST not in _decide(_record()).rejection_reasons


# --- ordering modes ---

def test_clean_strict_ordering_accepted_in_both_modes():
    assert _decide(_record()).accepted
    assert _decide(_record(), strict=True).accepted


def test_tie_passes_discriminating_but_fails_strict_with_name():
    tied = _record(greedy=8.0, heuristic=8.0, info=10.0)
    relaxed = _decide(tied)
    assert relaxed.accepted
    assert relaxed.ties == ["greedy_lt_stronger_heuristic"]

    strict = _decide(tied, strict=True)
    assert not strict.accepted
    assert fl.REASON_ORDERING in strict.rejection_reasons
    assert "greedy_lt_stronger_heuristic" in strict.failed_inequalities


def test_inversion_rejects_in_both_modes():
    inverted = _record(greedy=9.0, heuristic=8.0, info=10.0)
    for strict in (False, True):
        decision = _decide(inverted, strict=strict)
        assert not decision.accepted
        assert decision.inversions == ["greedy_lt_stronger_heuristic"]


def test_discriminating_requires_info_headroom_above_greedy():
    saturated = _record(greedy=10.0, heuristic=10.0, info=10.0)
    decision = _decide(saturated)
    assert fl.REASON_ORDERING in decision.rejection_reasons


# --- capability tags + frozen-set integration ---

def test_capability_tags_for_v1_main_and_l1():
    decisions = {d.config_name: d for d in fl.evaluate_frozen_manifest(MANIFEST)}

    main_tags = decisions["v1_main"].capability_pressure_tags
    assert "hidden_discovery" in main_tags
    assert "public_solicitation" in main_tags
    assert "multiparty_composition" in main_tags
    assert "bilateral_visible" not in main_tags

    l1_tags = decisions["v1_ladder_l1_visible_bilateral_ir_trade"].capability_pressure_tags
    assert "bilateral_visible" in l1_tags
    assert "hidden_discovery" not in l1_tags


def test_frozen_manifest_decisions_match_design():
    decisions = fl.evaluate_frozen_manifest(MANIFEST)
    assert len(decisions) == 7
    by_name = {d.config_name: d for d in decisions}

    l1 = by_name["v1_ladder_l1_visible_bilateral_ir_trade"]
    assert not l1.accepted
    assert fl.REASON_GREEDY_CAPTURE in l1.rejection_reasons

    for name, decision in by_name.items():
        if name != "v1_ladder_l1_visible_bilateral_ir_trade":
            assert decision.accepted, f"{name}: {decision.rejection_reasons}"
        assert decision.llm_calls == 0
        assert decision.inversions == []


def test_strict_mode_rejects_all_frozen_rungs_naming_the_tier():
    decisions = fl.evaluate_frozen_manifest(MANIFEST, strict=True)
    for decision in decisions:
        assert not decision.accepted
        assert fl.REASON_ORDERING in decision.rejection_reasons
        assert decision.failed_inequalities


def test_paired_ablation_passthrough_on_visibility_gap_pair():
    result = fl.paired_ablation_check(
        CONFIG_DIR / "treatment_public_solicitation_visibility_gap_control.json",
        CONFIG_DIR / "treatment_public_solicitation_visibility_gap.json",
        conceptual_knob="public_solicitation",
    )
    assert result.passed


def test_markdown_report_has_one_row_per_decision():
    decisions = fl.evaluate_frozen_manifest(MANIFEST)
    md = fl.decisions_to_markdown(decisions)
    rows = [line for line in md.splitlines() if line.startswith("| v1_")]
    assert len(rows) == 7
    assert any("ACCEPT" in row for row in rows)
    assert any("reject" in row for row in rows)
