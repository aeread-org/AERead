"""Hand-derived formula parity for the termsbench counterpart kernel.

Every assertion here is independently re-derived from the cited paper
equation (docs/termsbench_adapter_spec.md sections 3-4), never validated
against an upstream implementation -- none exists (dead repository link).
"""
from __future__ import annotations

import math

import pytest

from aeread_families.termsbench import kernel as k

# ---------------------------------------------------------------------------
# Golden 1 (spec section 4): p_min=0, p_max=200, r_A=150 (buyer), r_B=100
# (seller), Candid family, eta_B=neutral, kappa_B=0.5, K=10, round k=1.
# ---------------------------------------------------------------------------


def test_golden1_normalized_favorability_and_deadline_clock() -> None:
    delta_bar = k.normalized_favorability(110.0, r_b=100.0, counterpart_role="seller", price_range=200.0)
    assert delta_bar == pytest.approx(0.05, abs=1e-9)

    d_tilde, d_tilde_bar = k.deadline_clock(1, 10)
    assert d_tilde == pytest.approx(math.sqrt(0.1), abs=1e-9)
    assert d_tilde_bar == pytest.approx(1 - math.sqrt(0.1), abs=1e-9)
    assert d_tilde == pytest.approx(0.3162, abs=1e-4)
    assert d_tilde_bar == pytest.approx(0.6838, abs=1e-4)


def test_golden1_acceptance_probability_matches_hand_derivation() -> None:
    preset = k.ECONOMIC_PRESETS["type_instrumental"]
    delta_bar = 0.05
    _d_tilde, d_tilde_bar = k.deadline_clock(1, 10)
    a1 = k.acceptance_probability(
        delta_bar=delta_bar,
        kappa_b=0.5,
        d_tilde_bar=d_tilde_bar,
        rho=preset["rho"]["neutral"],
        xi=preset["xi"]["neutral"],
        concede_speed=0.0,
        rigidity=0.0,
    )
    # g_theta = 6(0.05) + 1(0.5) - 2(0.6838) = 0.3 + 0.5 - 1.3675 = -0.5675
    # (independent re-derivation, using the same precise d_tilde_bar as the
    # scorer under test so this checks the *formula*, not rounding noise)
    g_theta = 6.0 * delta_bar + 1.0 * 0.5 - 2.0 * d_tilde_bar
    assert g_theta == pytest.approx(-0.5675, abs=1e-3)
    assert a1 == pytest.approx(1.0 / (1.0 + math.exp(-g_theta)), abs=1e-12)
    assert a1 == pytest.approx(0.3618, abs=1e-3)


def test_golden1_resolves_to_accept_at_p_110() -> None:
    decision = k.resolve_counterpart_turn(
        round_k=1,
        horizon=10,
        family="candid",
        agent_role="buyer",
        counterpart_role="seller",
        r_b=100.0,
        kappa_b=0.5,
        eta_b="neutral",
        p_min=0.0,
        p_max=200.0,
        opening_harshness=0.5,
        agent_offers=(110.0,),
        counterpart_offers=(),
        draws={"u_accept": 0.10, "sentiment_noise": 0.0},
    )
    assert decision.resolved == "accept"
    assert decision.price == 110.0
    # Candid's cue channel is accurate: sentiment latent score = mu(neutral)
    # + 0 = 0, which is within [-tau_s, tau_s] -> neutral.
    assert decision.sentiment_cue == "neutral"
    assert decision.strategic_cue == "Concede"  # terminal mapping for Accept


def test_golden1_a1_below_threshold_does_not_accept() -> None:
    decision = k.resolve_counterpart_turn(
        round_k=1,
        horizon=10,
        family="candid",
        agent_role="buyer",
        counterpart_role="seller",
        r_b=100.0,
        kappa_b=0.5,
        eta_b="neutral",
        p_min=0.0,
        p_max=200.0,
        opening_harshness=0.5,
        agent_offers=(110.0,),
        counterpart_offers=(),
        draws={
            "u_accept": 0.9999,
            "u_walkaway": 0.9999,
            "sentiment_noise": 0.0,
            "opening_noise": 0.0,
            "posture_u": 0.5,
        },
    )
    assert decision.resolved != "accept"


# ---------------------------------------------------------------------------
# Table 4 economic presets (verbatim transcription check).
# ---------------------------------------------------------------------------


def test_table4_type_instrumental_preset_values() -> None:
    preset = k.ECONOMIC_PRESETS["type_instrumental"]
    assert preset["rho"] == {"conciliatory": 0.0, "neutral": -0.25, "aggressive": -0.75}
    assert preset["xi"] == {"conciliatory": 0.40, "neutral": 0.0, "aggressive": -0.50}
    assert preset["lambda2"] == {"conciliatory": 0.30, "neutral": 0.50, "aggressive": 1.00}


def test_table4_high_reactivity_preset_values() -> None:
    preset = k.ECONOMIC_PRESETS["high_reactivity"]
    assert preset["rho"] == {"conciliatory": 0.0, "neutral": -0.75, "aggressive": -1.50}
    assert preset["xi"] == {"conciliatory": 0.40, "neutral": 0.0, "aggressive": -0.75}
    assert preset["lambda2"] == {"conciliatory": 0.45, "neutral": 0.90, "aggressive": 1.80}


def test_table3_family_to_preset_and_cue_channel_mapping() -> None:
    assert k.FAMILY_PRESETS["candid"] == {
        "economic_preset": "type_instrumental",
        "cue_channel": "accurate",
        "price_noise_tier": "low",
    }
    assert k.FAMILY_PRESETS["taciturn"] == {
        "economic_preset": "type_instrumental",
        "cue_channel": "uninformative",
        "price_noise_tier": "low",
    }
    assert k.FAMILY_PRESETS["expressive"] == {
        "economic_preset": "high_reactivity",
        "cue_channel": "accurate",
        "price_noise_tier": "moderate",
    }


# ---------------------------------------------------------------------------
# Appendix C.3: agent history-feature boundary conditions.
# ---------------------------------------------------------------------------


def test_history_features_are_zero_with_fewer_than_two_agent_offers() -> None:
    empty = k.agent_history_features((), agent_role="buyer", price_range=200.0)
    assert empty == k.HistoryFeatures(0.0, 0.0, 0.0)
    single = k.agent_history_features((110.0,), agent_role="buyer", price_range=200.0)
    assert single == k.HistoryFeatures(0.0, 0.0, 0.0)


def test_history_features_concede_speed_sign_is_role_invariant() -> None:
    # Buyer raising its offer is concessionary (+); seller lowering its own
    # offer by the same magnitude is equally concessionary (+).
    buyer = k.agent_history_features((100.0, 110.0), agent_role="buyer", price_range=200.0)
    seller = k.agent_history_features((110.0, 100.0), agent_role="seller", price_range=200.0)
    assert buyer.concede_speed == pytest.approx(seller.concede_speed)
    assert buyer.concede_speed > 0.0


def test_rigidity_flags_a_small_recent_concession() -> None:
    # A buyer moving from 100 to 100.5 out of R=200 concedes 0.25% < tau_rigid.
    features = k.agent_history_features((90.0, 100.0, 100.5), agent_role="buyer", price_range=200.0)
    assert features.rigidity == 1.0

    # A buyer moving from 100 to 130 out of R=200 concedes 15% >= tau_rigid.
    features_large = k.agent_history_features((70.0, 100.0, 130.0), agent_role="buyer", price_range=200.0)
    assert features_large.rigidity == 0.0


# ---------------------------------------------------------------------------
# Appendix C.2.2: walk-away hazard hard gates.
# ---------------------------------------------------------------------------


def test_walkaway_hazard_is_zero_when_offer_is_individually_rational() -> None:
    assert k.walkaway_hazard(round_k=8, horizon=10, delta_bar=0.1) == 0.0


def test_walkaway_hazard_is_zero_before_the_grace_period() -> None:
    # k_walk = ceil(10/2) = 5; round 4 is before the grace period even though
    # delta_bar < 0.
    assert k.walkaway_hazard(round_k=4, horizon=10, delta_bar=-0.2) == 0.0


def test_walkaway_hazard_is_positive_after_grace_period_when_infeasible() -> None:
    hazard = k.walkaway_hazard(round_k=6, horizon=10, delta_bar=-0.2)
    assert 0.0 < hazard < 1.0


def test_k_walk_matches_ceil_half_horizon() -> None:
    assert k.k_walk(10) == 5
    assert k.k_walk(9) == 5
    assert k.k_walk(11) == 6


# ---------------------------------------------------------------------------
# Appendix C.2.3: the terminal round still draws (a_k, omega_k) together --
# a positive walk-away hazard must still be sampled at round_k=horizon, not
# short-circuited straight to Timeout (Codex review finding 1).
# ---------------------------------------------------------------------------


def test_resolve_counterpart_turn_still_samples_walkaway_at_the_terminal_round() -> None:
    """horizon=10, round_k=10, delta_bar=-0.2 (agent_price=60 vs r_b=100,
    price_range=200, seller counterpart): acceptance_probability's delta_bar
    hard-gate makes a_k=0 regardless of u_accept, so u_accept=0.5 never
    accepts. walkaway_hazard(round_k=10, horizon=10, delta_bar=-0.2) is
    strictly positive (round 10 is past k_walk=5's grace period and the
    offer is not individually rational for the counterpart) -- with
    u_walkaway=0.0, sampling that hazard must resolve to Reject
    (walk-away), not Timeout: the round-limit disagreement case is only for
    the *remaining* mass once accept/walk-away have both been drawn and
    neither fires, never a substitute for skipping the walk-away draw.
    """
    hazard = k.walkaway_hazard(round_k=10, horizon=10, delta_bar=-0.2)
    assert hazard > 0.0  # sanity: this scenario's hazard is genuinely positive

    decision = k.resolve_counterpart_turn(
        round_k=10,
        horizon=10,
        family="candid",
        agent_role="buyer",
        counterpart_role="seller",
        r_b=100.0,
        kappa_b=0.5,
        eta_b="neutral",
        p_min=0.0,
        p_max=200.0,
        opening_harshness=0.5,
        agent_offers=(60.0,),
        counterpart_offers=(),
        draws={"u_accept": 0.5, "u_walkaway": 0.0, "sentiment_noise": 0.0},
    )
    assert decision.resolved == "reject"


def test_resolve_counterpart_turn_times_out_at_the_terminal_round_only_when_the_hazard_does_not_fire() -> None:
    """Same terminal-round scenario, but ``u_walkaway`` is high enough that
    the (still-sampled) hazard does not fire -- only *then* does the
    round-limit disagreement (Timeout) case apply."""
    hazard = k.walkaway_hazard(round_k=10, horizon=10, delta_bar=-0.2)
    assert hazard < 1.0  # sanity: a u_walkaway just under 1.0 must not fire

    decision = k.resolve_counterpart_turn(
        round_k=10,
        horizon=10,
        family="candid",
        agent_role="buyer",
        counterpart_role="seller",
        r_b=100.0,
        kappa_b=0.5,
        eta_b="neutral",
        p_min=0.0,
        p_max=200.0,
        opening_harshness=0.5,
        agent_offers=(60.0,),
        counterpart_offers=(),
        draws={"u_accept": 0.5, "u_walkaway": 0.9999999, "sentiment_noise": 0.0},
    )
    assert decision.resolved == "timeout"


# ---------------------------------------------------------------------------
# Appendix C.5.3: family-specific cue collapse for Taciturn.
# ---------------------------------------------------------------------------


def test_taciturn_cues_are_always_collapsed_to_neutral_hold() -> None:
    for resolved_action, price, prior in (
        ("offer", 120.0, 100.0),
        ("accept", 110.0, None),
        ("reject", None, None),
    ):
        cues = k.generate_cues(
            family="taciturn",
            resolved_action=resolved_action,
            eta_b="aggressive",
            round_k=5,
            horizon=10,
            counterpart_price=price,
            prior_counterpart_price=prior,
            r_b=100.0,
            sentiment_noise=None,
            posture_u=None,
        )
        assert cues.sentiment_cue == "neutral"
        assert cues.strategic_cue == "Hold"


def test_candid_terminal_cue_mapping_is_deterministic() -> None:
    accept_cues = k.generate_cues(
        family="candid", resolved_action="accept", eta_b="neutral", round_k=1, horizon=10,
        counterpart_price=110.0, prior_counterpart_price=None, r_b=100.0,
        sentiment_noise=0.0, posture_u=None,
    )
    assert accept_cues.strategic_cue == "Concede"
    reject_cues = k.generate_cues(
        family="candid", resolved_action="reject", eta_b="neutral", round_k=6, horizon=10,
        counterpart_price=None, prior_counterpart_price=None, r_b=100.0,
        sentiment_noise=0.0, posture_u=None,
    )
    assert reject_cues.strategic_cue == "Pressure"


# ---------------------------------------------------------------------------
# Counter-offer / opening-offer price projections stay individually rational.
# ---------------------------------------------------------------------------


def test_counter_offer_price_never_crosses_the_counterpart_reservation() -> None:
    # Seller counterpart: M_B(k) = [r_B, p_{k-1}^B]; even with large noise the
    # projected price cannot fall below r_B.
    price = k.counter_offer_price(
        counterpart_role="seller", r_b=100.0, prior_counterpart_price=150.0,
        lambda_b=0.5, price_noise=-1000.0,
    )
    assert price == pytest.approx(100.0)


def test_opening_offer_price_stays_within_the_reservation_bound() -> None:
    price = k.opening_offer_price(
        counterpart_role="seller", r_b=100.0, kappa_b=0.5, eta_b="neutral",
        opening_harshness=0.8, p_min=0.0, p_max=200.0, opening_noise=-1000.0,
    )
    assert price >= 100.0


def test_sigmoid_matches_reference_logistic_function() -> None:
    for x in (-5.0, -0.5, 0.0, 0.5, 5.0):
        assert k.sigmoid(x) == pytest.approx(1.0 / (1.0 + math.exp(-x)), abs=1e-12)
