"""Offline validity checks for v1 exchange-economy configs.

This module is deliberately deterministic and provider-free. It answers two
questions before any LLM run:

1. Is a proposed treatment pair a clean paired ablation?
2. Does the paired environment have the baseline/oracle ordering expected from a
   useful benchmark?
"""
from __future__ import annotations

import argparse
import json
import random
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from . import economy as ex


PUBLIC_SOLICITATION_ALLOWED_DIFFS = {
    "name",
    "description",
    "protocol.name",
    "protocol.public_broadcast",
    "protocol.response_scope",
}


@dataclass(frozen=True)
class PairedAblationCheck:
    conceptual_knob: str
    passed: bool
    expected_diffs: dict[str, tuple[Any, Any]]
    unexpected_diffs: dict[str, tuple[Any, Any]]
    shared_fields: dict[str, Any]


@dataclass(frozen=True)
class ValidityInequality:
    left_metric: str
    right_metric: str
    left_value: float
    right_value: float
    passed: bool


@dataclass(frozen=True)
class ConfigValidityResult:
    config_name: str
    rounds: int
    no_op_gain: float
    random_mean_gain: float
    greedy_gain: float
    stronger_heuristic_gain: float
    information_constrained_gain: float
    hidden_discovery_gain: float
    greedy_applied_rounds: int
    stronger_heuristic_applied_rounds: int
    information_constrained_applied_rounds: int


@dataclass(frozen=True)
class PairedValidityReport:
    control: ConfigValidityResult
    treatment: ConfigValidityResult
    paired_ablation: PairedAblationCheck
    environment_ordering: dict[str, ValidityInequality]
    rounds: int
    random_samples: int
    random_seed: int
    llm_calls: int = 0

    @property
    def passed(self) -> bool:
        return self.paired_ablation.passed and all(item.passed for item in self.environment_ordering.values())


@dataclass(frozen=True)
class PublicSolicitationRoundTrace:
    round_index: int
    controller_id: int
    visible_agents: list[int]
    response_agents: list[int]
    hidden_responders: list[int]
    public_solicitation_activated: bool
    hidden_responder_used_in_proposal: bool
    applied: bool
    applied_with_hidden_responder: bool


@dataclass(frozen=True)
class PublicSolicitationTraceSummary:
    trace_path: str
    config_name: str
    rounds: int
    public_solicitation_activated_rounds: int
    hidden_responder_rounds: int
    hidden_responder_count: int
    hidden_responder_used_in_proposal_rounds: int
    applied_trades: int
    applied_trades_with_hidden_responders: int
    round_traces: list[PublicSolicitationRoundTrace]


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten(child, child_prefix))
        return out
    return {prefix: value}


def compare_paired_ablation_configs(
    control: ex.ExchangeExperimentConfig,
    treatment: ex.ExchangeExperimentConfig,
    *,
    conceptual_knob: str,
    allowed_diffs: set[str] | None = None,
) -> PairedAblationCheck:
    """Check that two configs differ only by one conceptual treatment knob."""
    allowed = allowed_diffs or PUBLIC_SOLICITATION_ALLOWED_DIFFS
    left = _flatten(control)
    right = _flatten(treatment)
    expected: dict[str, tuple[Any, Any]] = {}
    unexpected: dict[str, tuple[Any, Any]] = {}
    shared: dict[str, Any] = {}
    for key in sorted(set(left) | set(right)):
        pair = (left.get(key), right.get(key))
        if pair[0] == pair[1]:
            shared[key] = pair[0]
        elif key in allowed:
            expected[key] = pair
        else:
            unexpected[key] = pair
    return PairedAblationCheck(
        conceptual_knob=conceptual_knob,
        passed=not unexpected,
        expected_diffs=expected,
        unexpected_diffs=unexpected,
        shared_fields=shared,
    )


def _agent_ids_from_mapping_keys(value: Any) -> list[int]:
    if not isinstance(value, dict):
        return []
    ids: list[int] = []
    for key in value:
        match = re.search(r"(\d+)", str(key))
        if match:
            ids.append(int(match.group(1)))
    return sorted(set(ids))


def _agent_ids_mentioned_in_text(text: str) -> set[int]:
    out: set[int] = set()
    for match in re.finditer(r"\ba(?:gent)?\s*(\d+)\b", text, flags=re.IGNORECASE):
        out.add(int(match.group(1)))
    return out


def _agent_id_from_transfer_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else None


def _transfer_agent_ids(mechanism: Any) -> set[int]:
    if not isinstance(mechanism, dict):
        return set()
    transfers = mechanism.get("transfers") or []
    if not isinstance(transfers, list):
        return set()
    out: set[int] = set()
    for transfer in transfers:
        if not isinstance(transfer, dict):
            continue
        for key in ("from", "from_agent", "to", "to_agent"):
            aid = _agent_id_from_transfer_value(transfer.get(key))
            if aid is not None:
                out.add(aid)
    return out


def summarize_public_solicitation_trace(
    trace_jsonl_path: str | Path,
    config_path: str | Path,
) -> PublicSolicitationTraceSummary:
    """Summarize whether a live trace used the public discovery affordance.

    This is a read-only posthoc diagnostic. It uses the run config only to
    reconstruct visible contacts, then checks the saved transcript for public
    solicitation activation, hidden responses, and whether hidden responders
    were converted into proposed/applied settlement rows.
    """
    trace_path = Path(trace_jsonl_path)
    config = ex.load_experiment_config(config_path)
    world = ex.make_world_from_config(config)
    round_traces: list[PublicSolicitationRoundTrace] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        round_index = int(row.get("round_index") or 0)
        controller_id = int(row.get("controller_id") or 0)
        visible = ex.visible_agents_for(config.protocol, world, controller_id)
        response_agents = _agent_ids_from_mapping_keys(row.get("response_texts"))
        hidden_responders = sorted(set(response_agents) - set(visible))
        communication_texts = row.get("communication_texts")
        if not isinstance(communication_texts, dict):
            communication_texts = {}
        proposal_text = str(row.get("proposal_text") or "")
        activated = ex._has_functional_public_solicitation(
            communication_texts,
            controller_id=controller_id,
            proposal_text=proposal_text,
        )
        proposal_agents = _agent_ids_mentioned_in_text(proposal_text)
        transfer_agents = set()
        for field in ("verified_before_private_acceptance", "verified_mechanism", "compiled_mechanism"):
            transfer_agents.update(_transfer_agent_ids(row.get(field)))
        hidden_set = set(hidden_responders)
        hidden_used = bool(hidden_set & (proposal_agents | transfer_agents))
        event = row.get("event") if isinstance(row.get("event"), dict) else {}
        applied = bool(event.get("applied"))
        round_traces.append(
            PublicSolicitationRoundTrace(
                round_index=round_index,
                controller_id=controller_id,
                visible_agents=visible,
                response_agents=response_agents,
                hidden_responders=hidden_responders,
                public_solicitation_activated=activated,
                hidden_responder_used_in_proposal=hidden_used,
                applied=applied,
                applied_with_hidden_responder=applied and hidden_used,
            )
        )

    return PublicSolicitationTraceSummary(
        trace_path=str(trace_path),
        config_name=config.name,
        rounds=len(round_traces),
        public_solicitation_activated_rounds=sum(
            1 for item in round_traces if item.public_solicitation_activated
        ),
        hidden_responder_rounds=sum(1 for item in round_traces if item.hidden_responders),
        hidden_responder_count=sum(len(item.hidden_responders) for item in round_traces),
        hidden_responder_used_in_proposal_rounds=sum(
            1 for item in round_traces if item.hidden_responder_used_in_proposal
        ),
        applied_trades=sum(1 for item in round_traces if item.applied),
        applied_trades_with_hidden_responders=sum(
            1 for item in round_traces if item.applied_with_hidden_responder
        ),
        round_traces=round_traces,
    )


def _sample_positive_quantity(rng: random.Random, available: float) -> float:
    if available <= 1e-9:
        return 0.0
    cap = min(float(available), 3.0)
    return max(0.05, round(rng.uniform(0.05, cap), 3))


def _random_visible_swap_round(
    world: ex.ExchangeWorld,
    protocol: ex.ProtocolConfig,
    *,
    controller_id: int,
    round_index: int,
    rng: random.Random,
) -> bool:
    participants = ex._communication_agent_ids_for(protocol, world, controller_id)
    if len(participants) < 2:
        return False
    first, second = rng.sample(participants, 2)
    first_resources = [
        rid
        for rid in range(1, world.num_resources + 1)
        if float(world.allocation[first - 1][rid - 1]) > 1e-9
    ]
    second_resources = [
        rid
        for rid in range(1, world.num_resources + 1)
        if float(world.allocation[second - 1][rid - 1]) > 1e-9
    ]
    if not first_resources or not second_resources:
        return False
    first_resource = rng.choice(first_resources)
    second_resource = rng.choice(second_resources)
    mechanism = ex.CompiledMechanism(
        proposer_id=controller_id,
        label="random_visible_swap",
        summary="Random visible paired swap baseline.",
        transfers=[
            ex.Transfer(
                from_agent=first,
                to_agent=second,
                resource=first_resource,
                quantity=_sample_positive_quantity(rng, float(world.allocation[first - 1][first_resource - 1])),
            ),
            ex.Transfer(
                from_agent=second,
                to_agent=first,
                resource=second_resource,
                quantity=_sample_positive_quantity(rng, float(world.allocation[second - 1][second_resource - 1])),
            ),
        ],
        consenting_agents=sorted({first, second}),
        confidence=1.0,
        verifier_ok=True,
    )
    event = ex.apply_compiled_mechanism(
        world,
        mechanism,
        round_index=round_index,
        controller_id=controller_id,
        ir_enforce=True,
    )
    return bool(event.applied)


def simulate_random_visible_swap_floor(
    world: ex.ExchangeWorld,
    protocol: ex.ProtocolConfig,
    *,
    controllers: list[int],
    rounds: int,
    samples: int,
    random_seed: int,
) -> float:
    """Mean safe surplus from random visible paired swaps.

    Random attempts are executed through the same ledger and IR gate as other
    baselines. This is intentionally weak: it tests that reward is not captured
    by arbitrary motion.
    """
    if samples < 1:
        raise ValueError("samples must be positive")
    gains: list[float] = []
    for sample_idx in range(samples):
        rng = random.Random(random_seed + sample_idx * 1009)
        sample_gain = 0.0
        for round_index in range(1, rounds + 1):
            work = deepcopy(world)
            initial = ex.total_welfare(work)
            controller_id = controllers[(round_index - 1) % len(controllers)]
            _random_visible_swap_round(
                work,
                protocol,
                controller_id=controller_id,
                round_index=round_index,
                rng=rng,
            )
            sample_gain += max(0.0, ex.total_welfare(work) - initial)
        gains.append(sample_gain)
    return mean(gains)


def _score_greedy_bilateral_opportunities(
    world: ex.ExchangeWorld,
    protocol: ex.ProtocolConfig,
    *,
    controllers: list[int],
    rounds: int,
) -> tuple[float, int]:
    total_gain = 0.0
    positive_rounds = 0
    for round_index in range(1, rounds + 1):
        controller_id = controllers[(round_index - 1) % len(controllers)]
        visible_participants = ex._communication_agent_ids_for(protocol, world, controller_id)
        solution = ex.solve_bilateral_ir_oracle(
            world,
            participants=visible_participants,
            controller_id=controller_id,
            row_limit=protocol.settlement_row_limit,
        )
        if solution.welfare_gain > 1e-9:
            total_gain += solution.welfare_gain
            positive_rounds += 1
    return total_gain, positive_rounds


def _score_protocol_oracle_opportunities(
    world: ex.ExchangeWorld,
    config: ex.ExchangeExperimentConfig,
    *,
    rounds: int,
) -> tuple[float, int]:
    total_gain = 0.0
    positive_rounds = 0
    for round_index in range(1, rounds + 1):
        controller_id = config.controllers[(round_index - 1) % len(config.controllers)]
        solution = ex.solve_protocol_constrained_ir_oracle(
            world,
            config.protocol,
            controller_id=controller_id,
        )
        if solution.welfare_gain > 1e-9:
            total_gain += solution.welfare_gain
            positive_rounds += 1
    return total_gain, positive_rounds


def _best_controller_public_pair(
    world: ex.ExchangeWorld,
    config: ex.ExchangeExperimentConfig,
    *,
    controller_id: int,
) -> ex.OracleSolution:
    """Fast public-solicitation ceiling for the validity gate.

    The exact bounded public-solicitation oracle is useful but expensive. For the
    v1 environment-validity gate, use a cheaper upper bound: if a public opt-in
    path exists, the controller can discover its best hidden bilateral
    counterparty. This tests whether hidden discovery creates additional
    reachable surplus without solving a full public clearing problem.
    """
    if not (config.protocol.public_broadcast and config.protocol.response_scope == "solicited_public"):
        return ex.solve_protocol_constrained_ir_oracle(
            world,
            config.protocol,
            controller_id=controller_id,
        )
    best: ex.OracleSolution | None = None
    for aid in range(1, world.num_agents + 1):
        if aid == controller_id:
            continue
        candidate = ex.solve_bilateral_ir_oracle(
            world,
            participants=[controller_id, aid],
            controller_id=controller_id,
            row_limit=config.protocol.settlement_row_limit,
        )
        if best is None or candidate.welfare_gain > best.welfare_gain + 1e-9:
            best = candidate
    return best or ex.solve_protocol_constrained_ir_oracle(
        world,
        config.protocol,
        controller_id=controller_id,
    )


def _score_public_pair_opportunities(
    world: ex.ExchangeWorld,
    config: ex.ExchangeExperimentConfig,
    *,
    rounds: int,
) -> tuple[float, int]:
    total_gain = 0.0
    positive_rounds = 0
    for round_index in range(1, rounds + 1):
        controller_id = config.controllers[(round_index - 1) % len(config.controllers)]
        solution = _best_controller_public_pair(
            world,
            config,
            controller_id=controller_id,
        )
        if solution.welfare_gain > 1e-9:
            total_gain += solution.welfare_gain
            positive_rounds += 1
    return total_gain, positive_rounds


def evaluate_config_validity(
    config: ex.ExchangeExperimentConfig,
    *,
    rounds: int | None = None,
    random_samples: int = 5,
    random_seed: int = 0,
    use_public_solicitation_for_information_oracle: bool | None = None,
) -> ConfigValidityResult:
    rounds = config.rounds if rounds is None else int(rounds)
    world = ex.make_world_from_config(config)
    greedy_gain, greedy_applied = _score_greedy_bilateral_opportunities(
        world,
        config.protocol,
        controllers=config.controllers,
        rounds=rounds,
    )
    random_gain = simulate_random_visible_swap_floor(
        deepcopy(world),
        config.protocol,
        controllers=config.controllers,
        rounds=rounds,
        samples=random_samples,
        random_seed=random_seed,
    )
    stronger_gain, stronger_applied = _score_protocol_oracle_opportunities(
        world,
        config,
        rounds=rounds,
    )
    if use_public_solicitation_for_information_oracle is None:
        use_public_solicitation_for_information_oracle = (
            config.protocol.public_broadcast and config.protocol.response_scope == "solicited_public"
        )
    if use_public_solicitation_for_information_oracle:
        public_pair_gain, public_pair_applied = _score_public_pair_opportunities(
            world,
            config,
            rounds=rounds,
        )
        if public_pair_gain > stronger_gain + 1e-9:
            info_gain = public_pair_gain
            info_applied = public_pair_applied
        else:
            info_gain = stronger_gain
            info_applied = stronger_applied
    else:
        info_gain, info_applied = _score_protocol_oracle_opportunities(
            world,
            config,
            rounds=rounds,
        )
    return ConfigValidityResult(
        config_name=config.name,
        rounds=rounds,
        no_op_gain=0.0,
        random_mean_gain=random_gain,
        greedy_gain=greedy_gain,
        stronger_heuristic_gain=stronger_gain,
        information_constrained_gain=info_gain,
        hidden_discovery_gain=max(0.0, info_gain - stronger_gain),
        greedy_applied_rounds=greedy_applied,
        stronger_heuristic_applied_rounds=stronger_applied,
        information_constrained_applied_rounds=info_applied,
    )


def _inequality(left_metric: str, left_value: float, right_metric: str, right_value: float) -> ValidityInequality:
    return ValidityInequality(
        left_metric=left_metric,
        right_metric=right_metric,
        left_value=left_value,
        right_value=right_value,
        passed=left_value < right_value - 1e-9,
    )


def _treatment_environment_ordering(
    treatment: ConfigValidityResult,
) -> dict[str, ValidityInequality]:
    """Oracle ordering expected of a useful benchmark arm, scored on the treatment.

    random < greedy < stronger_heuristic <= information_constrained. Provider-free.
    """
    return {
        "random_lt_greedy": _inequality(
            "random_mean_gain",
            treatment.random_mean_gain,
            "greedy_gain",
            treatment.greedy_gain,
        ),
        "greedy_lt_stronger_heuristic": _inequality(
            "greedy_gain",
            treatment.greedy_gain,
            "stronger_heuristic_gain",
            treatment.stronger_heuristic_gain,
        ),
        "stronger_heuristic_lt_information_constrained": _inequality(
            "stronger_heuristic_gain",
            treatment.stronger_heuristic_gain,
            "information_constrained_gain",
            treatment.information_constrained_gain,
        ),
    }


def evaluate_paired_validity(
    control_config_path: str | Path,
    treatment_config_path: str | Path,
    *,
    conceptual_knob: str,
    allowed_diffs: set[str] | None = None,
    rounds: int | None = None,
    random_samples: int = 5,
    random_seed: int = 0,
    use_public_solicitation_for_information_oracle: bool | None = None,
) -> PairedValidityReport:
    """Provider-free validity of an arbitrary single-knob mechanism ablation.

    Generalizes the public-solicitation check to any mechanism: the caller names
    the ``conceptual_knob`` and the ``allowed_diffs`` set (the config fields that
    are intended to change between control and treatment). The information-oracle
    behavior is auto-derived from each arm's protocol unless explicitly forced.
    """
    control_config = ex.load_experiment_config(control_config_path)
    treatment_config = ex.load_experiment_config(treatment_config_path)
    pair_check = compare_paired_ablation_configs(
        control_config,
        treatment_config,
        conceptual_knob=conceptual_knob,
        allowed_diffs=allowed_diffs,
    )
    eval_rounds = rounds if rounds is not None else treatment_config.rounds
    control = evaluate_config_validity(
        control_config,
        rounds=eval_rounds,
        random_samples=random_samples,
        random_seed=random_seed,
        use_public_solicitation_for_information_oracle=use_public_solicitation_for_information_oracle,
    )
    treatment = evaluate_config_validity(
        treatment_config,
        rounds=eval_rounds,
        random_samples=random_samples,
        random_seed=random_seed,
        use_public_solicitation_for_information_oracle=use_public_solicitation_for_information_oracle,
    )
    return PairedValidityReport(
        control=control,
        treatment=treatment,
        paired_ablation=pair_check,
        environment_ordering=_treatment_environment_ordering(treatment),
        rounds=eval_rounds,
        random_samples=random_samples,
        random_seed=random_seed,
    )


def evaluate_paired_public_solicitation_validity(
    control_config_path: str | Path,
    treatment_config_path: str | Path,
    *,
    rounds: int | None = None,
    random_samples: int = 5,
    random_seed: int = 0,
) -> PairedValidityReport:
    control_config = ex.load_experiment_config(control_config_path)
    treatment_config = ex.load_experiment_config(treatment_config_path)
    pair_check = compare_paired_ablation_configs(
        control_config,
        treatment_config,
        conceptual_knob="public_solicitation_path",
    )
    eval_rounds = rounds if rounds is not None else treatment_config.rounds
    control = evaluate_config_validity(
        control_config,
        rounds=eval_rounds,
        random_samples=random_samples,
        random_seed=random_seed,
        use_public_solicitation_for_information_oracle=False,
    )
    treatment = evaluate_config_validity(
        treatment_config,
        rounds=eval_rounds,
        random_samples=random_samples,
        random_seed=random_seed,
        use_public_solicitation_for_information_oracle=True,
    )
    return PairedValidityReport(
        control=control,
        treatment=treatment,
        paired_ablation=pair_check,
        environment_ordering=_treatment_environment_ordering(treatment),
        rounds=eval_rounds,
        random_samples=random_samples,
        random_seed=random_seed,
    )


def _write_json(path: Path, report: PairedValidityReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True), encoding="utf-8")


def render_markdown_report(report: PairedValidityReport) -> str:
    rows = [
        "| Arm | Random | Greedy | Stronger heuristic | Info-constrained | Hidden discovery |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, result in [("Control", report.control), ("Treatment", report.treatment)]:
        rows.append(
            "| "
            f"{label} | {result.random_mean_gain:.3f} | {result.greedy_gain:.3f} | "
            f"{result.stronger_heuristic_gain:.3f} | {result.information_constrained_gain:.3f} | "
            f"{result.hidden_discovery_gain:.3f} |"
        )
    ordering_rows = [
        "| Inequality | Left | Right | Pass |",
        "|---|---:|---:|---|",
    ]
    for name, item in report.environment_ordering.items():
        ordering_rows.append(
            f"| `{name}` | {item.left_value:.3f} | {item.right_value:.3f} | {item.passed} |"
        )
    return "\n".join(
        [
            "# Exchange V1 Public-Solicitation Validity Check",
            "",
            f"- rounds: `{report.rounds}`",
            f"- random samples: `{report.random_samples}`",
            f"- random seed: `{report.random_seed}`",
            f"- llm calls: `{report.llm_calls}`",
            f"- paired ablation clean: `{report.paired_ablation.passed}`",
            f"- environment ordering passed: `{all(x.passed for x in report.environment_ordering.values())}`",
            "",
            "## Baseline / Oracle Ordering",
            "",
            *rows,
            "",
            "## Inequalities",
            "",
            *ordering_rows,
            "",
            "## Paired-Ablation Diff",
            "",
            "Expected differences:",
            "",
            "```json",
            json.dumps(report.paired_ablation.expected_diffs, indent=2, sort_keys=True),
            "```",
            "",
            "Unexpected differences:",
            "",
            "```json",
            json.dumps(report.paired_ablation.unexpected_diffs, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )


def _write_markdown(path: Path, report: PairedValidityReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_report(report), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--control-config",
        default="configs/exchange_economy/baselines/core_atomic_ir_clean.json",
    )
    parser.add_argument(
        "--treatment-config",
        default="configs/exchange_economy/treatments/public_solicitation/treatment_public_solicitation_solicited.json",
    )
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--random-samples", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument(
        "--conceptual-knob",
        default=None,
        help="Name the single mechanism knob under test (generic mode). "
        "When omitted, runs the public-solicitation default.",
    )
    parser.add_argument(
        "--allowed-diffs",
        default=None,
        help="Comma-separated config fields permitted to differ between arms in "
        "generic mode, e.g. 'name,description,protocol.name,protocol.partial_clearing'.",
    )
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    if args.conceptual_knob:
        allowed = (
            {s.strip() for s in args.allowed_diffs.split(",") if s.strip()}
            if args.allowed_diffs
            else None
        )
        report = evaluate_paired_validity(
            args.control_config,
            args.treatment_config,
            conceptual_knob=args.conceptual_knob,
            allowed_diffs=allowed,
            rounds=args.rounds,
            random_samples=args.random_samples,
            random_seed=args.random_seed,
        )
    else:
        report = evaluate_paired_public_solicitation_validity(
            args.control_config,
            args.treatment_config,
            rounds=args.rounds,
            random_samples=args.random_samples,
            random_seed=args.random_seed,
        )
    print(render_markdown_report(report))
    if args.output_json:
        _write_json(Path(args.output_json), report)
    if args.output_md:
        _write_markdown(Path(args.output_md), report)


if __name__ == "__main__":
    main()
