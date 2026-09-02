"""Provider-free scheduler coverage for the amazonbarg environment plugin.

Runs the five QC Gate-2 goldens from
``docs/amazonbarg_adapter_spec.md`` section 4 through the real kernel
scheduler (``run_episode``), scripted end to end -- no model, no network,
no tool calls (this benchmark has no tool-calling surface at all).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType

import pytest

from aeread.shared_runner.registry import (
    REQUIRED_FAMILY_PLUGIN_HOOKS,
    PluginRegistry,
)
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread.shared_runner.scheduler import DecisionRequest, SchedulerContractError, run_episode
from aeread_families.amazonbarg import cases as amazonbarg_cases
from aeread_families.amazonbarg import measurement as amazonbarg_measurement
from aeread_families.amazonbarg.environment import (
    BUYER_PHASE,
    SELLER_PHASE,
    AmazonbargPlugin,
    family_manifest,
    register_plugin,
)


def _upstream_root() -> Path:
    """The pinned upstream checkout path -- may not exist on disk.

    Unlike this function's pre-fix form, this never skips at import time
    (codex-review finding 6): a missing checkout is caught per-test by
    ``conftest.py``'s ``pytest_collection_modifyitems`` hook instead, which
    skips only the tests that actually need it -- tests marked
    ``@pytest.mark.no_upstream_checkout_required`` (verified independently to
    touch no upstream bytes) still run and pass even when this path does not
    exist.
    """
    candidate = os.environ.get(
        "AEREAD_AMAZONBARG_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg",
    )
    return Path(candidate)


UPSTREAM_ROOT = _upstream_root()
CASES_DIR = Path("cases/amazonbarg/pilot")


def _case(codename: str) -> CaseManifest:
    case_id = amazonbarg_cases.case_id_for_codename(codename)
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
        suite_id="suite_amazonbarg_environment",
        suite_version="0.1.0",
        block_id="block_amazonbarg_environment",
        sampling_plan_id="sampling_amazonbarg_environment",
        analysis_plan_id="analysis_amazonbarg_environment",
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

    Not a production harness (that is a later milestone) -- just enough to
    exercise the real kernel scheduler (``run_episode``) end to end for
    this milestone's environment tests. Asserts every incoming request
    matches the next scripted ``(phase_id, seat_id)`` pair before replying.
    """

    def __init__(self, script: list[tuple[str, str, str]]) -> None:
        self._script = list(script)
        self._index = 0
        self.requests: list[DecisionRequest] = []

    async def __call__(self, request: DecisionRequest) -> dict[str, str]:
        assert self._index < len(self._script), "script exhausted before episode terminated"
        expected_phase, expected_seat, content = self._script[self._index]
        assert request.phase_id == expected_phase
        assert request.seat_id == expected_seat
        self._index += 1
        self.requests.append(request)
        return {"content": content}

    @property
    def exhausted(self) -> bool:
        return self._index == len(self._script)


def _run(case: CaseManifest, script: list[tuple[str, str, str]]):
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    scripted = _ScriptedReplies(script)
    result = asyncio.run(
        run_episode(
            cell=_cell(case),
            case=case,
            plugin=resolved_plugin,
            response_source=scripted,
        )
    )
    return result, scripted


# ---------------------------------------------------------------------------
# Registration and phase-graph shape.
# ---------------------------------------------------------------------------


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    manifest = family_manifest()
    registered = register_plugin(registry, plugin=plugin)

    assert registered is plugin
    assert registry.resolve_manifest(manifest) is plugin
    assert set(REQUIRED_FAMILY_PLUGIN_HOOKS) == {
        name
        for name in REQUIRED_FAMILY_PLUGIN_HOOKS
        if callable(getattr(plugin, name, None))
    }

    case = _case("home-kitchen_2")
    family_case = plugin.validate_payload(case.payload)
    phases = plugin.phases(family_case)
    assert [(phase.phase_id, phase.mode, phase.next_phases) for phase in phases] == [
        (BUYER_PHASE, "single", (SELLER_PHASE,)),
        (SELLER_PHASE, "single", (BUYER_PHASE,)),
    ]


def test_build_scorer_returns_the_five_declared_measurement_leaves() -> None:
    """Milestone 2: ``build_scorer`` is wired to ``measurement.py`` for real.

    See ``tests/test_amazonbarg_measurement.py`` for the five leaves'
    declaration rules and the QC Gate-2 golden scoring tests themselves;
    this only proves the plugin hook returns the same leaves
    ``measurement.build_scorer`` does, mirroring
    ``tau3_retail``'s own ``test_plugin_build_scorer_hook_returns_the_same
    _leaves_as_measurement_py``.
    """
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    family_case = plugin.validate_payload(case.payload)

    scorer = plugin.build_scorer(family_case)

    expected = amazonbarg_measurement.build_leaves(family_case)
    assert tuple(leaf.leaf_id for leaf in scorer.leaves) == tuple(
        leaf.leaf_id for leaf in expected
    )
    assert len(scorer.leaves) == 5


# ---------------------------------------------------------------------------
# validate_payload.
# ---------------------------------------------------------------------------


def test_validate_payload_accepts_every_real_pilot_case() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    for path in sorted(CASES_DIR.glob("amazonbarg.bilateral.*.json")):
        if path.name == "pilot_manifest.json":
            continue
        case = CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        family_case = plugin.validate_payload(case.payload)
        assert family_case["derived"]["codename"] == case.upstream_task_id


def test_validate_payload_rejects_a_tampered_product_record() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    payload = json.loads(canonical_json_bytes(case.payload))
    payload["product"]["title"] = "not the real title"
    with pytest.raises(ValueError, match="does not exactly match"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_the_wrong_upstream_commit() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    payload = json.loads(canonical_json_bytes(case.payload))
    payload["pins"]["upstream_commit"] = "0" * 40
    with pytest.raises(ValueError, match="wrong upstream commit"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_a_budget_that_is_not_price_times_ratio() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    payload = json.loads(canonical_json_bytes(case.payload))
    payload["derived"]["budget"] = payload["derived"]["price"]
    with pytest.raises(ValueError, match="budget is not price"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_an_interest_label_inconsistent_with_cost_budget() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")  # a real mutual-interest session
    payload = json.loads(canonical_json_bytes(case.payload))
    payload["derived"]["interest"] = "conflicting"
    with pytest.raises(ValueError, match="expected 'mutual'"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_missing_top_level_keys() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    payload = json.loads(canonical_json_bytes(case.payload))
    del payload["pins"]
    with pytest.raises(ValueError, match="exactly product, derived, and pins"):
        plugin.validate_payload(payload)


def test_validate_payload_rejects_an_upstream_checkout_edited_in_place(tmp_path: Path) -> None:
    """Codex-review finding 1: the runtime pin must verify the actual bytes at
    ``upstream_root``, not only the payload's own ``pins.upstream_commit`` string.

    A payload's declared pin is untouched by an operator editing the on-disk
    checkout in place (e.g. widening upstream's own ``eval.py:Metrics.evaluate``);
    without this check, ``validate_payload`` would pass and every downstream
    delegated import/score would silently run the tampered source.
    """
    import shutil

    dirty_root = tmp_path / "upstream"
    shutil.copytree(UPSTREAM_ROOT, dirty_root)
    eval_path = dirty_root / "eval.py"
    eval_path.write_text(
        eval_path.read_text(encoding="utf-8") + "\n# tampered in place\n", encoding="utf-8"
    )

    plugin = AmazonbargPlugin(upstream_root=dirty_root)
    case = _case("home-kitchen_2")
    with pytest.raises(ValueError, match="must be clean at the pinned revision"):
        plugin.validate_payload(case.payload)


def test_validate_payload_rejects_an_upstream_checkout_at_the_wrong_revision(
    tmp_path: Path,
) -> None:
    """Codex-review finding 1: a checkout whose actual git HEAD does not equal
    ``UPSTREAM_COMMIT`` must be rejected even if it is otherwise byte-identical
    and even if the payload's own declared pin string is (still) correct."""
    import shutil
    import subprocess

    other_root = tmp_path / "upstream"
    shutil.copytree(UPSTREAM_ROOT, other_root)
    subprocess.run(
        ["git", "-C", str(other_root), "commit", "--allow-empty", "-m", "not the pinned commit"],
        check=True,
        capture_output=True,
    )

    plugin = AmazonbargPlugin(upstream_root=other_root)
    case = _case("home-kitchen_2")
    with pytest.raises(ValueError, match="checkout revision mismatch"):
        plugin.validate_payload(case.payload)


# ---------------------------------------------------------------------------
# QC Gate-2 goldens (spec section 4), run through the real scheduler.
# ---------------------------------------------------------------------------


def test_golden_1_successful_deal_shark_vacuum() -> None:
    case = _case("home-kitchen_2")
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: hi\nAction: [BUY] $120 (1x home-kitchen_2)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: ok\nAction: [SELL] $150 (1x home-kitchen_2)"),
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: deal?\nAction: [BUY] $135 (1x home-kitchen_2)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: yes\nAction: [DEAL] $135 (1x home-kitchen_2)"),
    ]
    result, scripted = _run(case, script)

    assert scripted.exhausted
    assert result.terminal["reason"] == "deal"
    assert result.terminal["terminating_actor"] == "seller"
    assert result.outcome["termination_reason"] == "deal"
    assert result.logical_action_count == 4
    assert [instance.phase_id for instance in result.phase_instances] == [
        BUYER_PHASE,
        SELLER_PHASE,
        BUYER_PHASE,
        SELLER_PHASE,
    ]
    history = result.final_state["history"]
    assert len(history) == 2
    assert [record["role"] for record in history[0]] == ["buyer", "seller"]
    assert history[1][1]["action"] == "[DEAL] $135 (1x home-kitchen_2)"


def test_golden_2_valid_but_poor_deal_calphalon() -> None:
    case = _case("home-kitchen_3")
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: hi\nAction: [BUY] $61 (1x home-kitchen_3)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: ok\nAction: [DEAL] $61.5 (1x home-kitchen_3)"),
    ]
    result, scripted = _run(case, script)

    assert scripted.exhausted
    assert result.terminal["reason"] == "deal"
    assert result.terminal["terminating_actor"] == "seller"
    last_action = result.final_state["history"][-1][-1]["action"]
    assert last_action == "[DEAL] $61.5 (1x home-kitchen_3)"


def test_golden_3_invalid_unauthorized_below_cost_deal_breville() -> None:
    """Environment-level half of golden 3 only: no live economic legality.

    Spec section 4 golden 3's full point -- a below-cost ``DEAL`` that
    upstream's own ``eval.py:Metrics`` authentication (``wrongAction``)
    calls legitimate while AERead's own added ``amazonbarg_zopa_membership``
    catches it -- is a *scoring* claim that belongs to the milestone-2
    scorer test suite, which will exercise the spec's exact scripted
    ``SELL $480 -> BUY $480 -> DEAL $480`` trajectory against delegated
    ``eval.Metrics`` directly. This milestone's environment has no
    legality/authentication logic at all (governing fact: "no economic
    legality live"), so this test only proves the phase graph *lets* a
    below-cost deal happen and records it faithfully -- using a plain
    buyer-opens/seller-deals trajectory, not the exact literal script.
    """
    case = _case("home-kitchen_5")
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: low\nAction: [BUY] $480 (1x home-kitchen_5)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: fine\nAction: [DEAL] $480 (1x home-kitchen_5)"),
    ]
    result, scripted = _run(case, script)

    assert scripted.exhausted
    assert result.terminal["reason"] == "deal"
    derived = case.payload["derived"]
    assert 480 < derived["cost"]  # the deal price is below cost -- legal here, illegal at scoring
    last_action = result.final_state["history"][-1][-1]["action"]
    assert last_action == "[DEAL] $480 (1x home-kitchen_5)"


def test_golden_4_malformed_operational_missing_action_line_bean_bag() -> None:
    case = _case("home-kitchen_4")
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: no action line here"),
    ]
    result, scripted = _run(case, script)

    assert scripted.exhausted
    assert result.terminal["reason"] == "action_error"
    assert result.terminal["terminating_actor"] == "buyer"
    assert result.terminal["turns_completed"] == 0
    assert len(result.final_state["history"]) == 1
    assert len(result.final_state["history"][0]) == 1
    assert result.final_state["history"][0][0]["action"] == ""


def test_golden_5_degenerate_reference_dji_drone_quits() -> None:
    case = _case("toys-games_22")
    derived = case.payload["derived"]
    assert derived["cost"] > derived["budget"]  # the pilot's one CI session
    script = [
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: hi\nAction: [BUY] $850 (1x toys-games_22)"),
        (SELLER_PHASE, "seller", "Thought: t\nTalk: no\nAction: [REJECT]"),
        (BUYER_PHASE, "buyer", "Thought: t\nTalk: bye\nAction: [QUIT]"),
    ]
    result, scripted = _run(case, script)

    assert scripted.exhausted
    assert result.terminal["reason"] == "quit"
    assert result.terminal["terminating_actor"] == "buyer"
    assert result.terminal["turns_completed"] == 1


# ---------------------------------------------------------------------------
# Turn-limit path (no golden names this explicitly, but the phase graph and
# episode.max_logical_actions both depend on it terminating correctly).
# ---------------------------------------------------------------------------


def test_turn_limit_terminates_after_max_turns_with_no_deal_or_quit() -> None:
    case = _case("home-kitchen_2")
    script: list[tuple[str, str, str]] = []
    for turn in range(amazonbarg_cases.MAX_TURNS):
        script.append(
            (BUYER_PHASE, "buyer", f"Thought: t\nTalk: offer {turn}\nAction: [BUY] $100 (1x home-kitchen_2)")
        )
        script.append(
            (SELLER_PHASE, "seller", f"Thought: t\nTalk: counter {turn}\nAction: [SELL] $160 (1x home-kitchen_2)")
        )
    result, scripted = _run(case, script)

    assert scripted.exhausted
    assert result.terminal["reason"] == "turn_limit"
    assert result.terminal["terminating_actor"] is None
    assert result.terminal["turns_completed"] == amazonbarg_cases.MAX_TURNS
    assert result.logical_action_count == 2 * amazonbarg_cases.MAX_TURNS


# ---------------------------------------------------------------------------
# Phase-graph contract: buyer always first, strict alternation, no tools.
# ---------------------------------------------------------------------------


def test_eligible_actors_are_exactly_one_seat_per_phase() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, cell=None)
    buyer_phase, seller_phase = plugin.phases(family_case)

    assert plugin.eligible_actors(family_case, state, buyer_phase) == ("buyer",)
    assert plugin.eligible_actors(family_case, state, seller_phase) == ("seller",)


@pytest.mark.no_upstream_checkout_required
def test_family_manifest_declares_no_tools_and_no_sandbox() -> None:
    manifest = family_manifest()
    assert manifest.environment.needs_tools is False
    assert manifest.environment.needs_sandbox is False
    assert manifest.environment.phase_specs == (BUYER_PHASE, SELLER_PHASE)


def test_empty_reply_content_fails_to_parse_like_upstreams_own_guard() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, cell=None)
    buyer_phase, _seller_phase = plugin.phases(family_case)

    result = plugin.parse_action(family_case, state, "buyer", buyer_phase, {"content": ""})
    assert result.ok is False
    assert result.error_code == "empty_reply"


def test_a_non_deal_non_quit_reply_never_terminates_the_episode() -> None:
    plugin = AmazonbargPlugin(upstream_root=UPSTREAM_ROOT)
    case = _case("home-kitchen_2")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, cell=None)
    buyer_phase, _seller_phase = plugin.phases(family_case)

    parsed = plugin.parse_action(
        family_case, state, "buyer", buyer_phase, {"content": "Thought: t\nTalk: hi\nAction: [BUY] $1 (1x home-kitchen_2)"}
    )
    assert parsed.ok is True
    from aeread.shared_runner.scheduler import ActionEnvelope

    legality = plugin.legal(family_case, state, "buyer", buyer_phase, parsed.action)
    envelope = ActionEnvelope(seat_id="buyer", valid=True, action=parsed.action, parse=parsed, legality=legality)
    transition = plugin.step(family_case, state, buyer_phase, {"buyer": envelope})
    assert transition.next_phase_id == SELLER_PHASE
    assert plugin.terminal(family_case, transition.state) is None
