"""Tests for the agenticpay.bilateral measurement declarations (measurement.py).

Two kinds of coverage, mirroring ``tests/test_tau3_retail_measurement.py``'s
own split:

* Pure, provider-free, bridge-free tests against synthetic ``family_case``/
  ``terminal``/``round_trace`` fixtures -- these run everywhere and exercise
  the leaf-declaration and scorer rules (spec section 2) directly.
* Bridge-gated tests that drive a real episode through the kernel scheduler
  (``run_episode``) and the pinned upstream checkout, then score the
  resulting terminal state with the real ``measurement.py`` scorer. These
  follow ``tests/test_agenticpay_bilateral_environment.py``'s
  ``_bridge()``/skip convention: they run for real when
  ``$AEREAD_AGENTICPAY_BRIDGE_PYTHON``/a colocated venv resolves to a
  provisioned interpreter, and are skipped (never faked) otherwise. This
  section also implements the five QC Gate-2 goldens (spec section 4) as
  executable tests, plus a component parity check that the surplus-share
  leaves recombine (via upstream's own published ``Q = 4 * u_b * u_s``
  formula) to upstream's own recorded ``GlobalScore`` for the same scripted
  trajectory -- "our recorded scoring equals upstream computed scoring".
  The basic-mode variant of that check is the same class of independent
  cross-check ``test_tau3_retail_measurement.py`` performs against
  ``tau2.evaluator.evaluator_env.EnvironmentEvaluator``: ``u_b``/``u_s`` are
  recomputed here from ``agreed_price`` alone, never read back off
  upstream's own state. The contract-mode variant is weaker and is *not*
  independent in the same sense: contract-mode ``u_b``/``u_s`` are upstream's
  own ``buyer_utility``/``seller_utility`` read back verbatim off
  ``state.metadata`` (see ``measurement.py``'s ``_score_surplus_share``),
  the exact inputs upstream itself just used to compute ``GlobalScore``, so
  equality holds by construction; it can only catch a typo in this
  adapter's own copy of the weights/discount/``Q`` formula, never an error
  in upstream's own MAUT utility calculation. See that test's own docstring.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.measurement import MeasurementContractError, MetricValue
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import DecisionRequest, run_episode
from aeread_families.agenticpay_bilateral import measurement as m
from aeread_families.agenticpay_bilateral.agenticpay_bridge import (
    AgenticpayBridge,
    AgenticpayBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.agenticpay_bilateral.environment import (
    BUYER_PHASE,
    SELLER_PHASE,
    AgenticpayBilateralPlugin,
    family_manifest,
    register_plugin,
)

CASES_DIR = Path("cases/agenticpay_bilateral")


def _case(case_id: str) -> CaseManifest:
    split = case_id.split(".")[2]
    path = CASES_DIR / split / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _family_case(case_id: str) -> dict:
    return json.loads(canonical_json_bytes(_case(case_id).payload))


BASIC_CASE_ID = "agenticpay.bilateral.basic.task1"
REALISTIC_CASE_ID = "agenticpay.bilateral.realistic.s01_beauty_product"


# ---------------------------------------------------------------------------
# Pure, bridge-free: leaf declarations.
# ---------------------------------------------------------------------------


def test_basic_case_declares_exactly_three_leaves_no_contract_legality() -> None:
    family_case = _family_case(BASIC_CASE_ID)
    assert m.is_contract_mode(family_case) is False
    leaves = m.build_leaves(family_case)
    assert [leaf.leaf_id for leaf in leaves] == [
        m.DEAL_REACHED_LEAF_ID,
        m.BUYER_SURPLUS_LEAF_ID,
        m.SELLER_SURPLUS_LEAF_ID,
    ]
    assert m.build_contract_legality_leaf(family_case) is None


def test_realistic_case_declares_all_four_leaves() -> None:
    family_case = _family_case(REALISTIC_CASE_ID)
    assert m.is_contract_mode(family_case) is True
    leaves = m.build_leaves(family_case)
    assert [leaf.leaf_id for leaf in leaves] == [
        m.DEAL_REACHED_LEAF_ID,
        m.BUYER_SURPLUS_LEAF_ID,
        m.SELLER_SURPLUS_LEAF_ID,
        m.CONTRACT_LEGALITY_LEAF_ID,
    ]


def test_deal_reached_leaf_is_a_deterministic_rule_constraint_leaf() -> None:
    leaf = m.build_deal_reached_leaf(_family_case(BASIC_CASE_ID))
    assert leaf.verifier.verifier_family == "rule_constraint"
    assert leaf.verifier.evaluation_class == "deterministic"
    assert leaf.verifier.reference.reference_kind == "constraint_satisfaction"
    assert leaf.estimand.input_scope == "terminal_state"


def test_contract_legality_leaf_uses_trajectory_input_scope_deviation() -> None:
    # Spec section 2 literally writes input_scope="action"; the kernel's
    # real EstimandSpec only accepts {"answer", "terminal_state",
    # "trajectory", "distribution"} -- see measurement.py's own docstring.
    leaf = m.build_contract_legality_leaf(_family_case(REALISTIC_CASE_ID))
    assert leaf is not None
    assert leaf.estimand.input_scope == "trajectory"
    assert leaf.verifier.verifier_family == "rule_constraint"
    with pytest.raises(MeasurementContractError):
        from aeread.shared_runner.measurement import EstimandSpec, ValidityDomainSpec

        EstimandSpec(
            estimand_id="agenticpay_contract_legality",
            estimand_version="1.0.0",
            input_scope="action",
            direction="none",
            units="pass",
            validity_domain=leaf.estimand.validity_domain,
        )


def test_surplus_share_leaves_are_objective_reference_with_outcome_support_max() -> None:
    # Spec section 2 literally writes reference_kind="outcome_support_normalized";
    # the kernel only accepts "outcome_support_max" (among others) for an
    # objective_reference verifier -- see measurement.py's own docstring.
    for leaf in (
        m.build_buyer_surplus_share_leaf(_family_case(BASIC_CASE_ID)),
        m.build_seller_surplus_share_leaf(_family_case(BASIC_CASE_ID)),
    ):
        assert leaf.verifier.verifier_family == "objective_reference"
        assert leaf.verifier.reference.reference_kind == "outcome_support_max"
        assert leaf.verifier.objective_scope is not None
        assert leaf.verifier.objective_scope.direction == "maximize"
        assert leaf.estimand.units == "share_of_zopa"


# ---------------------------------------------------------------------------
# Pure, bridge-free: scorers against synthetic fixtures.
# ---------------------------------------------------------------------------


def test_score_deal_reached_is_1_iff_terminal_reason_is_agreed() -> None:
    leaf = m.build_deal_reached_leaf(_family_case(BASIC_CASE_ID))
    agreed = m.score_deal_reached(leaf, terminal={"reason": "agreed"})
    timeout = m.score_deal_reached(leaf, terminal={"reason": "timeout"})
    assert agreed.primary.value == 1.0
    assert timeout.primary.value == 0.0


def test_score_deal_reached_carries_diagnostics_through_without_changing_primary() -> None:
    leaf = m.build_deal_reached_leaf(_family_case(BASIC_CASE_ID))
    diagnostics = {"parse_failure_count": MetricValue(1.0, "count")}
    envelope = m.score_deal_reached(leaf, terminal={"reason": "agreed"}, diagnostics=diagnostics)
    assert envelope.primary.value == 1.0
    assert envelope.metrics["parse_failure_count"].value == 1.0


def test_build_action_diagnostics_flags_only_digit_free_non_contract_messages() -> None:
    round_trace = [
        {
            "round": 1,
            "buyer_action": "this is not a price at all, just chatter",
            "seller_action": "### SELLER_PRICE($130) ###",
            "buyer_contract_attempted": False,
            "seller_contract_attempted": False,
        },
        {
            "round": 2,
            "buyer_action": "### BUYER_PRICE($100) ###",
            "seller_action": "### SELLER_PRICE($100) ###",
            "buyer_contract_attempted": False,
            "seller_contract_attempted": False,
        },
        {
            "round": 3,
            "buyer_action": "<contract>{}</contract>",
            "seller_action": "no digits but a contract attempt",
            "buyer_contract_attempted": True,
            "seller_contract_attempted": False,
        },
    ]
    diagnostics = m.build_action_diagnostics(round_trace)
    assert diagnostics["round_1_buyer_parse_failure"].value == 1.0
    assert "round_1_seller_parse_failure" not in diagnostics
    assert "round_2_buyer_parse_failure" not in diagnostics
    assert "round_2_seller_parse_failure" not in diagnostics
    # round 3's seller message has no digits and is not a contract attempt.
    assert diagnostics["round_3_seller_parse_failure"].value == 1.0
    assert "round_3_buyer_parse_failure" not in diagnostics  # contract-tagged, skipped
    assert diagnostics["parse_failure_count"].value == 2.0


def test_score_contract_legality_flags_only_the_rejected_round() -> None:
    leaf = m.build_contract_legality_leaf(_family_case(REALISTIC_CASE_ID))
    assert leaf is not None
    round_trace = [
        {
            "round": 1,
            "buyer_contract_attempted": True,
            "buyer_contract_before": None,
            "buyer_contract_after": {"price": 5.39},
            "buyer_contract_valid": True,
            "seller_contract_attempted": True,
            "seller_contract_before": None,
            "seller_contract_after": None,  # rejected: unchanged
            "seller_contract_valid": False,
        },
        {
            "round": 2,
            "buyer_contract_attempted": False,
            "seller_contract_attempted": True,
            "seller_contract_before": None,
            "seller_contract_after": {"price": 5.39},  # accepted: changed
            "seller_contract_valid": True,
        },
    ]
    envelope = m.score_contract_legality(leaf, round_trace=round_trace)
    assert envelope.primary.value == 0.0  # any rejection anywhere -> fail
    assert envelope.metrics["round_1_buyer_contract_legal"].value == 1.0
    assert envelope.metrics["round_1_seller_contract_legal"].value == 0.0
    assert envelope.metrics["round_2_seller_contract_legal"].value == 1.0
    assert "round_2_buyer_contract_legal" not in envelope.metrics


def test_score_contract_legality_uses_upstreams_valid_verdict_not_a_before_after_diff() -> None:
    """Second-review regression (Codex finding 4), unit-level: a repeated,
    already-accepted contract leaves ``*_contract_before == *_contract_after``
    (upstream's own state slot does not visibly change) yet must still be scored
    legal, because upstream's own ``*_contract_valid`` verdict for that round says
    so. This is the pure-fixture sibling of
    ``test_repeating_an_already_accepted_legal_contract_is_not_marked_illegal``
    (which drives the real bridge).
    """
    leaf = m.build_contract_legality_leaf(_family_case(REALISTIC_CASE_ID))
    assert leaf is not None
    round_trace = [
        {
            "round": 1,
            "buyer_contract_attempted": True,
            "buyer_contract_before": {"price": 5.39},
            "buyer_contract_after": {"price": 5.39},  # unchanged: repeated verbatim
            "buyer_contract_valid": True,  # ...but upstream re-validated and accepted it
        },
    ]
    envelope = m.score_contract_legality(leaf, round_trace=round_trace)
    assert envelope.metrics["round_1_buyer_contract_legal"].value == 1.0
    assert envelope.primary.value == 1.0


def test_score_contract_legality_is_vacuously_1_when_nothing_attempted() -> None:
    leaf = m.build_contract_legality_leaf(_family_case(REALISTIC_CASE_ID))
    assert leaf is not None
    envelope = m.score_contract_legality(leaf, round_trace=[])
    assert envelope.primary.value == 1.0
    assert envelope.metrics == {}


def test_score_buyer_surplus_share_basic_mode_valid_and_degenerate() -> None:
    family_case = _family_case(BASIC_CASE_ID)  # buyer_max=150, seller_min=80
    leaf = m.build_buyer_surplus_share_leaf(family_case)
    ok = m.score_buyer_surplus_share(leaf, family_case=family_case, terminal={"agreed_price": 100.0})
    assert ok.status == "ok"
    assert ok.primary.value == pytest.approx(50.0 / 70.0)
    assert ok.reference_values["outcome_support_min"].value == 0.0
    assert ok.reference_values["outcome_support_max"].value == 1.0

    no_agreement = m.score_buyer_surplus_share(
        leaf, family_case=family_case, terminal={"agreed_price": None}
    )
    assert no_agreement.status == "invalid_measurement"
    assert no_agreement.validity.reasons == ("no_agreement_reached",)
    assert no_agreement.primary is None


def test_score_seller_surplus_share_degenerate_zopa_never_fabricates_a_share() -> None:
    degenerate_case = _family_case(BASIC_CASE_ID)
    degenerate_case["constructor_kwargs"]["buyer_max_price"] = 90.0
    degenerate_case["constructor_kwargs"]["seller_min_price"] = 100.0
    leaf = m.build_seller_surplus_share_leaf(degenerate_case)
    envelope = m.score_seller_surplus_share(
        leaf, family_case=degenerate_case, terminal={"agreed_price": 95.0}
    )
    assert envelope.status == "invalid_measurement"
    assert envelope.validity.reasons == ("denominator_degenerate",)
    assert envelope.primary is None


def test_score_buyer_surplus_share_contract_mode_uses_z_max_and_recorded_utility() -> None:
    family_case = _family_case(REALISTIC_CASE_ID)
    leaf = m.build_buyer_surplus_share_leaf(family_case)
    envelope = m.score_buyer_surplus_share(
        leaf, family_case=family_case, terminal={"z_max": 1.2, "buyer_utility": 0.6}
    )
    assert envelope.status == "ok"
    assert envelope.primary.value == pytest.approx(0.5)

    degenerate = m.score_buyer_surplus_share(
        leaf, family_case=family_case, terminal={"z_max": None, "buyer_utility": 0.6}
    )
    assert degenerate.status == "invalid_measurement"
    assert degenerate.validity.reasons == ("denominator_degenerate",)


# ---------------------------------------------------------------------------
# Bridge-gated: goldens driven end to end through the real kernel scheduler.
# ---------------------------------------------------------------------------


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AGENTICPAY_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-agenticpay",
    )
    root = Path(candidate)
    marker = root / "agenticpay" / "envs" / "single_buyer_product_seller" / "Task1_basic_price_negotiation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream AgenticPay checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except AgenticpayBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> AgenticpayBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "upstream AgenticPay Python interpreter unavailable")
    return AgenticpayBridge(python_executable=BRIDGE_PYTHON, upstream_root=UPSTREAM_ROOT)


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_agenticpay_bilateral_measurement",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_agenticpay_bilateral_measurement",
        suite_version="0.1.0",
        block_id="block_agenticpay_bilateral_measurement",
        sampling_plan_id="sampling_agenticpay_bilateral_measurement",
        analysis_plan_id="analysis_agenticpay_bilateral_measurement",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_agenticpay_bilateral_measurement",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType({"buyer": "scripted_buyer", "seller": "scripted_seller"}),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


class _ScriptedNegotiation:
    """Serve a fixed, ordered sequence of buyer/seller messages, one round at a time.

    Duplicated from ``tests/test_agenticpay_bilateral_environment.py`` rather
    than imported, mirroring ``test_tau3_retail_measurement.py``'s own
    convention of not cross-importing test helpers between test modules.
    """

    def __init__(self, rounds: list[tuple[str, str]]) -> None:
        self._rounds = rounds
        self._index = 0

    async def __call__(self, request: DecisionRequest) -> dict[str, str]:
        if self._index >= len(self._rounds):
            raise AssertionError("scripted negotiation exhausted before the episode terminated")
        buyer_message, seller_message = self._rounds[self._index]
        if request.phase_id == BUYER_PHASE:
            assert request.seat_id == "buyer"
            return {"message": buyer_message}
        if request.phase_id == SELLER_PHASE:
            assert request.seat_id == "seller"
            self._index += 1
            return {"message": seller_message}
        raise AssertionError(f"unexpected phase in scripted negotiation: {request.phase_id}")


def _run(case: CaseManifest, rounds: list[tuple[str, str]]):
    bridge = _bridge()
    cell = _cell(case)
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    scripted = _ScriptedNegotiation(rounds)
    result = asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=scripted)
    )
    scorer = resolved_plugin.build_scorer(json.loads(canonical_json_bytes(case.payload)))
    return result, scorer


def _degenerate_basic_case() -> CaseManifest:
    """Task1's payload with buyer_max/seller_min flipped so Z <= 0 (golden 5)."""
    from aeread.shared_runner.run.resolver import case_content_sha256

    base = _case(BASIC_CASE_ID)
    degenerate_payload = json.loads(canonical_json_bytes(base.payload))
    degenerate_payload["constructor_kwargs"]["buyer_max_price"] = 90.0
    degenerate_payload["constructor_kwargs"]["seller_min_price"] = 100.0
    degenerate_payload["constructor_kwargs"]["initial_seller_price"] = 100.0
    degenerate_payload["constructor_kwargs"]["price_tolerance"] = 1.0
    draft = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": base.case_id,
        "family_id": base.family_id,
        "family_version": base.family_version,
        "split": base.split,
        "world_seed": base.world_seed,
        "seats": [{"id": seat.id, "role": seat.role} for seat in base.seats],
        "episode": {
            "max_logical_actions": base.episode.max_logical_actions,
            "termination": list(base.episode.termination),
        },
        "visibility_policy": base.visibility_policy,
        "payload": degenerate_payload,
        "provenance": {
            "generator_id": base.provenance.generator_id,
            "generator_version": base.provenance.generator_version,
            "review_status": base.provenance.review_status,
        },
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256({**draft, "content_sha256": "0" * 64})
    return CaseManifest.from_dict({**draft, "content_sha256": digest})


# ---- Golden 1: successful -------------------------------------------------


def test_golden_1_successful_negotiation() -> None:
    case = _case(BASIC_CASE_ID)  # buyer_max=150, seller_min=80 -> Z=70
    result, scorer = _run(
        case,
        rounds=[
            ("### BUYER_PRICE($90) ###", "### SELLER_PRICE($130) ###"),
            ("### BUYER_PRICE($100) ###", "### SELLER_PRICE($100) ###"),
        ],
    )
    assert result.terminal["agreed_price"] == 100.0

    deal = scorer.score_deal_reached(terminal=result.terminal)
    buyer_share = scorer.score_buyer_surplus_share(terminal=result.terminal)
    seller_share = scorer.score_seller_surplus_share(terminal=result.terminal)

    assert deal.primary.value == 1.0
    assert buyer_share.status == "ok"
    assert buyer_share.primary.value == pytest.approx(50.0 / 70.0)
    assert seller_share.status == "ok"
    assert seller_share.primary.value == pytest.approx(20.0 / 70.0)


# ---- Golden 2: valid but poor ----------------------------------------------


def test_golden_2_valid_but_poor_negotiation() -> None:
    case = _case(BASIC_CASE_ID)  # Z=70; price 146.5 -> u_b=0.05, u_s=0.95
    result, scorer = _run(
        case,
        rounds=[("### BUYER_PRICE($146.5) ###", "### SELLER_PRICE($146.5) ###")],
    )
    assert result.terminal["agreed_price"] == 146.5

    deal = scorer.score_deal_reached(terminal=result.terminal)
    buyer_share = scorer.score_buyer_surplus_share(terminal=result.terminal)
    seller_share = scorer.score_seller_surplus_share(terminal=result.terminal)

    assert deal.primary.value == 1.0
    assert buyer_share.primary.value == pytest.approx(0.05)
    assert seller_share.primary.value == pytest.approx(0.95)


# ---- Golden 3: invalid or unauthorized -------------------------------------


_LEGAL_CONTRACT = (
    '<contract>{"price": 5.39, "continuous_terms": {"delivery_days": 1}, '
    '"discrete_terms": {"return_policy": "none", "packaging": "protective", '
    '"user_product_preference": "strong_match"}}</contract>'
)
_ILLEGAL_CONTRACT = (
    '<contract>{"price": 5.39, "continuous_terms": {"delivery_days": 10}, '
    '"discrete_terms": {"return_policy": "lifetime", "packaging": "protective", '
    '"user_product_preference": "strong_match"}}</contract>'
)
# Individually legal (satisfies s01's declared bounds) but incompatible with
# _LEGAL_CONTRACT's `delivery_days: 1` -- upstream's own `_contracts_compatible`
# requires equal `continuous_terms`, so pairing this with _LEGAL_CONTRACT never
# reaches agreement on its own (second-review Codex finding 4 below).
_ANOTHER_LEGAL_CONTRACT = (
    '<contract>{"price": 5.39, "continuous_terms": {"delivery_days": 3}, '
    '"discrete_terms": {"return_policy": "none", "packaging": "protective", '
    '"user_product_preference": "strong_match"}}</contract>'
)


def test_golden_3_invalid_or_unauthorized_contract_offer() -> None:
    case = _case(REALISTIC_CASE_ID)
    result, scorer = _run(
        case,
        rounds=[
            (_LEGAL_CONTRACT, _ILLEGAL_CONTRACT),
            ("Still holding my last offer, please confirm.", _LEGAL_CONTRACT),
        ],
    )
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["rounds"] == 2
    # The seller's round-1 illegal contract earns no state mutation and no
    # round score; the round-2 legal resubmission reaches the same
    # GlobalScore this contract already reaches when agreed at round 1
    # (spec section 4 golden 3).
    assert result.terminal["global_score"] == pytest.approx(99.0)

    legality = scorer.score_contract_legality(round_trace=result.terminal["round_trace"])
    assert legality.primary.value == 0.0  # any rejection anywhere -> fail
    assert legality.metrics["round_1_buyer_contract_legal"].value == 1.0
    assert legality.metrics["round_1_seller_contract_legal"].value == 0.0
    assert legality.metrics["round_2_seller_contract_legal"].value == 1.0
    assert "round_2_buyer_contract_legal" not in legality.metrics

    # The round-1 leaf check above proves "no mutation" only indirectly,
    # through score_contract_legality's own definition of "accepted"
    # (measurement.py's `seller_contract_before == seller_contract_after`);
    # assert the underlying round_trace fields directly here too, so this
    # golden's "no protected state changed" claim is self-evident from the
    # test body and does not silently change meaning if that definition is
    # ever refactored.
    round_1 = result.terminal["round_trace"][0]
    assert round_1["seller_contract_after"] is None
    assert round_1["seller_contract_after"] == round_1["seller_contract_before"]

    # The deal and both surplus shares are unaffected by the rejected round.
    deal = scorer.score_deal_reached(terminal=result.terminal)
    buyer_share = scorer.score_buyer_surplus_share(terminal=result.terminal)
    seller_share = scorer.score_seller_surplus_share(terminal=result.terminal)
    assert deal.primary.value == 1.0
    assert buyer_share.primary.value == pytest.approx(0.5)
    assert seller_share.primary.value == pytest.approx(0.5)


# ---- Second-review regression: repeated legal contract ---------------------


def test_repeating_an_already_accepted_legal_contract_is_not_marked_illegal() -> None:
    """Second-review regression (Codex finding 4): "accepted" must not be inferred
    from whether upstream's stored contract *value* changed round to round.
    Upstream assigns every parsed, validated contract to state on every round it
    validates, even when it equals the previous value (``Task1_basic_price_
    negotiation.py``'s ``step()``: ``if buyer_contract and self._validate_
    contract(buyer_contract): self.state.metadata["buyer_contract"] =
    buyer_contract`` -- unconditional on whether the value changed). Round 1: the
    buyer submits a legal contract C; the seller submits a different, individually
    legal but incompatible contract D (different ``delivery_days``), so no
    agreement forms yet. Round 2: the buyer repeats C verbatim (still legal, but
    upstream's own state slot for it does not visibly change) while the seller
    submits C too (now compatible) and the deal is reached. Before this fix, the
    buyer's round-2 resubmission was marked illegal purely because
    ``buyer_contract_before == buyer_contract_after``.
    """
    case = _case(REALISTIC_CASE_ID)
    result, scorer = _run(
        case,
        rounds=[
            (_LEGAL_CONTRACT, _ANOTHER_LEGAL_CONTRACT),
            (_LEGAL_CONTRACT, _LEGAL_CONTRACT),
        ],
    )
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["rounds"] == 2

    legality = scorer.score_contract_legality(round_trace=result.terminal["round_trace"])
    assert legality.metrics["round_1_buyer_contract_legal"].value == 1.0
    assert legality.metrics["round_1_seller_contract_legal"].value == 1.0
    assert legality.metrics["round_2_seller_contract_legal"].value == 1.0
    # The regression: round 2's buyer resubmission of the same legal contract C
    # must still be scored legal, not illegal just because the stored value did
    # not visibly change.
    assert legality.metrics["round_2_buyer_contract_legal"].value == 1.0
    assert legality.primary.value == 1.0  # nothing anywhere was ever rejected


# ---- Golden 4: malformed / operational failure -----------------------------


def test_golden_4_malformed_action_text_is_flagged_not_scored_as_a_task_zero() -> None:
    case = _case(BASIC_CASE_ID)
    result, scorer = _run(
        case,
        rounds=[
            ("this is not a price at all, just chatter", "### SELLER_PRICE($130) ###"),
            ("### BUYER_PRICE($100) ###", "### SELLER_PRICE($100) ###"),
        ],
    )
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["rounds"] == 2

    diagnostics = m.build_action_diagnostics(result.terminal["round_trace"])
    assert diagnostics["round_1_buyer_parse_failure"].value == 1.0
    assert "round_1_seller_parse_failure" not in diagnostics
    assert "round_2_buyer_parse_failure" not in diagnostics
    assert diagnostics["parse_failure_count"].value == 1.0

    # Never a task-quality zero: the deal still reaches full credit.
    deal = scorer.score_deal_reached(terminal=result.terminal, diagnostics=diagnostics)
    assert deal.primary.value == 1.0
    assert deal.metrics["round_1_buyer_parse_failure"].value == 1.0


# ---- Golden 5: degenerate reference -----------------------------------------


def test_golden_5_degenerate_reference_never_fabricates_a_share() -> None:
    case = _degenerate_basic_case()  # buyer_max=90 < seller_min=100 -> Z<=0
    result, scorer = _run(case, rounds=[("### BUYER_PRICE($95) ###", "### SELLER_PRICE($95) ###")])
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["global_score"] == pytest.approx(0.0, abs=1e-9)

    deal = scorer.score_deal_reached(terminal=result.terminal)
    buyer_share = scorer.score_buyer_surplus_share(terminal=result.terminal)
    seller_share = scorer.score_seller_surplus_share(terminal=result.terminal)

    assert deal.primary.value == 1.0  # deal_reached is independent of quality
    for envelope in (buyer_share, seller_share):
        assert envelope.status == "invalid_measurement"
        assert envelope.validity.reasons == ("denominator_degenerate",)
        assert envelope.primary is None


# ---- Second-review regression: out-of-declared-range agreement -------------


def test_surplus_share_rejects_an_agreed_price_outside_the_declared_zopa_bounds() -> None:
    """Second-review regression (Codex finding 2): a positive ZOPA denominator alone
    is not enough to publish a share in ``[0, 1]``. Upstream's own scoring
    (``Task1_basic_price_negotiation.py``'s ``_calculate_global_score``) additionally
    requires ``seller_min_price <= final_price <= buyer_max_price`` before it will
    treat a deal as a success -- an agreement outside that declared range is exactly
    the ``valid_range=False`` branch upstream itself falls back to a failure penalty
    for. Driven through the real scheduler + real bridge (production path, not a
    hand-built ``terminal`` fixture): both parties submit $200 for task1
    (buyer_max=150, seller_min=80), a price neither reservation would ever legitimately
    accept, so upstream's own text-matching negotiation still reaches ``"agreed"`` at
    $200. Before this fix, ``score_buyer_surplus_share``/``score_seller_surplus_share``
    published ``status="ok"`` with shares (buyer -50/70, seller 120/70) outside their
    own declared ``[0, 1]`` support -- this asserts ``invalid_measurement`` instead.
    """
    case = _case(BASIC_CASE_ID)  # buyer_max=150, seller_min=80 -> Z=70
    result, scorer = _run(
        case,
        rounds=[("### BUYER_PRICE($200) ###", "### SELLER_PRICE($200) ###")],
    )
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["agreed_price"] == 200.0

    buyer_share = scorer.score_buyer_surplus_share(terminal=result.terminal)
    seller_share = scorer.score_seller_surplus_share(terminal=result.terminal)

    for envelope in (buyer_share, seller_share):
        assert envelope.status == "invalid_measurement"
        assert envelope.validity.reasons == ("agreed_price_out_of_declared_range",)
        assert envelope.primary is None


# ---- Component parity: our leaves recombine to upstream's own GlobalScore --


def test_surplus_share_leaves_recombine_to_upstream_recorded_global_score_basic_mode() -> None:
    """Our recorded scoring (the two surplus-share leaves, computed by
    measurement.py) equals upstream computed scoring (info["global_score"],
    computed by the real, bridge-executed ``_calculate_global_score``) for
    the identical scripted trajectory, once recombined through upstream's
    own published ``Q = 4 * u_b * u_s`` formula and its actual current
    default weights (D=10, W=80, E=10, gamma=0.99 -- spec section 4).
    """
    case = _case(BASIC_CASE_ID)
    result, scorer = _run(
        case,
        rounds=[
            ("### BUYER_PRICE($90) ###", "### SELLER_PRICE($130) ###"),
            ("### BUYER_PRICE($100) ###", "### SELLER_PRICE($100) ###"),
        ],
    )
    buyer_share = scorer.score_buyer_surplus_share(terminal=result.terminal).primary.value
    seller_share = scorer.score_seller_surplus_share(terminal=result.terminal).primary.value
    quality = 4.0 * buyer_share * seller_share
    discount = 0.99 ** (result.terminal["rounds"] - 1)
    reconstructed_global_score = (10.0 + 80.0 * quality + 10.0) * discount
    assert reconstructed_global_score == pytest.approx(result.terminal["global_score"])


def test_surplus_share_leaves_recombine_to_upstream_recorded_global_score_contract_mode() -> None:
    """Weaker than its basic-mode sibling above: contract-mode ``u_b``/``u_s``
    (``terminal["buyer_utility"]``/``terminal["seller_utility"]``) are
    upstream's own values, carried forward verbatim off ``state.metadata``
    (upstream never stores them for price-only mode, so the basic-mode test
    above recomputes them independently from ``agreed_price`` instead). This
    test therefore multiplies the exact numbers upstream itself just used to
    compute ``GlobalScore`` back through the same disclosed ``Q`` formula, so
    equality holds by construction -- it proves this adapter's own copy of the
    weights/discount/``Q`` formula is correct, not that upstream's own MAUT
    utility calculation (``u_b``, ``u_s``, ``z_max``) is. See spec sections
    5/9: no separate gold oracle exists for contract-mode utilities, so
    replay parity (not this test) is the correctness oracle for those.
    """
    case = _case(REALISTIC_CASE_ID)
    result, scorer = _run(case, rounds=[(_LEGAL_CONTRACT, _LEGAL_CONTRACT)])
    buyer_share = scorer.score_buyer_surplus_share(terminal=result.terminal).primary.value
    seller_share = scorer.score_seller_surplus_share(terminal=result.terminal).primary.value
    quality = 4.0 * buyer_share * seller_share
    discount = 0.99 ** (result.terminal["rounds"] - 1)
    reconstructed_global_score = (10.0 + 80.0 * quality + 10.0) * discount
    assert reconstructed_global_score == pytest.approx(result.terminal["global_score"])
