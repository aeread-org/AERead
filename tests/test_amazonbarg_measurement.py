"""Tests for the amazonbarg.bilateral measurement declarations (measurement.py).

Two kinds of coverage, both provider-free and network-free (scripted/gold
trajectories only, per this build's ground rules):

* Pure leaf-declaration tests (spec section 2) -- no upstream checkout
  needed at all.
* The five QC Gate-2 goldens (spec section 4), each: (1) run through the
  real kernel scheduler (``run_episode``, exactly like
  ``tests/test_amazonbarg_environment.py``'s own ``_run`` helper) to
  produce a real recorded transcript; (2) delegated to upstream's own
  ``eval.py:Metrics`` via ``measurement.compute_upstream_metrics``; (3)
  scored through ``measurement.build_scorer(...).score_all(...)``; and (4)
  cross-checked with a component parity test -- a second, independent
  delegated call to ``eval.py:Metrics`` on the identical recorded
  transcript must reproduce byte-identical output, and every number this
  module's ``ScoreEnvelope``s seal must equal that delegated output
  verbatim, never an independently recomputed or rounded value (mirrors
  ``tau3_retail/parity.py``'s own component-by-component comparison
  discipline, simplified for amazonbarg's in-process delegation -- no
  bridge subprocess is involved).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from aeread.shared_runner.measurement import MeasurementContractError, ScoreEnvelope
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import DecisionRequest, run_episode
from aeread_families.amazonbarg import measurement as m
from aeread_families.amazonbarg import upstream_shim
from aeread_families.amazonbarg.environment import (
    BUYER_PHASE,
    SELLER_PHASE,
    AmazonbargPlugin,
    family_manifest,
    register_plugin,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AMAZONBARG_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg",
    )
    root = Path(candidate)
    marker = root / "data" / "AmazonHistoryPrice" / "home-kitchen.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream AmazonPriceHistory checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/amazonbarg/pilot")


def _case(codename: str) -> CaseManifest:
    from aeread_families.amazonbarg.cases import case_id_for_codename

    case_id = case_id_for_codename(codename)
    path = CASES_DIR / f"{case_id}.json"
    if not path.is_file():
        pytest.skip(f"checked-in case file not found at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_{case.case_id}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_amazonbarg_measurement",
        suite_version="0.1.0",
        block_id="block_amazonbarg_measurement",
        sampling_plan_id="sampling_amazonbarg_measurement",
        analysis_plan_id="analysis_amazonbarg_measurement",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_{case.case_id}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"buyer": "scripted_buyer", "seller": "scripted_seller"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


class _ScriptedReplies:
    """Minimal inline provider-free response source for a fixed reply script.

    Identical in spirit to ``test_amazonbarg_environment.py``'s own helper
    of the same name (duplicated here rather than imported across test
    modules, matching this suite's existing per-file convention -- see
    e.g. every ``test_tau3_retail_*.py`` file's own local ``_bridge()``).
    """

    def __init__(self, script: list[tuple[str, str, str]]) -> None:
        self._script = list(script)
        self._index = 0

    async def __call__(self, request: DecisionRequest) -> dict[str, str]:
        assert self._index < len(self._script), "script exhausted before episode terminated"
        expected_phase, expected_seat, content = self._script[self._index]
        assert request.phase_id == expected_phase
        assert request.seat_id == expected_seat
        self._index += 1
        return {"content": content}

    @property
    def exhausted(self) -> bool:
        return self._index == len(self._script)


def _run_transcript(codename: str, script: list[tuple[str, str, str]]) -> tuple[CaseManifest, dict[str, Any], Any]:
    """Run one scripted golden through the real scheduler; return its history.

    Returns ``(case, family_case, history)`` where ``history`` is exactly
    ``result.final_state["history"]`` -- the same per-round record list
    ``eval.py:Metrics`` itself expects (spec section 2/3;
    ``measurement.build_metrics_line`` documents the shape match).
    """
    case = _case(codename)
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(case.payload)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    scripted = _ScriptedReplies(script)
    result = asyncio.run(
        run_episode(cell=_cell(case), case=case, plugin=resolved_plugin, response_source=scripted)
    )
    assert scripted.exhausted
    return case, family_case, result.final_state["history"]


# ---------------------------------------------------------------------------
# Leaf declaration rules -- pure, no upstream checkout needed.
# ---------------------------------------------------------------------------


def test_build_leaves_declares_exactly_five_leaves_every_time() -> None:
    leaves = m.build_leaves()
    assert len(leaves) == 5
    assert [leaf.leaf_id for leaf in leaves] == [
        m.DEAL_AUTHENTICITY_LEAF_ID,
        m.ZOPA_MEMBERSHIP_LEAF_ID,
        m.DEAL_LOWER_BOUND_LEAF_ID,
        m.DEAL_UPPER_BOUND_LEAF_ID,
        m.BARGAINED_RATIO_LEAF_ID,
    ]
    for leaf in leaves:
        assert leaf.composition_kind == "leaf"
        assert leaf.verifier.evaluation_class == "deterministic"


def test_deal_authenticity_leaf_is_a_delegated_rule_constraint() -> None:
    leaf = m.build_deal_authenticity_leaf()
    assert leaf.verifier.verifier_family == "rule_constraint"
    assert leaf.verifier.reference.reference_kind == "constraint_satisfaction"
    assert leaf.estimand.units == "pass"
    assert leaf.verifier.objective_scope is None


def test_zopa_membership_leaf_is_a_rule_constraint_distinct_from_authenticity() -> None:
    authenticity = m.build_deal_authenticity_leaf()
    zopa = m.build_zopa_membership_leaf()
    assert zopa.verifier.verifier_family == "rule_constraint"
    assert zopa.verifier.reference.reference_kind == "constraint_satisfaction"
    # Two distinct claims, never folded into one (spec section 2).
    assert zopa.leaf_id != authenticity.leaf_id
    assert zopa.estimand.estimand_id != authenticity.estimand.estimand_id
    assert (
        zopa.verifier.reference.source_sha256 != authenticity.verifier.reference.source_sha256
    )


def test_bound_leaves_are_two_separate_objective_reference_leaves() -> None:
    lower = m.build_deal_lower_bound_leaf()
    upper = m.build_deal_upper_bound_leaf()

    assert lower.leaf_id != upper.leaf_id
    for leaf, reference_kind in ((lower, "outcome_support_min"), (upper, "outcome_support_max")):
        assert leaf.verifier.verifier_family == "objective_reference"
        assert leaf.verifier.reference.reference_kind == reference_kind
        assert leaf.estimand.units == "usd"
        # A mandatory ObjectiveScopeSpec matching the estimand's own identity
        # (kernel contract requirement for every objective_reference leaf).
        scope = leaf.verifier.objective_scope
        assert scope is not None
        assert scope.objective_id == leaf.estimand.estimand_id
        assert scope.direction == leaf.estimand.direction


def test_bargained_ratio_leaf_is_comparative_with_no_objective_scope() -> None:
    leaf = m.build_bargained_ratio_leaf()
    assert leaf.verifier.verifier_family == "comparative"
    assert leaf.verifier.reference.reference_kind == "head_to_head"
    assert leaf.verifier.objective_scope is None
    assert leaf.estimand.direction == "maximize"
    assert leaf.estimand.units == "ratio"
    # The fixed scripted-counterpart identity is recorded in the estimand's
    # own validity_domain (spec section 2).
    assert m.SCRIPTED_COUNTERPART_POLICY_ID in leaf.estimand.validity_domain.domain_id


def test_bound_leaf_direction_is_a_documented_placeholder_not_a_real_kernel_none() -> None:
    """The kernel's real ObjectiveScopeSpec has no directionless option.

    Pins the exact contract behaviour driving this module's documented
    interpretation (module docstring): declaring ``direction="none"`` for
    an ``objective_reference`` estimand fails at ``ObjectiveScopeSpec``
    construction, not merely at some looser validation layer.
    """
    from aeread.shared_runner.measurement import (
        EstimandSpec,
        ImplementationRef,
        ObjectiveScopeSpec,
        ValidityDomainSpec,
    )

    domain = ValidityDomainSpec("d", "1.0.0", "ref", ImplementationRef("p", "1.0.0", "a" * 64))
    estimand = EstimandSpec("e", "1.0.0", "terminal_state", "none", "usd", domain)
    with pytest.raises(MeasurementContractError, match="maximize or minimize"):
        ObjectiveScopeSpec(
            "e", "1.0.0", "none", "usd", "fs", "is", "h", "ec", "oc", domain,
        )
    del estimand


# ---------------------------------------------------------------------------
# Delegation: build_metrics_line / compute_upstream_metrics.
# ---------------------------------------------------------------------------


def test_build_metrics_line_mirrors_upstreams_own_session_py_shape() -> None:
    case = _case("home-kitchen_2")
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    family_case = plugin.validate_payload(case.payload)
    derived = family_case["derived"]

    line = m.build_metrics_line(family_case, history=[], row=7)

    assert line["index"] == 0
    assert line["row"] == 7
    assert line["inv"] == {
        derived["codename"]: [derived["title"], derived["description"], derived["price"], derived["cost"]]
    }
    assert line["need"] == [
        {
            "codename": derived["codename"],
            "title": derived["title"],
            "quantity": 1,
            "budget": derived["budget"],
        }
    ]
    assert line["history"] == []


# ---------------------------------------------------------------------------
# QC Gate-2 goldens (spec section 4): real transcript -> delegated Metrics
# -> measurement.py scoring -> component parity against a fresh delegated
# recomputation.
# ---------------------------------------------------------------------------


def _score_and_check_parity(codename: str, script: list[tuple[str, str, str]]) -> tuple[dict[str, Any], dict[str, ScoreEnvelope]]:
    """Run one golden, score it, and assert the component parity property.

    "Component parity": a second, wholly independent delegated call to
    upstream's own ``eval.py:Metrics`` on the identical recorded history
    reproduces byte-identical output (proves determinism -- test plan P3),
    and every number this module's five ``ScoreEnvelope``s seal is read
    verbatim from that same delegated output, never recomputed or altered.
    """
    case, family_case, history = _run_transcript(codename, script)

    metrics_output = m.compute_upstream_metrics(
        upstream_root=UPSTREAM_ROOT, family_case=family_case, history=history
    )
    # Independent second delegated call on the identical transcript --
    # session-scoped shim state is fully evicted between calls (spec
    # section 3.1), so this genuinely re-executes upstream's source fresh.
    replay_metrics_output = m.compute_upstream_metrics(
        upstream_root=UPSTREAM_ROOT, family_case=family_case, history=history
    )
    assert metrics_output == replay_metrics_output
    assert upstream_shim.miss_count() == 0

    scorer = m.build_scorer(family_case)
    envelopes: dict[str, ScoreEnvelope] = {}
    for tested_seat in ("buyer", "seller"):
        envelopes[f"ratio_{tested_seat}"] = scorer.score_bargained_ratio(
            metrics_output=metrics_output, tested_seat=tested_seat
        )
    envelopes["authenticity"] = scorer.score_deal_authenticity(metrics_output=metrics_output)
    envelopes["zopa"] = scorer.score_zopa_membership(metrics_output=metrics_output)
    envelopes["lower"] = scorer.score_deal_lower_bound(metrics_output=metrics_output)
    envelopes["upper"] = scorer.score_deal_upper_bound(metrics_output=metrics_output)

    # Component parity: any sealed numeric value traced back to a
    # `metrics_output` field must equal that field verbatim (never an
    # independently recomputed number).
    if "D" in metrics_output:
        if envelopes["zopa"].status == "ok":
            assert envelopes["zopa"].metrics["deal_price"].value == metrics_output["D"]
        assert envelopes["lower"].primary.value == metrics_output["D"]
        assert envelopes["upper"].primary.value == metrics_output["D"]
    if "buyer_bargained_ratio" in metrics_output:
        assert envelopes["ratio_buyer"].primary.value == metrics_output["buyer_bargained_ratio"]
        assert envelopes["ratio_seller"].primary.value == metrics_output["seller_bargained_ratio"]

    return metrics_output, envelopes


def test_golden_1_successful_deal_shark_vacuum() -> None:
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: hi\nAction: [BUY] $120 (1x home-kitchen_2)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: ok\nAction: [SELL] $150 (1x home-kitchen_2)"),
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: deal?\nAction: [BUY] $135 (1x home-kitchen_2)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: yes\nAction: [DEAL] $135 (1x home-kitchen_2)"),
    ]
    metrics_output, envelopes = _score_and_check_parity("home-kitchen_2", script)

    assert metrics_output["wrongAction"] == 0
    assert metrics_output["closeADeal"] == 1
    assert metrics_output["D"] == pytest.approx(135.0)

    assert envelopes["authenticity"].status == "ok"
    assert envelopes["authenticity"].primary.value == 1.0
    assert envelopes["zopa"].status == "ok"
    assert envelopes["zopa"].primary.value == 1.0  # 135 in [95.0, 173.44]
    assert envelopes["lower"].status == "ok"
    assert envelopes["upper"].status == "ok"
    assert envelopes["ratio_buyer"].primary.value == pytest.approx(0.49, abs=0.01)
    assert envelopes["ratio_seller"].primary.value == pytest.approx(0.51, abs=0.01)
    assert envelopes["ratio_buyer"].utility_by_seat["seller"].value == envelopes["ratio_seller"].primary.value


def test_golden_2_valid_but_poor_deal_calphalon() -> None:
    """cost=$60.99, budget~=$103.99; an authentic deal at $61.50 that is
    legal on both rule_constraint leaves but comparatively bad for the
    seller (spec section 4: ``seller_bargained_ratio ~= 0.012``)."""
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: hi\nAction: [BUY] $61.5 (1x home-kitchen_3)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: ok\nAction: [DEAL] $61.5 (1x home-kitchen_3)"),
    ]
    metrics_output, envelopes = _score_and_check_parity("home-kitchen_3", script)

    assert metrics_output["wrongAction"] == 0
    assert metrics_output["closeADeal"] == 1
    assert envelopes["authenticity"].primary.value == 1.0
    assert envelopes["zopa"].primary.value == 1.0
    assert envelopes["ratio_seller"].primary.value == pytest.approx(0.012, abs=0.001)


def test_golden_3_invalid_unauthorized_below_cost_deal_breville() -> None:
    """cost=$524.97, budget=$599.96; the deal matches a genuine prior
    offer exactly (so ``amazonbarg_deal_authenticity`` passes -- upstream
    calls this a legitimate deal) but closes below cost, so AERead's own
    ``amazonbarg_zopa_membership`` fails (spec section 4 golden 3)."""
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: hi\nAction: [BUY] $400 (1x home-kitchen_5)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: ok\nAction: [SELL] $480 (1x home-kitchen_5)"),
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: deal?\nAction: [BUY] $480 (1x home-kitchen_5)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: yes\nAction: [DEAL] $480 (1x home-kitchen_5)"),
    ]
    metrics_output, envelopes = _score_and_check_parity("home-kitchen_5", script)

    assert metrics_output["wrongAction"] == 0  # authentic: matches buyer's own $480 offer
    assert metrics_output["D"] == pytest.approx(480.0)
    assert metrics_output["D"] < metrics_output["C"]  # below cost

    assert envelopes["authenticity"].status == "ok"
    assert envelopes["authenticity"].primary.value == 1.0  # upstream calls this legitimate
    assert envelopes["zopa"].status == "ok"
    assert envelopes["zopa"].primary.value == 0.0  # AERead's own check catches it
    assert envelopes["lower"].status == "ok"
    assert envelopes["lower"].primary.value == pytest.approx(480.0)


def test_golden_4_malformed_operational_missing_action_line_bean_bag() -> None:
    """A missing ``Action:`` line -> upstream's own ``wrongAction=1``.
    ``amazonbarg_deal_authenticity`` still seals ``status="ok"`` with a
    failing primary (the malformed action is the evidence); the
    comparative and both bound leaves seal typed ``invalid_measurement``,
    never a computed zero (spec section 2's measurement validity gate)."""
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: no action line here"),
    ]
    metrics_output, envelopes = _score_and_check_parity("home-kitchen_4", script)

    assert metrics_output["wrongAction"] == 1
    assert "D" not in metrics_output

    assert envelopes["authenticity"].status == "ok"
    assert envelopes["authenticity"].primary.value == 0.0

    for key in ("zopa", "lower", "upper", "ratio_buyer", "ratio_seller"):
        envelope = envelopes[key]
        assert envelope.status == "invalid_measurement"
        assert envelope.primary is None
        assert envelope.validity.status == "invalid"
        assert m.reasons_include(envelope.validity, m.REASON_ACTION_ERROR)


def test_golden_5_degenerate_reference_dji_drone_quits() -> None:
    """cost=$959.00 > budget~=$864.93 -- the pilot's one conflicting-interest
    session; no ZOPA exists. ``amazonbarg_zopa_membership`` and both bound
    leaves report a typed ``degenerate_no_zopa`` reason, never a computed
    pass/fail or bound value (spec section 4 golden 5)."""
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: hi\nAction: [BUY] $850 (1x toys-games_22)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: no\nAction: [REJECT]"),
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: bye\nAction: [QUIT]"),
    ]
    metrics_output, envelopes = _score_and_check_parity("toys-games_22", script)

    assert metrics_output["wrongAction"] == 0
    assert metrics_output["closeADeal"] == 0
    assert metrics_output["costGTbudget"] == 1

    assert envelopes["authenticity"].status == "ok"
    assert envelopes["authenticity"].primary.value == 1.0  # the correct behavior

    for key in ("zopa", "lower", "upper", "ratio_buyer", "ratio_seller"):
        envelope = envelopes[key]
        assert envelope.status == "invalid_measurement"
        assert envelope.primary is None
        assert m.reasons_include(envelope.validity, m.REASON_DEGENERATE_NO_ZOPA)
        assert not m.reasons_include(envelope.validity, m.REASON_ACTION_ERROR)


# ---------------------------------------------------------------------------
# The measurement validity gate itself, directly.
# ---------------------------------------------------------------------------


def _family_case(interest: str, cost: float = 10.0, budget: float = 20.0) -> dict[str, Any]:
    return {"derived": {"interest": interest, "cost": cost, "budget": budget}}


def test_gate_is_none_when_a_real_deal_can_be_reported() -> None:
    gate = m._measurement_gate(  # noqa: SLF001 - unit-testing the private gate directly
        family_case=_family_case("mutual"),
        metrics_output={"wrongAction": 0, "closeADeal": 1},
    )
    assert gate is None


def test_gate_reports_action_error_prefix_on_wrong_action() -> None:
    gate = m._measurement_gate(
        family_case=_family_case("mutual"), metrics_output={"wrongAction": 1, "closeADeal": 0}
    )
    assert gate is not None
    assert any(reason.startswith(f"{m.REASON_ACTION_ERROR}:") for reason in gate)


def test_gate_reports_degenerate_prefix_when_cost_exceeds_budget() -> None:
    gate = m._measurement_gate(
        family_case=_family_case("conflicting", cost=20.0, budget=10.0),
        metrics_output={"wrongAction": 0, "closeADeal": 0},
    )
    assert gate is not None
    assert any(reason.startswith(f"{m.REASON_DEGENERATE_NO_ZOPA}:") for reason in gate)


def test_gate_reports_no_deal_prefix_when_no_deal_closed() -> None:
    gate = m._measurement_gate(
        family_case=_family_case("mutual"), metrics_output={"wrongAction": 0, "closeADeal": 0}
    )
    assert gate is not None
    assert any(reason.startswith(f"{m.REASON_NO_DEAL}:") for reason in gate)


def test_gate_reports_no_evidence_prefix_when_metrics_never_ran() -> None:
    gate = m._measurement_gate(family_case=_family_case("mutual"), metrics_output={})
    assert gate == (
        f"{m.REASON_NO_EVIDENCE}: upstream Metrics produced no wrongAction "
        "verdict (empty recorded history)",
    )


def test_score_bargained_ratio_rejects_an_unknown_tested_seat() -> None:
    leaf = m.build_bargained_ratio_leaf()
    with pytest.raises(ValueError, match="tested_seat"):
        m.score_bargained_ratio(
            leaf,
            family_case=_family_case("mutual"),
            metrics_output={"wrongAction": 0, "closeADeal": 1, "buyer_bargained_ratio": 0.5, "seller_bargained_ratio": 0.5},
            tested_seat="referee",
        )
