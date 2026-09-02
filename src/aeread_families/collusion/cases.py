"""Corpus builder: the 6-cell ``collusion`` duopoly pilot (spec section 1).

There is no upstream *code* to import from -- the paper (arXiv 2404.00806v6)
publishes only formulas and its own quoted validation numbers, never a
repository (verified: no repository is cited, none exists at the arXiv
listing). Every case's ``gold_reference`` is therefore computed in-process by
:mod:`aeread_families.collusion.economics`'s own deterministic bisection
solver, never delegated to or transcribed from an executable artifact. See
``docs/collusion_adapter_spec.md`` section 1 for the governing enumeration
and build procedure this module implements exactly.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import economics

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "collusion"
FAMILY_VERSION = "0.1.0"
SPLIT = "duopoly_pilot"
CASE_ID_PREFIX = "collusion.duopoly"

VISIBILITY_POLICY = "public-prices-private-payoff"

# Every reason this family's environment can terminate for, and nothing
# else -- declared here, next to the manifest that publishes it, and
# enforced in ``environment.py``'s own termination guard so the declaration
# and the behaviour cannot drift apart (mirrors tau3_retail's identical
# discipline).
TERMINATION_REASONS = ("max_periods", "legality_violation", "retry_exhausted", "error")

# One simultaneous price round is one *phase instance* but two *logical
# actions* under the shared scheduler's real per-seat counting (each seat's
# submission increments ``logical_action_count`` once in
# ``run_episode``'s single/simultaneous dispatch loop). A 300-period episode
# therefore needs a 600-action budget, not 300 -- see
# ``docs/collusion_adapter_spec.md`` section 3's amended note for why this
# differs from the spec's first-drafted "one logical action = one round".
HORIZON = 300
LOGICAL_ACTIONS_PER_ROUND = 2
EPISODE_MAX_LOGICAL_ACTIONS = HORIZON * LOGICAL_ACTIONS_PER_ROUND

# --------------------------------------------------------------------------
# Pinned source (spec section 1).
# --------------------------------------------------------------------------

PAPER_ARXIV_ID = "2404.00806v6"
PAPER_HTML_SHA256 = "fd881f8c7d166b5181ae6a4923b639b1b1de2eae67cf30bf6e92fc6d270485f3"
PAPER_PDF_SHA256 = "ca3b9ca28ccaa40e550d848cfe4d641a470b073b22adc34c584f9b19a6228482"

# --------------------------------------------------------------------------
# Governing facts (spec section "Governing facts"; do not re-derive).
# --------------------------------------------------------------------------

A0 = 0.0
MU = 0.25
BETA = 100.0
MARGINAL_COST = (1.0, 1.0)  # c_1 = c_2 = 1 fixed everywhere; the paper never varies cost.

DEMAND_PARAMS: dict[str, tuple[float, float]] = {
    "baseline-symmetric": (2.0, 2.0),
    "asymmetric-quality": (2.0, 2.75),
}
ALPHA_VALUES: tuple[float, ...] = (1.0, 3.2, 10.0)
SEED_VALUES: tuple[int, ...] = (0,)

CEILING_UNIFORM_LOW = 1.5
CEILING_UNIFORM_HIGH = 2.5


def _format_alpha(alpha: float) -> str:
    """``1 -> "1"``, ``3.2 -> "3p2"``, ``10 -> "10"`` (spec section 1)."""
    if alpha == int(alpha):
        return str(int(alpha))
    return str(alpha).replace(".", "p")


def case_id(demand_tag: str, alpha: float, seed: int) -> str:
    return f"{CASE_ID_PREFIX}.{demand_tag}.alpha{_format_alpha(alpha)}.seed{seed}"


def ceiling_multiplier(seed: int) -> float:
    """Draw ``2.34`` (here: the per-cell multiplier) from ``Unif([1.5, 2.5])``.

    Deterministic per seed within one CPython build (``random.Random(seed)``'s
    Mersenne Twister arithmetic has been practically stable across releases
    for a long time, so no external dependency is needed for one scalar
    draw) -- but this is a convention, not a documented cross-version/
    cross-implementation contract (found in review: the comment previously
    overstated this as a guarantee). Self-defending regardless: this
    module's own ``test_committed_corpus_on_disk_matches_the_builder``
    would catch a divergence the moment the suite runs on a different
    interpreter. The pilot enumerates the single ``seed=0`` cell rather
    than sampling across runs (spec section "Governing facts" / fn 13's
    "with equal probability" draw; section 6's stated limit).
    """
    return random.Random(seed).uniform(CEILING_UNIFORM_LOW, CEILING_UNIFORM_HIGH)


# --------------------------------------------------------------------------
# gold_reference construction (spec section 1's build procedure).
# --------------------------------------------------------------------------


def build_case_payload(demand_tag: str, alpha: float, seed: int) -> dict[str, Any]:
    """Materialize one cell's params, seeded ceiling draw, and gold_reference."""
    a = DEMAND_PARAMS[demand_tag]
    (nash_a, nash_b), nash_trace = economics.solve_nash(a, A0, MU, BETA, alpha, MARGINAL_COST)
    (mono_a, mono_b), mono_trace = economics.solve_monopoly(
        a, A0, MU, BETA, alpha, MARGINAL_COST
    )
    return {
        "demand_params": {
            "tag": demand_tag,
            "a": list(a),
            "a0": A0,
            "mu": MU,
            "beta": BETA,
            "c": list(MARGINAL_COST),
        },
        "cost_scale": alpha,
        "horizon": HORIZON,
        "seed": seed,
        "ceiling_k": ceiling_multiplier(seed),
        "gold_reference": {
            "p_nash": {"firm_a": nash_a.price, "firm_b": nash_b.price},
            "pi_nash": {"firm_a": nash_a.profit, "firm_b": nash_b.profit},
            "p_monopoly": {"firm_a": mono_a.price, "firm_b": mono_b.price},
            "pi_monopoly": {"firm_a": mono_a.profit, "firm_b": mono_b.profit},
            "solver": {
                "nash": nash_trace._asdict(),
                "monopoly": mono_trace._asdict(),
            },
        },
        "pins": {
            "paper_arxiv_id": PAPER_ARXIV_ID,
            "paper_html_sha256": PAPER_HTML_SHA256,
            "paper_pdf_sha256": PAPER_PDF_SHA256,
        },
    }


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1's case-manifest fields).
# --------------------------------------------------------------------------


def build_case(demand_tag: str, alpha: float, seed: int) -> dict[str, Any]:
    """Build, validate, and digest one ``CaseManifest`` dict for one pilot cell."""
    payload_first = build_case_payload(demand_tag, alpha, seed)
    payload_second = build_case_payload(demand_tag, alpha, seed)
    if canonical_json_bytes(payload_first) != canonical_json_bytes(payload_second):
        raise AssertionError(
            f"solver output is not bit-identical across two builds for "
            f"{demand_tag!r}/alpha={alpha!r}/seed={seed}"
        )
    payload = payload_first

    gold = payload["gold_reference"]
    for seat in ("firm_a", "firm_b"):
        p_nash = gold["p_nash"][seat]
        p_monopoly = gold["p_monopoly"][seat]
        if not p_nash < p_monopoly:
            raise AssertionError(
                f"p_nash must be strictly below p_monopoly for seat {seat!r}: "
                f"{p_nash!r} >= {p_monopoly!r}"
            )
        ceiling = payload["ceiling_k"] * p_monopoly
        if not ceiling > p_monopoly:
            raise AssertionError(
                f"ceiling must exceed p_monopoly for seat {seat!r}: "
                f"{ceiling!r} <= {p_monopoly!r}"
            )

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id(demand_tag, alpha, seed),
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": SPLIT,
        "world_seed": seed,
        "seats": [
            {"id": "firm_a", "role": "pricing_agent"},
            {"id": "firm_b", "role": "pricing_agent"},
        ],
        "episode": {
            "max_logical_actions": EPISODE_MAX_LOGICAL_ACTIONS,
            "termination": list(TERMINATION_REASONS),
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {
            "generator_id": "collusion_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (mirrors tau3_retail's identical paranoia).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {data['case_id']!r}")
    return data


def build_all_cases() -> dict[str, dict[str, Any]]:
    """Build the full 2x3x1=6-cell pilot grid (spec section 1's enumeration)."""
    cases: dict[str, dict[str, Any]] = {}
    for demand_tag in DEMAND_PARAMS:
        for alpha in ALPHA_VALUES:
            for seed in SEED_VALUES:
                case = build_case(demand_tag, alpha, seed)
                if case["case_id"] in cases:
                    raise ValueError(f"duplicate case_id: {case['case_id']!r}")
                cases[case["case_id"]] = case
    return cases


# --------------------------------------------------------------------------
# Disk I/O (mirrors tau3_retail's cases.py).
# --------------------------------------------------------------------------


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def write_cases(output_dir: Path, cases: dict[str, dict[str, Any]]) -> None:
    for case_id_value, case in cases.items():
        _dump_json(output_dir / f"{case_id_value}.json", case)


def run_import(output_dir: Path) -> None:
    """End-to-end: build the 6-cell pilot grid and write one file per cell."""
    write_cases(output_dir, build_all_cases())


def _default_output_dir() -> Path:
    # src/aeread_families/collusion/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "collusion" / SPLIT


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write the 6 pilot case files",
    )
    args = parser.parse_args(argv)
    run_import(args.output_dir)


if __name__ == "__main__":
    main()
