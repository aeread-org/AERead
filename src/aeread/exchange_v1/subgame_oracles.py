"""Offline subgame-style extraction and local oracles for exchange traces.

This module deliberately scores local gamelets, not whole trajectories. Extracted
episodes from different traces are path-selected and should be compared only
through matched frontier ratios or stratified summaries.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class SubgameEpisode:
    trace_id: str
    round_index: int
    decision_index: int
    episode_type: str
    oracle_kind: str
    actor_id: Optional[int]
    participants: tuple[int, ...]
    applied: bool
    accepted: bool
    actual_gain: float
    matched_frontier_gain: float
    oracle_gap: float
    frontier_ratio: Optional[float]
    comparable_key: tuple[str, str, str, str]
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participants"] = list(self.participants)
        payload["comparable_key"] = list(self.comparable_key)
        return payload


def load_trace_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load an exchange trace JSONL file."""

    records: list[dict[str, Any]] = []
    with Path(path).open() as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))
    return records


def extract_subgame_episodes(
    records: Iterable[dict[str, Any]],
    *,
    trace_id: str = "",
) -> list[SubgameEpisode]:
    """Extract typed local gamelets and simple matched-oracle scores.

    Current oracle coverage:
    - same-proposal IR oracle for executable bilateral/multiparty mechanisms;
    - utility-delta oracle for private acceptance;
    - detector episodes for public solicitation and public-rule updates;
    - repeated-dyad reuse episodes when a pair trades again later in a trace.
    """

    episodes: list[SubgameEpisode] = []
    seen_pairs: set[tuple[int, int]] = set()
    trace_id = trace_id or "trace"

    for decision_index, row in enumerate(records, start=1):
        event = row.get("event") or {}
        mechanism = _mechanism_from_row(row)
        transfers = list(mechanism.get("transfers") or [])
        participants = _participants_from_transfers(transfers)
        round_index = _int(row.get("round_index"), default=decision_index)
        controller_id = _optional_int(row.get("controller_id"))
        applied = bool(event.get("applied", False))
        accepted = bool(event.get("accepted", False))
        summary = str(event.get("message") or mechanism.get("summary") or event.get("kind") or "")

        if _has_public_solicitation(row):
            episodes.append(
                _episode(
                    trace_id=trace_id,
                    round_index=round_index,
                    decision_index=decision_index,
                    episode_type="hidden_or_public_solicitation",
                    oracle_kind="solicitation_detector",
                    actor_id=controller_id,
                    participants=participants,
                    applied=applied,
                    accepted=accepted,
                    actual_gain=0.0,
                    matched_frontier_gain=0.0,
                    summary=summary,
                )
            )

        if transfers and len(participants) >= 2:
            episode_type = "bilateral_offer" if len(participants) == 2 else "multiparty_clearing"
            actual_gain, frontier_gain = _same_proposal_ir_gains(event, participants, applied)
            episodes.append(
                _episode(
                    trace_id=trace_id,
                    round_index=round_index,
                    decision_index=decision_index,
                    episode_type=episode_type,
                    oracle_kind="same_proposal_ir_oracle",
                    actor_id=controller_id,
                    participants=participants,
                    applied=applied,
                    accepted=accepted,
                    actual_gain=actual_gain,
                    matched_frontier_gain=frontier_gain,
                    summary=summary,
                )
            )

            if len(participants) == 2:
                pair = tuple(participants)
                if pair in seen_pairs:
                    episodes.append(
                        _episode(
                            trace_id=trace_id,
                            round_index=round_index,
                            decision_index=decision_index,
                            episode_type="repeated_dyad_reuse",
                            oracle_kind="same_pair_reuse_oracle",
                            actor_id=controller_id,
                            participants=participants,
                            applied=applied,
                            accepted=accepted,
                            actual_gain=actual_gain,
                            matched_frontier_gain=frontier_gain,
                            summary=summary,
                        )
                    )
                seen_pairs.add(pair)

        elif _looks_like_multiparty_negotiation(row):
            episodes.append(
                _episode(
                    trace_id=trace_id,
                    round_index=round_index,
                    decision_index=decision_index,
                    episode_type="multiparty_negotiation",
                    oracle_kind="no_executable_settlement_oracle",
                    actor_id=controller_id,
                    participants=participants,
                    applied=applied,
                    accepted=accepted,
                    actual_gain=0.0,
                    matched_frontier_gain=0.0,
                    summary=summary,
                )
            )
        elif _looks_like_bilateral_negotiation(row):
            episodes.append(
                _episode(
                    trace_id=trace_id,
                    round_index=round_index,
                    decision_index=decision_index,
                    episode_type="bilateral_negotiation",
                    oracle_kind="no_executable_settlement_oracle",
                    actor_id=controller_id,
                    participants=participants,
                    applied=applied,
                    accepted=accepted,
                    actual_gain=0.0,
                    matched_frontier_gain=0.0,
                    summary=summary,
                )
            )

        if _institutional_updates(row):
            actual_gain, frontier_gain = _same_proposal_ir_gains(event, participants, applied)
            episodes.append(
                _episode(
                    trace_id=trace_id,
                    round_index=round_index,
                    decision_index=decision_index,
                    episode_type="public_rule_update",
                    oracle_kind="public_rule_update_detector",
                    actor_id=controller_id,
                    participants=participants,
                    applied=applied,
                    accepted=accepted,
                    actual_gain=actual_gain,
                    matched_frontier_gain=frontier_gain,
                    summary=summary,
                )
            )

        for audit in event.get("private_acceptance_audits") or []:
            delta = _float(audit.get("actual_delta"), default=0.0)
            approve = bool(audit.get("approve", False))
            actual_gain = delta if approve else 0.0
            frontier_gain = max(0.0, delta)
            actor_id = _optional_int(audit.get("agent_id"))
            episodes.append(
                _episode(
                    trace_id=trace_id,
                    round_index=round_index,
                    decision_index=decision_index,
                    episode_type="private_acceptance",
                    oracle_kind="utility_delta_acceptance_oracle",
                    actor_id=actor_id,
                    participants=(actor_id,) if actor_id is not None else (),
                    applied=applied,
                    accepted=accepted,
                    actual_gain=actual_gain,
                    matched_frontier_gain=frontier_gain,
                    summary=str(audit.get("reason") or audit.get("error_family") or summary),
                )
            )

    return episodes


def summarize_subgame_episodes(episodes: Iterable[SubgameEpisode]) -> dict[str, Any]:
    by_type: dict[str, dict[str, Any]] = {}
    total_count = 0
    for ep in episodes:
        total_count += 1
        bucket = by_type.setdefault(
            ep.episode_type,
            {
                "count": 0,
                "actual_gain": 0.0,
                "matched_frontier_gain": 0.0,
                "oracle_gap": 0.0,
                "applied": 0,
            },
        )
        bucket["count"] += 1
        bucket["actual_gain"] += ep.actual_gain
        bucket["matched_frontier_gain"] += ep.matched_frontier_gain
        bucket["oracle_gap"] += ep.oracle_gap
        bucket["applied"] += 1 if ep.applied else 0

    for bucket in by_type.values():
        frontier = bucket["matched_frontier_gain"]
        bucket["frontier_ratio"] = None if frontier <= 1e-12 else bucket["actual_gain"] / frontier

    return {"episode_count": total_count, "by_type": by_type}


def summarize_d_dimensions(episodes: Iterable[SubgameEpisode]) -> dict[str, Any]:
    """Aggregate extracted gamelets into the D1-D5 capability ontology.

    This is a trace-level diagnostic overlay, not a theorem. D1 and D2 currently
    use observable proxies: disclosure/solicitation surfaces and formed positive
    proposal opportunities. D3-D5 use matched local frontier ratios where the
    extracted gamelet has an explicit local oracle.
    """

    eps = list(episodes)
    disclosure_eps = [
        ep for ep in eps
        if ep.episode_type in {"hidden_or_public_solicitation", "bilateral_negotiation", "multiparty_negotiation"}
    ]
    proposal_eps = [
        ep for ep in eps
        if ep.episode_type in {"bilateral_offer", "multiparty_clearing"}
    ]
    positive_proposals = [ep for ep in proposal_eps if ep.matched_frontier_gain > 1e-12]
    acceptance_eps = [ep for ep in eps if ep.episode_type == "private_acceptance"]
    reuse_eps = [
        ep for ep in eps
        if ep.episode_type in {"public_rule_update", "repeated_dyad_reuse"}
    ]

    d1_count = len(disclosure_eps)
    opportunities_formed = len(positive_proposals)
    return {
        "D1_sender_disclosure": {
            "count": d1_count,
            "description": "observable disclosure, solicitation, or negotiation surfaces",
        },
        "D2_receiver_inference": {
            "opportunities_formed": opportunities_formed,
            "opportunity_per_disclosure": None if d1_count == 0 else opportunities_formed / d1_count,
            "description": "proxy: positive executable opportunities formed after disclosure surfaces",
        },
        "D3_executable_proposal": {
            **_aggregate_dimension(proposal_eps),
            "description": "local same-proposal IR frontier over bilateral and multiparty compiled bundles",
        },
        "D4_settlement_evaluation": {
            **_aggregate_dimension(acceptance_eps),
            "description": "utility-delta acceptance oracle over private acceptance decisions",
        },
        "D5_reuse_continuation": {
            **_aggregate_dimension(reuse_eps),
            "description": "public-rule-update and repeated-dyad reuse local frontiers",
        },
    }


def _aggregate_dimension(episodes: Iterable[SubgameEpisode]) -> dict[str, Any]:
    eps = list(episodes)
    actual = sum(ep.actual_gain for ep in eps)
    frontier = sum(ep.matched_frontier_gain for ep in eps)
    gap = sum(ep.oracle_gap for ep in eps)
    nontrivial = sum(1 for ep in eps if ep.matched_frontier_gain > 1e-12)
    solved = sum(
        1 for ep in eps
        if ep.matched_frontier_gain > 1e-12
        and ep.frontier_ratio is not None
        and ep.frontier_ratio >= 1.0 - 1e-9
    )
    return {
        "count": len(eps),
        "nontrivial_count": nontrivial,
        "solved_count": solved,
        "actual_gain": actual,
        "matched_frontier_gain": frontier,
        "oracle_gap": gap,
        "frontier_ratio": None if frontier <= 1e-12 else actual / frontier,
    }


def _episode(
    *,
    trace_id: str,
    round_index: int,
    decision_index: int,
    episode_type: str,
    oracle_kind: str,
    actor_id: Optional[int],
    participants: Iterable[int],
    applied: bool,
    accepted: bool,
    actual_gain: float,
    matched_frontier_gain: float,
    summary: str,
) -> SubgameEpisode:
    participants_tuple = tuple(sorted({int(p) for p in participants if p is not None}))
    oracle_gap = max(0.0, matched_frontier_gain - actual_gain)
    frontier_ratio = None if matched_frontier_gain <= 1e-12 else actual_gain / matched_frontier_gain
    comparable_key = (
        episode_type,
        oracle_kind,
        f"n{len(participants_tuple)}",
        "positive_frontier" if matched_frontier_gain > 1e-12 else "zero_frontier",
    )
    return SubgameEpisode(
        trace_id=trace_id,
        round_index=round_index,
        decision_index=decision_index,
        episode_type=episode_type,
        oracle_kind=oracle_kind,
        actor_id=actor_id,
        participants=participants_tuple,
        applied=applied,
        accepted=accepted,
        actual_gain=float(actual_gain),
        matched_frontier_gain=float(matched_frontier_gain),
        oracle_gap=float(oracle_gap),
        frontier_ratio=frontier_ratio,
        comparable_key=comparable_key,
        summary=summary,
    )


def _same_proposal_ir_gains(
    event: dict[str, Any],
    participants: Iterable[int],
    applied: bool,
) -> tuple[float, float]:
    deltas = _agent_deltas(event)
    participants_tuple = tuple(participants)
    participant_deltas = [deltas.get(pid, 0.0) for pid in participants_tuple]
    proposed_gain = sum(participant_deltas)
    ir_valid = bool(participant_deltas) and min(participant_deltas) >= -1e-12
    frontier_gain = proposed_gain if ir_valid else 0.0
    actual_gain = proposed_gain if applied and ir_valid else 0.0
    return float(actual_gain), float(max(0.0, frontier_gain))


def _mechanism_from_row(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("verified_before_private_acceptance", "verified_mechanism", "compiled_mechanism"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _participants_from_transfers(transfers: Iterable[dict[str, Any]]) -> tuple[int, ...]:
    ids: set[int] = set()
    for transfer in transfers:
        from_id = _optional_int(transfer.get("from"))
        to_id = _optional_int(transfer.get("to"))
        if from_id is not None:
            ids.add(from_id)
        if to_id is not None:
            ids.add(to_id)
    return tuple(sorted(ids))


def _agent_deltas(event: dict[str, Any]) -> dict[int, float]:
    raw = event.get("agent_deltas") or {}
    result: dict[int, float] = {}
    for key, value in raw.items():
        agent_id = _optional_int(key)
        if agent_id is not None:
            result[agent_id] = _float(value, default=0.0)
    return result


def _institutional_updates(row: dict[str, Any]) -> list[Any]:
    updates: list[Any] = []
    event = row.get("event") or {}
    mechanism = _mechanism_from_row(row)
    for value in (mechanism.get("institutional_updates"), event.get("institutional_updates")):
        if isinstance(value, list):
            updates.extend(value)
    return updates


def _has_public_solicitation(row: dict[str, Any]) -> bool:
    text = _all_text(row).lower()
    return any(marker in text for marker in ("all agents", "any agent", "everyone", "publicly solicit"))


def _looks_like_multiparty_negotiation(row: dict[str, Any]) -> bool:
    text = _all_text(row).lower()
    return any(marker in text for marker in ("three-way", "three way", "multi-party", "multi party", "multiway", "multi-way"))


def _looks_like_bilateral_negotiation(row: dict[str, Any]) -> bool:
    text = _all_text(row).lower()
    return "bilateral" in text or "direct trade" in text or "direct swap" in text


def _all_text(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("proposal_text") or ""),
        str(row.get("final_text") or ""),
    ]
    for key in ("communication_texts", "response_texts"):
        value = row.get(key)
        if isinstance(value, dict):
            parts.extend(str(v) for v in value.values())
    event = row.get("event") or {}
    parts.append(str(event.get("message") or ""))
    parts.append(str(event.get("kind") or ""))
    return "\n".join(parts)


def _optional_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        match = re.fullmatch(r"a?(\d+)", str(value).strip())
        return int(match.group(1)) if match else None


def _int(value: Any, *, default: int) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _float(value: Any, *, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace_jsonl", help="Exchange trace JSONL to parse")
    parser.add_argument("--episodes", action="store_true", help="Print JSONL episodes instead of summary")
    parser.add_argument("--dimensions", action="store_true", help="Print D1-D5 capability summary")
    args = parser.parse_args(argv)

    path = Path(args.trace_jsonl)
    episodes = extract_subgame_episodes(load_trace_jsonl(path), trace_id=str(path))
    if args.episodes:
        for episode in episodes:
            print(json.dumps(episode.to_dict(), sort_keys=True))
    elif args.dimensions:
        print(json.dumps(summarize_d_dimensions(episodes), indent=2, sort_keys=True))
    else:
        print(json.dumps(summarize_subgame_episodes(episodes), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
