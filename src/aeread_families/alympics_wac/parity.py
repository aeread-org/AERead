"""Independent-oracle parity harness for ``alympics.wac.reference_baseline``
(spec section 5's "Parity (required per 'never reimplement')" test plan
bullet; Gate 2 requirement 1: "cross-check deterministic oracles against an
independent implementation").

There is no second, independently-authored implementation of the Water
Allocation Challenge to diff against -- "the independent oracle is
upstream's own code invoked a second, unmodified time outside the kernel's
state machinery, not a reimplementation diffed against itself" (spec
section 5). This module drives that second invocation:

* **adapter**: run ``alympics.wac.reference_baseline`` the real,
  kernel-facing way -- ``AlympicsWacPlugin``/``run_episode`` -- which
  internally calls ``environment._delegate_round`` once per round. Each
  call constructs a *fresh, scratch* upstream ``waterAllocation`` instance,
  seeded from that round's recorded pre-state, so ``step()``'s own kernel
  state stays a plain, freezable dict rather than holding a live upstream
  object graph across the whole episode.
* **upstream_direct_continuous**: build upstream's own ``waterAllocation``
  object exactly **once** and drive its own ``run_single_round`` repeatedly
  across the whole game -- never reconstructed per round, i.e. the shape
  upstream's own ``run_multi_round`` uses (that method itself is not
  reused here, since it also writes a JSON history file to disk as a side
  effect this parity check has no use for -- see
  ``_run_upstream_direct_continuous``'s docstring).

Comparing the two proves the adapter's per-round scratch-instance-plus-
restore-state design (needed so kernel state stays a plain dict the
scheduler can freeze/hash/replay) is behaviorally indistinguishable from
driving one continuous upstream object across the whole episode -- never
that either driver's own arithmetic is "correct" in some abstract sense,
only that they agree, since both ultimately call the identical pinned
``_get_salary``/``_check_winner``/``_round_settlement``/``success_bid``/
``unsuccess_bid`` methods.

Only the reference_baseline case is covered, matching the "for
reference_baseline" scope named in spec section 5's parity test plan
bullet: its policy assignment is all-"proportional", i.e. every seat bids
a fixed ``3 * requirement`` for the whole game (constant, since
"proportional" is a function of a persona's own requirement only, never of
round or balance -- see ``docs/alympics_adapter_spec.md``'s golden 1),
which keeps both drivers' bid-generation trivial and identical by
construction. This module intentionally carries no subprocess/CLI shape:
unlike ``tau3_retail.parity`` (which bridges a *separate* Python process
running a different, newer-Python upstream checkout), alympics.wac has "no
bridge" at all (spec section 1) -- both drivers here run in the same
process, so there is nothing for a standalone CLI entrypoint to reproduce
that a pytest run does not already exercise directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from aeread.shared_runner.analysis.parity import ParityField, ParityReport, ParitySpec, compare_projections
from aeread.shared_runner.run.resolver import PlanCell
from aeread.shared_runner.task.scheduler import run_episode
from aeread.shared_runner.schemas import CaseManifest

from .cases import CASE_ID_PREFIX, SEAT_ORDER
from .environment import AlympicsWacPlugin, SEAT_NAME_BY_ID, _load_upstream

DEFAULT_CASES_DIR = Path("cases/alympics_wac/base")
REFERENCE_BASELINE_CASE_ID = f"{CASE_ID_PREFIX}.reference_baseline"

PARITY_SPEC = ParitySpec(
    parity_id="alympics_wac_reference_baseline_parity",
    parity_version="1.0.0",
    fields=(
        ParityField("final_balance_by_seat", ("final_balance_by_seat",), ("final_balance_by_seat",)),
        ParityField("final_hp_by_seat", ("final_hp_by_seat",), ("final_hp_by_seat",)),
        ParityField("final_no_drink_by_seat", ("final_no_drink_by_seat",), ("final_no_drink_by_seat",)),
        ParityField("winners_by_round", ("winners_by_round",), ("winners_by_round",)),
        ParityField("eliminated_order", ("eliminated_order",), ("eliminated_order",)),
    ),
)

_SEAT_BY_UPSTREAM_NAME: Mapping[str, str] = {
    name: seat for seat, name in SEAT_NAME_BY_ID.items()
}


class ParityRunError(RuntimeError):
    """The reference_baseline case could not be loaded or run at all."""


@dataclass(frozen=True, slots=True)
class ReferenceBaselineParityReport:
    """The parity outcome for the one covered case (spec section 5 scope)."""

    case_id: str
    report: ParityReport
    adapter_projection: Mapping[str, Any]
    upstream_direct_projection: Mapping[str, Any]

    @property
    def matched(self) -> bool:
        return self.report.status == "match"


def _proportional_bid(requirement: int) -> int:
    # Spec's verified golden 1 fact: "proportional" bids exactly 3x a
    # persona's own (fixed) requirement -- never round- or balance-
    # dependent, so this is the one closure both drivers need.
    return 3 * requirement


async def _proportional_response_source(request: Any) -> dict[str, int]:
    requirement = request.observation["requirement"]
    return {"bid": _proportional_bid(requirement)}


def _load_reference_baseline_case(cases_dir: Path) -> CaseManifest:
    path = cases_dir / f"{REFERENCE_BASELINE_CASE_ID}.json"
    if not path.is_file():
        raise ParityRunError(f"no checked-in case file for reference_baseline: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return CaseManifest.from_dict(raw)


def _plan_cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_alympics_wac_parity_reference_baseline",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_alympics_wac_parity",
        suite_version="0.1.0",
        block_id="block_alympics_wac_parity",
        sampling_plan_id="sampling_alympics_wac_parity",
        analysis_plan_id="analysis_alympics_wac_parity",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_alympics_wac_parity_reference_baseline",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {seat: "scripted_proportional" for seat in SEAT_ORDER}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_adapter(upstream_root: Path, cases_dir: Path) -> dict[str, Any]:
    """Run reference_baseline the real, kernel-facing way (spec section 3)."""
    import asyncio

    case = _load_reference_baseline_case(cases_dir)
    plugin = AlympicsWacPlugin(upstream_root=upstream_root)
    cell = _plan_cell(case)
    result = asyncio.run(
        run_episode(
            cell=cell,
            case=case,
            plugin=plugin,
            response_source=_proportional_response_source,
        )
    )
    final_players = result.final_state["players"]
    round_log = result.final_state["round_log"]
    return {
        "final_balance_by_seat": {seat: final_players[seat]["balance"] for seat in SEAT_ORDER},
        "final_hp_by_seat": {seat: final_players[seat]["hp"] for seat in SEAT_ORDER},
        "final_no_drink_by_seat": {seat: final_players[seat]["no_drink"] for seat in SEAT_ORDER},
        "winners_by_round": [list(entry["winners"]) for entry in round_log],
        "eliminated_order": list(result.final_state["eliminated_order"]),
    }


def _run_upstream_direct_continuous(upstream_root: Path, cases_dir: Path) -> dict[str, Any]:
    """Drive ONE continuous upstream ``waterAllocation`` instance directly.

    Never goes through ``AlympicsWacPlugin``/``run_episode``/
    ``_delegate_round``'s scratch-instance-per-round construction. Builds
    the real, pinned upstream object exactly once and calls its own
    ``run_single_round`` repeatedly; each ``LLM.call`` is rebound exactly
    once per player/game (not per round), which is sound only because
    "proportional" bids a fixed ``3 * requirement`` for the whole game --
    see the module docstring.

    Deliberately never calls ``run_multi_round``: that method also writes
    a JSON history file (``f'./{self.experiment_unique_id}.json'``) to the
    current working directory as a side effect this parity check has no
    use for and must not depend on (and the pinned upstream checkout is
    read-only regardless).
    """
    case = _load_reference_baseline_case(cases_dir)
    supply_schedule = case.payload["supply_schedule"]
    wa_module = _load_upstream(upstream_root)
    wa = wa_module.waterAllocation("alympics.wac parity direct-continuous instance")

    captured_winners: list[list[str]] = []
    original_check_winner = type(wa)._check_winner

    def _check_winner_wrapper(supply_arg: int, _orig=original_check_winner, _wa=wa) -> list[str]:
        result = _orig(_wa, supply_arg)
        captured_winners.append(list(result))
        return result

    wa._check_winner = _check_winner_wrapper

    for player in wa.players:
        fixed_bid = _proportional_bid(player.requirement)
        player.llm.call = lambda message, _bid=fixed_bid: str(_bid)  # noqa: ARG005

    def _parse_call(message: Any, _wa: Any = wa) -> str:
        return json.dumps({p.name: _proportional_bid(p.requirement) for p in _wa.players})

    wa.llm.call = _parse_call

    eliminated_order: list[str] = []
    survivors_before = {player.name for player in wa.survival_players}
    terminated_early = False
    for round_id, supply in enumerate(supply_schedule, start=1):
        try:
            wa.run_single_round(round_id, int(supply))
        except SystemExit:
            # Mirrors `_delegate_round`'s own catch (spec section 3): a
            # full wipeout is a real, verified upstream idiom, never
            # allowed to escape and kill the parity/pytest process.
            terminated_early = True
            eliminated_order.extend(
                name for name in SEAT_NAME_BY_ID.values() if name in survivors_before
            )
            break
        survivors_after = {player.name for player in wa.survival_players}
        newly_eliminated = survivors_before - survivors_after
        eliminated_order.extend(
            name for name in SEAT_NAME_BY_ID.values() if name in newly_eliminated
        )
        survivors_before = survivors_after
    del terminated_early

    final_by_name = {player.name: player for player in wa.players}
    return {
        "final_balance_by_seat": {
            _SEAT_BY_UPSTREAM_NAME[name]: player.balance for name, player in final_by_name.items()
        },
        "final_hp_by_seat": {
            _SEAT_BY_UPSTREAM_NAME[name]: player.hp for name, player in final_by_name.items()
        },
        "final_no_drink_by_seat": {
            _SEAT_BY_UPSTREAM_NAME[name]: player.no_drink for name, player in final_by_name.items()
        },
        "winners_by_round": [
            [_SEAT_BY_UPSTREAM_NAME[name] for name in winners] for winners in captured_winners
        ],
        "eliminated_order": [_SEAT_BY_UPSTREAM_NAME[name] for name in eliminated_order],
    }


def run_reference_baseline_parity(
    upstream_root: Path, *, cases_dir: Path = DEFAULT_CASES_DIR
) -> ReferenceBaselineParityReport:
    """Run both drivers on ``reference_baseline`` and compare component-by-component."""
    adapter_projection = _run_adapter(upstream_root, cases_dir)
    upstream_direct_projection = _run_upstream_direct_continuous(upstream_root, cases_dir)
    report = compare_projections(upstream_direct_projection, adapter_projection, PARITY_SPEC)
    return ReferenceBaselineParityReport(
        case_id=REFERENCE_BASELINE_CASE_ID,
        report=report,
        adapter_projection=adapter_projection,
        upstream_direct_projection=upstream_direct_projection,
    )


__all__ = [
    "DEFAULT_CASES_DIR",
    "PARITY_SPEC",
    "REFERENCE_BASELINE_CASE_ID",
    "ParityRunError",
    "ReferenceBaselineParityReport",
    "run_reference_baseline_parity",
]
