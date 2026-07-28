"""D1b arena acceptance filters: the offline, provider-free admission gate.

Decides which arena configs are non-trivial enough to enter the case set,
per the v1 contract's D1b bullets: absolute-threshold rejections (no meaningful
surplus, no IR-safe path, excessive random/greedy capture, insufficient greedy
floor, excessive hidden-knowledge gap, search-cost domination), the
random < greedy < heuristic < info-oracle ordering with per-inequality failure
records, capability-pressure tags, and stored accept/reject decisions -- all
computed before any LLM call. Never mutates config files.

Ordering gate modes:
- "discriminating" (default): random < greedy strict, zero inversions, and
  info-oracle strictly above greedy (headroom over the memoryless script).
  Ties at one tier are allowed -- single-pressure ladder rungs tie by design.
- "strict": the literal 4-tier strict chain.

Usage:
    python sprint/exchange_v1_filters.py --from-manifest \
        --output-json docs/exchange_economy/v1_filter_decisions.json \
        --output-md docs/exchange_economy/v1_filter_decisions.md
    python sprint/exchange_v1_filters.py --configs 'configs/exchange_economy/cand_*.json' --gate
    python sprint/exchange_v1_filters.py --paired control.json treatment.json --conceptual-knob public_broadcast
"""
from __future__ import annotations

import argparse
import glob
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

try:  # Supports both `python sprint/exchange_v1_filters.py` and `python -m sprint.exchange_v1_filters`.
    from aeread import exchange_economy as ex
    from aeread import exchange_v1_baselines as baselines
    from aeread import exchange_v1_validity as validity
except ModuleNotFoundError:  # pragma: no cover - exercised by module execution.
    from . import exchange_economy as ex
    from . import exchange_v1_baselines as baselines
    from . import exchange_v1_validity as validity


# Rejection-reason vocabulary, verbatim from the v1 contract's D1b bullet.
REASON_NO_SURPLUS = "no meaningful surplus"
REASON_NO_IR_SAFE_PATH = "no IR-safe path"
REASON_RANDOM_CAPTURE = "excessive random capture"
REASON_GREEDY_CAPTURE = "excessive greedy capture"
REASON_GREEDY_FLOOR = "insufficient greedy floor"
REASON_HIDDEN_GAP = "excessive hidden-knowledge gap"
REASON_SEARCH_COST = "search costs dominate reachable gain"
REASON_ORDERING = "ordering requirement failed"


@dataclass(frozen=True)
class FilterThresholds:
    min_meaningful_surplus: float = 1e-6
    require_ir_safe_path: bool = True
    max_random_capture_ratio: float = 0.5
    max_greedy_capture_ratio: float = 0.95
    min_greedy_floor_ratio: float = 0.02
    max_hidden_gap_ratio: float = 0.98


@dataclass(frozen=True)
class ArenaFilterDecision:
    config_name: str
    config_path: str
    sha256: str
    accepted: bool
    rejection_reasons: list[str]
    ordering_mode: str
    ordering_holds: bool
    failed_inequalities: list[str]
    ties: list[str]
    inversions: list[str]
    capability_pressure_tags: list[str]
    baselines: baselines.BaselineRecord
    thresholds: FilterThresholds
    llm_calls: int = 0


def worst_case_episode_search_cost(config: ex.ExchangeExperimentConfig) -> float:
    """Upper-bound coordination cost over the episode, from the pressure knobs.

    Mirrors apply_institutional_costs' two bases: per-contacted-agent when that
    rate is set (bounded by contacting everyone), otherwise the flat public-round
    basis. Standing-rule savings are ignored (worst case: no institutions exist).
    """
    pressure = config.institution_pressure
    if pressure.search_cost_per_contacted_agent:
        per_round = pressure.search_cost_per_contacted_agent * (config.num_agents - 1)
    else:
        per_round = pressure.search_cost_per_public_round * config.num_agents
    return per_round * config.rounds


def capability_pressure_tags(
    config: ex.ExchangeExperimentConfig,
    record: baselines.BaselineRecord,
) -> list[str]:
    protocol = config.protocol
    pressure = config.institution_pressure
    tags = []
    if protocol.visibility_mode == "full_public":
        tags.append("bilateral_visible")
    if protocol.partial_clearing or (protocol.settlement_row_limit or 0) > 2:
        tags.append("multiparty_composition")
    if protocol.visibility_mode == "limited_contact" and record.hidden_discovery_gain > 1e-9:
        tags.append("hidden_discovery")
    if protocol.response_scope == "solicited_public":
        tags.append("public_solicitation")
    if pressure.recurring_demand_mode != "none":
        tags.append("repeated_reuse")
    if (
        pressure.search_cost_per_public_round
        or pressure.search_cost_per_contacted_agent
        or pressure.contact_expansion_cost
    ):
        tags.append("search_cost")
    if pressure.standing_rule_bonus_or_cost_saving:
        tags.append("institution_continuation")
    if protocol.defection_rate > 0:
        tags.append("adversarial")
    return tags


def evaluate_arena(
    config: ex.ExchangeExperimentConfig,
    record: baselines.BaselineRecord,
    *,
    thresholds: Optional[FilterThresholds] = None,
    strict: bool = False,
) -> ArenaFilterDecision:
    """Pure admission decision over pre-computed baselines. No LLM, no oracle calls."""
    thresholds = thresholds or FilterThresholds()
    reasons: list[str] = []
    info_gain = record.information_constrained_gain

    if info_gain <= thresholds.min_meaningful_surplus:
        reasons.append(REASON_NO_SURPLUS)
    if thresholds.require_ir_safe_path and record.greedy_gain <= 0 and record.greedy_applied_rounds == 0:
        reasons.append(REASON_NO_IR_SAFE_PATH)
    if info_gain > 0:
        if record.random_mean_gain / info_gain > thresholds.max_random_capture_ratio:
            reasons.append(REASON_RANDOM_CAPTURE)
        greedy_ratio = record.greedy_gain / info_gain
        if greedy_ratio > thresholds.max_greedy_capture_ratio:
            reasons.append(REASON_GREEDY_CAPTURE)
        if greedy_ratio < thresholds.min_greedy_floor_ratio:
            reasons.append(REASON_GREEDY_FLOOR)
        if record.hidden_discovery_gain / info_gain > thresholds.max_hidden_gap_ratio:
            reasons.append(REASON_HIDDEN_GAP)
    worst_case_search = worst_case_episode_search_cost(config)
    if worst_case_search > 0 and worst_case_search >= info_gain:
        reasons.append(REASON_SEARCH_COST)

    ties, inversions = baselines.classify_ordering(record)
    failed = ties + inversions
    if strict:
        ordering_holds = not failed
    else:
        random_lt_greedy = record.ordering["random_lt_greedy"].passed
        info_above_greedy = info_gain > record.greedy_gain + 1e-9
        ordering_holds = random_lt_greedy and not inversions and info_above_greedy
    if not ordering_holds:
        reasons.append(REASON_ORDERING)

    return ArenaFilterDecision(
        config_name=record.config_name,
        config_path=record.config_path,
        sha256=record.sha256,
        accepted=not reasons,
        rejection_reasons=reasons,
        ordering_mode="strict" if strict else "discriminating",
        ordering_holds=ordering_holds,
        failed_inequalities=failed,
        ties=ties,
        inversions=inversions,
        capability_pressure_tags=capability_pressure_tags(config, record),
        baselines=record,
        thresholds=thresholds,
    )


def evaluate_config_path(
    config_path: str | Path,
    *,
    thresholds: Optional[FilterThresholds] = None,
    strict: bool = False,
    rounds: Optional[int] = None,
    random_samples: int = 5,
    random_seed: int = 0,
) -> ArenaFilterDecision:
    """Candidate path: compute baselines (oracle work happens here), then filter."""
    config = ex.load_experiment_config(config_path)
    record = baselines.compute_baselines(
        config_path, rounds=rounds, random_samples=random_samples, random_seed=random_seed,
    )
    return evaluate_arena(config, record, thresholds=thresholds, strict=strict)


def evaluate_frozen_manifest(
    manifest_path: str | Path = baselines.DEFAULT_MANIFEST_PATH,
    *,
    thresholds: Optional[FilterThresholds] = None,
    strict: bool = False,
) -> list[ArenaFilterDecision]:
    """Frozen-set path: reuse the manifest's stored baselines, zero oracle calls."""
    decisions = []
    for record in baselines.records_from_manifest(manifest_path):
        config = ex.load_experiment_config(record.config_path)
        decisions.append(evaluate_arena(config, record, thresholds=thresholds, strict=strict))
    return decisions


def paired_ablation_check(
    control_path: str | Path,
    treatment_path: str | Path,
    *,
    conceptual_knob: str,
    allowed_diffs: Optional[set[str]] = None,
) -> validity.PairedAblationCheck:
    """Single-knob treatment-claim support (delegates to the validity engine)."""
    return validity.compare_paired_ablation_configs(
        ex.load_experiment_config(control_path),
        ex.load_experiment_config(treatment_path),
        conceptual_knob=conceptual_knob,
        allowed_diffs=allowed_diffs,
    )


def decisions_to_markdown(decisions: list[ArenaFilterDecision]) -> str:
    mode = decisions[0].ordering_mode if decisions else "discriminating"
    lines = [
        "# V1 arena admission decisions (D1b acceptance filters)",
        "",
        f"Provider-free admission gate over baseline denominators (ordering mode: `{mode}`).",
        "Rejected arenas stay frozen/available for diagnostics -- rejection only means the",
        "config does not enter the discriminating case set.",
        "",
        "| config | decision | rejection reasons | ties | inversions | capability pressure |",
        "|---|---|---|---|---|---|",
    ]
    for d in decisions:
        lines.append(
            f"| {d.config_name} | {'ACCEPT' if d.accepted else 'reject'} "
            f"| {'; '.join(d.rejection_reasons) or '-'} "
            f"| {', '.join(d.ties) or '-'} | {', '.join(d.inversions) or '-'} "
            f"| {', '.join(d.capability_pressure_tags) or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _add_threshold_flags(parser: argparse.ArgumentParser) -> None:
    defaults = FilterThresholds()
    parser.add_argument("--min-meaningful-surplus", type=float, default=defaults.min_meaningful_surplus)
    parser.add_argument("--max-random-capture-ratio", type=float, default=defaults.max_random_capture_ratio)
    parser.add_argument("--max-greedy-capture-ratio", type=float, default=defaults.max_greedy_capture_ratio)
    parser.add_argument("--min-greedy-floor-ratio", type=float, default=defaults.min_greedy_floor_ratio)
    parser.add_argument("--max-hidden-gap-ratio", type=float, default=defaults.max_hidden_gap_ratio)
    parser.add_argument("--no-ir-safe-path-check", action="store_true")


def _thresholds_from_args(args: argparse.Namespace) -> FilterThresholds:
    return FilterThresholds(
        min_meaningful_surplus=args.min_meaningful_surplus,
        require_ir_safe_path=not args.no_ir_safe_path_check,
        max_random_capture_ratio=args.max_random_capture_ratio,
        max_greedy_capture_ratio=args.max_greedy_capture_ratio,
        min_greedy_floor_ratio=args.min_greedy_floor_ratio,
        max_hidden_gap_ratio=args.max_hidden_gap_ratio,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="D1b arena acceptance filters (provider-free admission gate)")
    parser.add_argument("--from-manifest", action="store_true",
                        help="filter the frozen set using the manifest's stored baselines (no oracle calls)")
    parser.add_argument("--manifest", default=str(baselines.DEFAULT_MANIFEST_PATH))
    parser.add_argument("--configs", default=None, help="glob of candidate configs (computes baselines)")
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--random-samples", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--strict", action="store_true", help="literal 4-tier strict ordering gate")
    parser.add_argument("--gate", action="store_true", help="exit 1 if any config is rejected")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    parser.add_argument("--paired", nargs=2, metavar=("CONTROL", "TREATMENT"),
                        help="single-knob paired-ablation check instead of admission filtering")
    parser.add_argument("--conceptual-knob", default=None)
    parser.add_argument("--allowed-diffs", default=None, help="comma-separated flattened field names")
    _add_threshold_flags(parser)
    args = parser.parse_args()

    if args.paired:
        if not args.conceptual_knob:
            parser.error("--paired requires --conceptual-knob")
        allowed = set(args.allowed_diffs.split(",")) if args.allowed_diffs else None
        result = paired_ablation_check(
            args.paired[0], args.paired[1],
            conceptual_knob=args.conceptual_knob, allowed_diffs=allowed,
        )
        print(json.dumps(asdict(result), indent=2))
        return 0 if result.passed else 1

    thresholds = _thresholds_from_args(args)
    if args.from_manifest:
        decisions = evaluate_frozen_manifest(args.manifest, thresholds=thresholds, strict=args.strict)
    elif args.configs:
        paths = sorted(p for p in glob.glob(args.configs) if not p.endswith("v1_manifest.json"))
        if not paths:
            print(f"no configs matched: {args.configs}")
            return 1
        decisions = [
            evaluate_config_path(
                p, thresholds=thresholds, strict=args.strict,
                rounds=args.rounds, random_samples=args.random_samples, random_seed=args.random_seed,
            )
            for p in paths
        ]
    else:
        parser.error("pass --from-manifest, --configs, or --paired")

    markdown = decisions_to_markdown(decisions)
    print(markdown)
    if args.output_md:
        Path(args.output_md).write_text(markdown)
    if args.output_json:
        Path(args.output_json).write_text(json.dumps([asdict(d) for d in decisions], indent=2) + "\n")

    rejected = [d for d in decisions if not d.accepted]
    if args.gate and rejected:
        print(f"GATE: {len(rejected)} config(s) rejected")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
