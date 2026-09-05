"""Tests for the econevals tool surface (tools.py).

Follows the same ``_bridge()``/skip convention as
``tests/test_econevals_environment.py``: pure structural tests (declared
tool sets, effect split, schema shape) run everywhere; tests that actually
execute a tool call through the real ``ToolRuntime``/bridge run for real
when a bridge interpreter is provisioned, and are skipped (never faked)
otherwise.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread.shared_runner.task.execution import EvidenceStore
from aeread.shared_runner.task.tools import ToolRuntime
from aeread.shared_runner.schemas import CaseManifest
from aeread_families.econevals.econevals_bridge import (
    EconevalsBridge,
    EconevalsBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econevals.environment import EconevalsPlugin, TRACK_TOOLS
from aeread_families.econevals.tools import (
    EconevalsToolSession,
    build_tool_bindings,
    build_tool_definitions,
)

CASES_DIR = Path("cases/econevals")

try:
    BRIDGE_PYTHON = discover_bridge_python()
except EconevalsBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> EconevalsBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return EconevalsBridge(python_executable=BRIDGE_PYTHON)


def _case(split: str, case_id: str) -> CaseManifest:
    path = CASES_DIR / split / f"{case_id}.json"
    if not path.is_file():
        pytest.skip(f"no checked-in case found at {path}")
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _evidence(tmp_path: Path, *, name: str = "evidence") -> EvidenceStore:
    return EvidenceStore(
        tmp_path / name,
        run_plan_id="runplan_econevals_tools",
        cell_id="cell_econevals_tools",
        episode_id="episode_econevals_tools",
        episode_attempt_id="attempt_econevals_tools",
    )


# ---------------------------------------------------------------------------
# Structural: declared tool sets / effect split (no bridge, no case files).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("track", ["procurement", "scheduling", "pricing"])
def test_build_tool_definitions_declares_exactly_the_tracks_tool_set(track: str) -> None:
    definitions = build_tool_definitions(track)
    expected_read_only = set(TRACK_TOOLS[track]["read_only"])
    expected_submit = TRACK_TOOLS[track]["submit_tool"]

    assert set(definitions) == expected_read_only | {expected_submit}
    assert definitions[expected_submit].effect == "mutating"
    for name in expected_read_only:
        assert definitions[name].effect == "read_only"


@pytest.mark.parametrize("track", ["procurement", "scheduling", "pricing"])
def test_exactly_one_mutating_tool_per_track(track: str) -> None:
    definitions = build_tool_definitions(track)
    mutating = [name for name, d in definitions.items() if d.effect == "mutating"]
    assert mutating == [TRACK_TOOLS[track]["submit_tool"]]


def test_write_notes_and_read_notes_declare_their_own_argument_schemas() -> None:
    definitions = build_tool_definitions("procurement")
    assert definitions["write_notes"].input_schema["required"] == ("notes",)
    assert definitions["read_notes"].input_schema["required"] == ("attempt_number",)
    # A plain info tool (no arguments) is declared with an empty schema.
    assert definitions["get_budget"].input_schema["properties"] == {}


def test_submit_tool_schema_names_the_tracks_own_argument() -> None:
    definitions = build_tool_definitions("pricing")
    schema = definitions["set_prices"].input_schema
    assert schema["required"] == ("prices_dict_str",)
    assert "prices_dict_str" in schema["properties"]


def test_tool_session_mirrors_initial_state_shape() -> None:
    plugin = EconevalsPlugin(bridge=None)
    family_case = {"track": "pricing", "pins": {"max_steps": 3}}
    initial = plugin.initial_state(family_case, None)

    session = EconevalsToolSession(initial)

    assert session.get_state() == {
        "track": "pricing",
        "period": 0,
        "termination": None,
        "notes": [""],
        "attempts": [],
    }
    assert session.attempts() is session.get_state()["attempts"]


def test_tool_session_advance_period_reaches_max_periods_termination() -> None:
    plugin = EconevalsPlugin(bridge=None)
    family_case = {"track": "pricing", "pins": {"max_steps": 2}}
    session = EconevalsToolSession(plugin.initial_state(family_case, None))

    session.advance_period(family_case)
    assert session.get_state()["period"] == 1
    assert session.get_state()["termination"] is None

    session.advance_period(family_case)
    assert session.get_state()["period"] == 2
    assert session.get_state()["termination"] == "max_periods"


# ---------------------------------------------------------------------------
# Bridge-gated: a real tool call through ToolRuntime.
# ---------------------------------------------------------------------------


def test_read_only_tool_call_through_tool_runtime_returns_the_dispatched_content(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("pricing_basic", "econevals.pricing.basic.0")
    family_case = plugin.validate_payload(case.payload)

    session = EconevalsToolSession(plugin.initial_state(family_case, None))
    bindings = build_tool_bindings(plugin, family_case, session)
    runtime = ToolRuntime(_evidence(tmp_path), bindings)

    result, record = asyncio.run(
        runtime.invoke(
            action_attempt_id="attempt_1",
            tool_id="get_product_ids",
            arguments={},
        )
    )

    assert result == {
        "content": {"product_ids": family_case["generated_instance"]["product_ids"]},
        "error": False,
    }
    assert record.effect == "read_only"
    assert record.status == "succeeded"


def test_submit_tool_call_through_tool_runtime_mutates_the_shared_session(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    plugin = EconevalsPlugin(bridge=bridge)
    case = _case("pricing_basic", "econevals.pricing.basic.0")
    family_case = plugin.validate_payload(case.payload)
    product_ids = family_case["generated_instance"]["product_ids"]

    session = EconevalsToolSession(plugin.initial_state(family_case, None))
    bindings = build_tool_bindings(plugin, family_case, session)
    runtime = ToolRuntime(_evidence(tmp_path), bindings)

    prices = {product_id: 1.0 for product_id in product_ids}
    result, record = asyncio.run(
        runtime.invoke(
            action_attempt_id="attempt_1",
            tool_id="set_prices",
            arguments={"prices_dict_str": prices},
        )
    )

    assert result["error"] is False
    assert result["content"]["prices"] == prices
    assert record.effect == "mutating"
    assert record.state_changed is True
    # The session's own attempt-history list (state_reader) now carries the
    # one recorded attempt -- delegated straight from dispatch_submit, not
    # reimplemented here.
    assert len(session.attempts()) == 1
    assert session.attempts()[0]["prices"] == prices
