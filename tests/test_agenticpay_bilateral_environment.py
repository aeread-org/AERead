"""Provider-free scheduler coverage for the agenticpay.bilateral environment plugin.

Milestone 1 scope ("cases + environment"): these tests exercise
``AgenticpayBilateralPlugin`` through the real kernel scheduler
(``run_episode``) end to end, using a small scripted response source
defined in this test module (not a shipped ``harness.py`` -- that scripted-
policy test harness is out of this milestone's scope, see
``environment.py``'s module docstring). No measurement leaf is asserted
here (``measurement.py`` does not exist yet): every fact this module checks
comes straight off ``EpisodeResult.terminal``/``.outcome``, which are
upstream's own ``info`` dict fields carried forward verbatim.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.registry import REQUIRED_FAMILY_PLUGIN_HOOKS, PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import DecisionRequest, run_episode
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


def _case(case_id: str) -> CaseManifest:
    split = case_id.split(".")[2]
    path = Path("cases/agenticpay_bilateral") / split / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_agenticpay_bilateral_environment",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_agenticpay_bilateral_environment",
        suite_version="0.1.0",
        block_id="block_agenticpay_bilateral_environment",
        sampling_plan_id="sampling_agenticpay_bilateral_environment",
        analysis_plan_id="analysis_agenticpay_bilateral_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_agenticpay_bilateral_environment",
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

    ``rounds`` is ``[(buyer_message, seller_message), ...]``; round *i*'s
    buyer message answers the buyer-turn decision request, and that same
    round's seller message answers the following seller-turn request.
    Raises if the episode asks for more rounds than were scripted (an
    exhausted script is a test-authoring bug, not a silent pass).
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


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)
    registry = PluginRegistry()
    manifest = family_manifest()
    registered = register_plugin(registry, plugin=plugin)

    assert registered is plugin
    assert registry.resolve_manifest(manifest) is plugin
    assert set(REQUIRED_FAMILY_PLUGIN_HOOKS) == {
        name for name in REQUIRED_FAMILY_PLUGIN_HOOKS if callable(getattr(plugin, name, None))
    }
    family_case = json.loads(canonical_json_bytes(_case("agenticpay.bilateral.basic.task1").payload))
    phases = plugin.phases(family_case)
    assert [(phase.phase_id, phase.mode, phase.next_phases) for phase in phases] == [
        (BUYER_PHASE, "single", (SELLER_PHASE,)),
        (SELLER_PHASE, "single", (BUYER_PHASE,)),
    ]


def test_build_scorer_raises_until_measurement_py_lands() -> None:
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)
    family_case = json.loads(canonical_json_bytes(_case("agenticpay.bilateral.basic.task1").payload))
    with pytest.raises(NotImplementedError):
        plugin.build_scorer(family_case)


def test_validate_payload_accepts_the_checked_in_basic_case() -> None:
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)
    case = _case("agenticpay.bilateral.basic.task1")
    family_case = plugin.validate_payload(case.payload)
    assert family_case["env_class"] == "Task1BasicPriceNegotiation"


def test_validate_payload_rejects_a_tampered_provenance_hash() -> None:
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)
    case = _case("agenticpay.bilateral.basic.task1")
    tampered = json.loads(canonical_json_bytes(case.payload))
    tampered["provenance_files"]["env_source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256 mismatch"):
        plugin.validate_payload(tampered)


def test_bridge_runtime_is_offline_and_loaded_from_the_pinned_checkout() -> None:
    runtime = _bridge().runtime_info()
    assert runtime["python_version"].startswith("3.11.")
    assert Path(runtime["agenticpay_package_file"]).resolve().is_relative_to(
        (UPSTREAM_ROOT / "agenticpay").resolve()
    )


def _run(case: CaseManifest, rounds: list[tuple[str, str]]):
    bridge = _bridge()
    cell = _cell(case)
    plugin = AgenticpayBilateralPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    scripted = _ScriptedNegotiation(rounds)
    return asyncio.run(
        run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=scripted)
    )


# ---------------------------------------------------------------------------
# Golden 1 -- successful basic negotiation (spec section 4).
# ---------------------------------------------------------------------------


def test_golden_successful_negotiation_converges_and_matches_upstream_global_score() -> None:
    case = _case("agenticpay.bilateral.basic.task1")
    # This case's declared prices (buyer_max=150, seller_min=80,
    # initial_seller=150) differ from the spec's illustrative golden
    # (120/80/120); the assertions below hand-derive the expected values for
    # *this* case's own Z=70 rather than re-asserting the spec's own numbers
    # verbatim, since the checked-in case is the real, pinned Task1 driver
    # script's declared prices, not an invented fixture.
    result = _run(
        case,
        rounds=[
            ("### BUYER_PRICE($90) ###", "### SELLER_PRICE($130) ###"),
            ("### BUYER_PRICE($100) ###", "### SELLER_PRICE($100) ###"),
        ],
    )
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["agreed_price"] == 100.0
    assert result.terminal["rounds"] == 2
    z = 150.0 - 80.0
    u_b = (150.0 - 100.0) / z
    u_s = (100.0 - 80.0) / z
    quality = 4.0 * u_b * u_s
    discount = 0.99**1
    expected_global_score = (10.0 + 80.0 * quality + 10.0) * discount
    assert result.terminal["global_score"] == pytest.approx(expected_global_score)
    assert result.outcome["agreed_price"] == 100.0
    assert result.outcome["global_score"] == pytest.approx(expected_global_score)


# ---------------------------------------------------------------------------
# Golden 5 -- degenerate reference (Z <= 0), spec section 4.
# ---------------------------------------------------------------------------


def test_golden_degenerate_reference_still_agrees_but_reports_failure_penalty() -> None:
    # Task2 (close-price) has buyer_max=85 > seller_min=80 in the checked-in
    # case, so Z > 0 there; the spec's golden 5 needs buyer_max < seller_min,
    # which no checked-in case declares. Build a minimal, explicitly labeled
    # variant of the pinned Task1 case's payload with only the two price
    # fields flipped, matching the spec's degenerate scenario exactly.
    base = _case("agenticpay.bilateral.basic.task1")
    degenerate_payload = json.loads(canonical_json_bytes(base.payload))
    degenerate_payload["constructor_kwargs"]["buyer_max_price"] = 90.0
    degenerate_payload["constructor_kwargs"]["seller_min_price"] = 100.0
    degenerate_payload["constructor_kwargs"]["initial_seller_price"] = 100.0
    degenerate_payload["constructor_kwargs"]["price_tolerance"] = 1.0
    degenerate_case = CaseManifest.from_dict(
        {
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
    )
    from aeread.shared_runner.resolver import case_content_sha256

    digest = case_content_sha256(
        {**json.loads(canonical_json_bytes(degenerate_case)), "content_sha256": "0" * 64}
    )
    degenerate_case = CaseManifest.from_dict(
        {**json.loads(canonical_json_bytes(degenerate_case)), "content_sha256": digest}
    )

    result = _run(degenerate_case, rounds=[("### BUYER_PRICE($95) ###", "### SELLER_PRICE($95) ###")])
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["agreed_price"] == 95.0
    assert result.terminal["global_score"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Realistic (contract-mode) case -- exercises environment_info.contract_config
# and the boolean-discrete-key restoration path end to end.
# ---------------------------------------------------------------------------


def test_realistic_contract_mode_case_runs_end_to_end_and_agrees() -> None:
    # Terms and price chosen to land on this scenario's own MAUT-optimal
    # discrete combination (the one z_max is computed against) with price at
    # the exact midpoint of the two sides' resulting utility range, so both
    # u_b and u_s land safely positive (u_b == u_s == 0.5 * z_max) --
    # verified end to end against the pinned checkout via the bridge before
    # writing this assertion, not guessed at. An arbitrary "reasonable-
    # looking" contract (e.g. "30_days"/"protective" here) can legitimately
    # make one side's utility negative for this scenario's declared
    # preference weights, which upstream itself then reports as a
    # (correctly) unscored contract, not a bug.
    case = _case("agenticpay.bilateral.realistic.s01_beauty_product")
    contract = (
        '<contract>{"price": 5.39, "continuous_terms": {"delivery_days": 1}, '
        '"discrete_terms": {"return_policy": "none", "packaging": "protective", '
        '"user_product_preference": "strong_match"}}</contract>'
    )
    result = _run(case, rounds=[(contract, contract)])
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["agreed_contract"] is not None
    assert result.terminal["buyer_utility"] == pytest.approx(0.6)
    assert result.terminal["seller_utility"] == pytest.approx(0.6)
    assert result.terminal["global_score"] == pytest.approx(100.0)


def test_realistic_food_delivery_boolean_discrete_term_reaches_a_real_utility() -> None:
    # s16_food_delivery_1's contract has a boolean-valued discrete term
    # (extra_condiments); this proves the importer's "true"/"false" string
    # coercion and the bridge driver's restoration to real Python bool
    # round-trip correctly end to end, not just in isolation (see
    # test_agenticpay_bilateral_cases.py's own narrower unit test). Terms
    # and price are this scenario's own MAUT-optimal combination at its
    # midpoint price, same rationale as the beauty-product golden above.
    case = _case("agenticpay.bilateral.realistic.s16_food_delivery_1")
    contract = (
        '<contract>{"price": 7.885, "continuous_terms": {}, '
        '"discrete_terms": {"delivery_speed": "batched", "extra_condiments": true, '
        '"user_product_preference": "strong_match"}}</contract>'
    )
    result = _run(case, rounds=[(contract, contract)])
    assert result.terminal["reason"] == "agreed"
    assert result.terminal["buyer_utility"] == pytest.approx(2.265)
    assert result.terminal["seller_utility"] == pytest.approx(2.265)
    assert result.terminal["global_score"] == pytest.approx(100.0)
