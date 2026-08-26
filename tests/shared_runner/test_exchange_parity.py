"""Old path against new path, field by field, on the same case and seed.

This is the safety belt. Everything the kernel does is worthless if the numbers
it produces are not the numbers the legacy runner produced, and "the ratio
looks about right" is not a check. Each case is run twice — once through
`run_v1`, once through the compatibility plugin under `run_episode` — and every
field a scorer or a paper table reads must agree exactly.

Provider-free by construction: the scripted policy decides on both paths.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from aeread.exchange_v1_runner import run_v1
from aeread.exchange_v1_scoring import score_run
from aeread.families.exchange_v1 import (
    EPISODE_PHASE,
    ExchangeCompatibilityError,
    ExchangeV1EnvironmentPlugin,
)
from aeread.runner.episode import run_episode
from aeread.runner.event_store import ArtifactStore, EventStore
from aeread.sdk.v1 import EventIdentity


CASES_V0 = Path("configs/exchange_economy/cases_v0")
CONFIG_ROOT = Path("configs/exchange_economy")

#: The last entry carries a non-zero coordination cost, which is what makes it
#: worth running: cost enters final_net_welfare and therefore w_real, so a case
#: where it is always zero cannot tell a faithful wrapper from a lossy one.
CASES = [
    (CASES_V0 / "case01_visible_bilateral_ir.json", 7),
    (CASES_V0 / "case01_visible_bilateral_ir.json", 11),
    (CASES_V0 / "case02_multiparty_clearing.json", 7),
    (CASES_V0 / "case03_hidden_discovery.json", 7),
    (CASES_V0 / "case04_consent_under_hidden_info.json", 7),
    (
        CONFIG_ROOT
        / "public_solicitation_institution_pressure_anti_anchor_atomic_commit.json",
        7,
    ),
]


def _rows(matrix: Any) -> list[list[int]]:
    return [list(row) for row in matrix]


def _identity(case_id: str, seed: int) -> EventIdentity:
    return EventIdentity(
        run_plan_id=f"parity-{case_id}",
        cell_id=f"{case_id}-s{seed}",
        episode_id="episode-1",
        episode_attempt_id="attempt-1",
    )


def _events(tmp_path: Path, identity: EventIdentity) -> EventStore:
    tmp_path.mkdir(parents=True, exist_ok=True)
    artifacts = ArtifactStore.open(
        tmp_path / "evidence", identity=identity, trusted_root=tmp_path
    )
    return EventStore.open(
        tmp_path / "events.jsonl", artifacts=artifacts, identity=identity
    )


def _through_kernel(config: Path, seed: int, tmp_path: Path) -> Any:
    plugin = ExchangeV1EnvironmentPlugin()
    case = plugin.validate_case(
        {
            "case_id": config.stem.replace("_", "-"),
            "config_path": str(config),
            "seed": seed,
        }
    )
    identity = _identity(config.stem, seed)
    return asyncio.run(
        run_episode(
            environment=plugin,
            case=case,
            cell=None,
            adapters={},
            events=_events(tmp_path, identity),
            identity=identity,
            request_factory=lambda slot, observation: None,
            max_phases=4,
        )
    )


def _through_legacy(config: Path, seed: int) -> tuple[Any, dict[str, Any]]:
    with tempfile.TemporaryDirectory() as out:
        outcome = run_v1(
            str(config),
            mode="offline",
            seed=seed,
            out_root=out,
            quiet=True,
        )
        return outcome.result, score_run(outcome.run_dir)


@pytest.mark.parametrize(("config", "seed"), CASES, ids=lambda v: getattr(v, "stem", v))
def test_the_kernel_reproduces_the_legacy_allocation_and_welfare(
    config: Path, seed: int, tmp_path: Path
) -> None:
    legacy, _ = _through_legacy(config, seed)
    result = _through_kernel(config, seed, tmp_path)

    assert result.status == "terminal"
    assert result.outcome is not None
    new = result.outcome.payload

    # The payload is a frozen JSON object, so rows come back as tuples.
    assert _rows(new["final_allocation"]) == _rows(legacy.final_allocation)
    assert _rows(new["initial_allocation"]) == _rows(legacy.initial_allocation)
    assert new["initial_welfare"] == legacy.initial_welfare
    assert new["final_welfare"] == legacy.final_welfare
    assert new["optimum_welfare"] == legacy.optimum_welfare
    assert new["final_net_welfare"] == legacy.final_net_welfare
    assert new["coordination_cost_total"] == legacy.coordination_cost_total
    assert new["applied_mechanisms"] == legacy.applied_mechanisms
    assert new["rounds"] == len(legacy.history)
    assert new["initial_gini"] == legacy.initial_gini
    assert new["final_gini"] == legacy.final_gini


@pytest.mark.parametrize(("config", "seed"), CASES, ids=lambda v: getattr(v, "stem", v))
def test_the_kernel_reproduces_the_legacy_score_and_denominator_tier(
    config: Path, seed: int, tmp_path: Path
) -> None:
    """The AER contract: raw ratio, preserved sign, declared tier."""

    _, legacy_score = _through_legacy(config, seed)
    result = _through_kernel(config, seed, tmp_path)
    assert result.outcome is not None
    new = result.outcome.payload

    w_real = new["final_net_welfare"] - new["initial_welfare"]
    denominator = max(0.0, new["optimum_welfare"] - new["initial_welfare"])

    assert w_real == pytest.approx(legacy_score["w_real"], abs=0.0)
    assert denominator == pytest.approx(legacy_score["denominator"], abs=0.0)
    if legacy_score["status"] == "ok":
        assert w_real / denominator == pytest.approx(legacy_score["score"], abs=0.0)
    else:
        assert denominator <= 1e-9, "a degenerate denominator must stay degenerate"


def test_a_seed_override_changes_the_case_digest(tmp_path: Path) -> None:
    """Two seeds are two cases, so a receipt cannot confuse them."""

    plugin = ExchangeV1EnvironmentPlugin()
    payload = {
        "case_id": "case01-visible-bilateral-ir",
        "config_path": str(CASES_V0 / "case01_visible_bilateral_ir.json"),
    }
    seven = plugin.validate_case({**payload, "seed": 7})
    eleven = plugin.validate_case({**payload, "seed": 11})
    assert seven.config_sha256 != eleven.config_sha256
    assert seven.seed == 7 and eleven.seed == 11


def test_the_episode_is_recorded_even_though_no_seat_acts(tmp_path: Path) -> None:
    identity = _identity("case01_visible_bilateral_ir", 7)
    events = _events(tmp_path, identity)
    plugin = ExchangeV1EnvironmentPlugin()
    case = plugin.validate_case(
        {
            "case_id": "case01-visible-bilateral-ir",
            "config_path": str(CASES_V0 / "case01_visible_bilateral_ir.json"),
            "seed": 7,
        }
    )
    asyncio.run(
        run_episode(
            environment=plugin,
            case=case,
            cell=None,
            adapters={},
            events=events,
            identity=identity,
            request_factory=lambda slot, observation: None,
            max_phases=4,
        )
    )

    types = [event.event_type for event in events.snapshot().events]
    assert types[0] == "episode_started"
    assert types[-1] == "episode_terminal"
    assert "phase_started" in types and "phase_applied" in types
    # No seat acted, so there is no action evidence to invent.
    assert not [t for t in types if t.startswith("logical_action_")]


def test_the_wrapper_refuses_actions_it_cannot_mean(tmp_path: Path) -> None:
    plugin = ExchangeV1EnvironmentPlugin()
    case = plugin.validate_case(
        {
            "case_id": "case01-visible-bilateral-ir",
            "config_path": str(CASES_V0 / "case01_visible_bilateral_ir.json"),
            "seed": 7,
        }
    )
    state = plugin.initial_state(case, None)
    phase = plugin.phase_graph(case).phases[0]

    with pytest.raises(ExchangeCompatibilityError, match="no seat actions"):
        plugin.step(case, state, phase, {"slot": object()})  # type: ignore[dict-item]

    ran = plugin.step(case, state, phase, {}).state
    with pytest.raises(ExchangeCompatibilityError, match="already ran"):
        plugin.step(case, ran, phase, {})


def test_running_twice_gives_byte_identical_outcomes(tmp_path: Path) -> None:
    """Determinism on the new path, independent of the legacy comparison."""

    first = _through_kernel(CASES_V0 / "case01_visible_bilateral_ir.json", 7, tmp_path / "a")
    second = _through_kernel(CASES_V0 / "case01_visible_bilateral_ir.json", 7, tmp_path / "b")
    assert first.outcome is not None and second.outcome is not None
    assert dict(first.outcome.payload) == dict(second.outcome.payload)
