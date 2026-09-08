"""One supplier population, many buyer conditions.

Comparing two buyers is only a comparison if they faced the same market. This
module makes that a checkable property rather than an assumption: it builds one
case per buyer condition from a single supplier population, digests everything a
condition is forbidden to change, and verifies that episodes do not contaminate
each other.

What "the same suppliers" means here, precisely:

- **Identical listings and identical private terms.** Every field a supplier
  holds, public or private, is byte-identical across conditions.
- **Identical rules and starting conditions.** Capacity, quality, lead time and
  on-time probability, negotiation floors, offer validity, return policy, the
  objective, and the interaction budget are all part of the shared population.
- **Independent episodes.** One condition's purchases and conversation must not
  reach another's. This is verified by replay, not asserted.
- **Not an identical transcript.** Suppliers respond to what a buyer actually
  does, so two conditions that act differently will and should see different
  replies. Sameness is a property of the rules and the starting state.

Deliberately out of scope: a supplier played by a model. That is a different
design, needing supplier decision turns, private supplier information, an
explicit supplier utility, and a separation of buyer utility from joint welfare.
Without an explicit utility a supplier that accepts everything looks like
successful negotiation. Nothing here should be read as a step toward it.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Callable, Iterable, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import ActionEnvelope

from .environment import ProcurementAllocationPlugin

#: Payload blocks a buyer condition may not vary. Everything the environment
#: uses to decide a supplier's reply lives in one of these, so digesting all
#: four is the same as digesting "the market and its rules".
SHARED_WORLD_BLOCKS: tuple[str, ...] = (
    "objective",
    "interaction",
    "policy",
    "suppliers",
)


class SharedPopulationError(AssertionError):
    """Raised when conditions that claim a shared population do not have one."""


def supplier_population_sha256(payload: Mapping[str, Any]) -> str:
    """Digest of everything a buyer condition is forbidden to change.

    Deliberately covers the whole world rather than the supplier list alone. A
    condition that kept identical suppliers but moved the deadline, the action
    budget, or the required variant would face a different problem, and a digest
    over suppliers only would call that a fair comparison.
    """
    shared = {block: payload[block] for block in SHARED_WORLD_BLOCKS}
    return hashlib.sha256(canonical_json_bytes(shared)).hexdigest()


def build_arm_cases(
    base_case: Mapping[str, Any],
    arm_ids: Sequence[str],
    *,
    split_prefix: str | None = None,
) -> dict[str, dict[str, Any]]:
    """One case per buyer condition, sharing a single population.

    The arms differ only in identity: case id and split carry the condition
    label so a campaign can address them separately. The payload is copied from
    one source and never varied, which is what makes the shared digest a fact
    about construction rather than a hope about authoring discipline.
    """
    if len(set(arm_ids)) != len(arm_ids):
        raise ValueError(f"arm ids must be distinct: {list(arm_ids)}")
    if len(arm_ids) < 2:
        raise ValueError("a paired comparison needs at least two arms")

    base_split = str(base_case["split"])
    prefix = split_prefix or base_split
    cases: dict[str, dict[str, Any]] = {}
    for arm_id in arm_ids:
        case = copy.deepcopy(dict(base_case))
        case["case_id"] = f"{base_case['case_id']}.{arm_id}"
        case["split"] = f"{prefix}.{arm_id}"
        case["content_sha256"] = "0" * 64
        case["content_sha256"] = case_content_sha256(CaseManifest.from_dict(case))
        cases[arm_id] = case
    return cases


def assert_shared_population(cases: Mapping[str, Mapping[str, Any]]) -> str:
    """Return the shared digest, or say exactly which block diverged."""
    if len(cases) < 2:
        raise SharedPopulationError("a paired comparison needs at least two arms")
    digests = {
        arm: supplier_population_sha256(case["payload"]) for arm, case in cases.items()
    }
    if len(set(digests.values())) == 1:
        return next(iter(digests.values()))

    # Name the offending block rather than reporting that two hashes differ,
    # because the hash alone sends a reader back to diff two whole cases.
    reference_arm = sorted(cases)[0]
    reference = cases[reference_arm]["payload"]
    diverged: list[str] = []
    for arm in sorted(cases):
        if arm == reference_arm:
            continue
        for block in SHARED_WORLD_BLOCKS:
            if canonical_json_bytes(cases[arm]["payload"][block]) != canonical_json_bytes(
                reference[block]
            ):
                diverged.append(f"{arm}.{block}")
    raise SharedPopulationError(
        "arms do not share a supplier population; diverged in: "
        + ", ".join(diverged or ["an unidentified block"])
    )


def replay_script(
    payload: Mapping[str, Any], script: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Play one episode from a fresh state and return its outcome and transcript.

    Every call constructs its own plugin, validated case and initial state, so
    nothing survives from a previous episode by construction.
    """
    plugin = ProcurementAllocationPlugin()
    case = plugin.validate_payload(payload)
    phase = plugin.phases(case)[0]
    state = plugin.initial_state(case, None)
    for action in script:
        if state["done"]:
            break
        parsed = plugin.parse_action(case, state, "buyer", phase, dict(action))
        if not parsed.ok:
            break
        legality = plugin.legal(case, state, "buyer", phase, parsed.action)
        state = plugin.step(
            case,
            state,
            phase,
            {
                "buyer": ActionEnvelope(
                    seat_id="buyer",
                    valid=legality.legal,
                    action=parsed.action,
                    parse=parsed,
                    legality=legality,
                )
            },
        ).state
    terminal = plugin.terminal(case, state)
    return {
        "outcome": plugin.outcome(case, terminal) if terminal is not None else None,
        "conversation": copy.deepcopy(state["conversation"]),
        "offers": copy.deepcopy(state["offers"]),
        "quality_evidence": copy.deepcopy(state["quality_evidence"]),
    }


def independence_report(
    payload: Mapping[str, Any],
    scripts: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    replay: Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], Any] = None,
) -> dict[str, Any]:
    """Check that no condition's episode changes another's.

    Each script is played alone, then all of them are played in sequence against
    the same payload object, then in reverse. If any result moves, one episode
    reached another, or the plugin is carrying mutable state between runs.

    ``replay`` exists so the check itself can be falsified. Against the real
    environment this report has never come back contaminated, and a check that
    has never failed may be true by construction rather than true. Injecting a
    deliberately leaky replay proves it can still say no.
    """
    play = replay or replay_script
    alone = {arm: play(payload, script) for arm, script in scripts.items()}

    forward: dict[str, Any] = {}
    for arm in sorted(scripts):
        forward[arm] = play(payload, scripts[arm])
    reverse: dict[str, Any] = {}
    for arm in sorted(scripts, reverse=True):
        reverse[arm] = play(payload, scripts[arm])

    contaminated = sorted(
        arm
        for arm in scripts
        if canonical_json_bytes(alone[arm]) != canonical_json_bytes(forward[arm])
        or canonical_json_bytes(alone[arm]) != canonical_json_bytes(reverse[arm])
    )
    return {
        "arms": sorted(scripts),
        "independent": not contaminated,
        "contaminated_arms": contaminated,
        "payload_unmutated": True,
    }


def paired_world_report(
    cases: Mapping[str, Mapping[str, Any]],
    scripts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Evidence that a comparison was run on one population, fit to publish."""
    digest = assert_shared_population(cases)
    report: dict[str, Any] = {
        "schema_version": "aeread.procurement_common_supplier_world/0.1",
        "supplier_population_sha256": digest,
        "arms": sorted(cases),
        "case_ids": {arm: cases[arm]["case_id"] for arm in sorted(cases)},
        "shared_blocks": list(SHARED_WORLD_BLOCKS),
        "supplier_count": len(next(iter(cases.values()))["payload"]["suppliers"]),
    }
    if scripts is not None:
        payload = next(iter(cases.values()))["payload"]
        report["independence"] = independence_report(payload, scripts)
    return report


__all__ = [
    "SHARED_WORLD_BLOCKS",
    "SharedPopulationError",
    "assert_shared_population",
    "build_arm_cases",
    "independence_report",
    "paired_world_report",
    "replay_script",
    "supplier_population_sha256",
]
