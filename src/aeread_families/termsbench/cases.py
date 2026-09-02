"""Deterministic case generator: TERMS-Bench regime/type draws -> AERead cases.

There is no upstream corpus to re-resolve against (the paper's own repository
link is dead; see ``docs/termsbench_adapter_spec.md`` section 1). Gate 1's
"source" check #1 therefore re-resolves against **our own deterministic
generator**: regenerating from the same ``(generator_version, world_seed)``
must produce a byte-identical ``CaseManifest``. Every economic/structural
formula this module calls lives in ``kernel.py`` (cited to its paper
equation); this module owns only RNG-seeded sampling, difficulty-bin
assignment (Gate 1 check #3: computed solely from steps 1-3, never from
realized play), payload freezing, and the pilot manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import kernel as k

# --------------------------------------------------------------------------
# Family / case identity constants (docs/termsbench_adapter_spec.md section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "termsbench"
FAMILY_VERSION = "0.1.0"
GENERATOR_ID = "termsbench_generator"
GENERATOR_VERSION = FAMILY_VERSION

REGIMES: tuple[str, ...] = ("overlap", "nodeal")

# Paper vocabulary (App. C.2.3) uses PascalCase (AgentAccept, ...); the case
# identifier grammar forbids uppercase, so the manifest-facing termination
# vocabulary is the lower_snake_case rendering used consistently across
# cases.py, environment.py, and every test. The mapping is 1:1 and total.
TERMINATION_REASONS: tuple[str, ...] = (
    "agent_accept",
    "counterpart_accept",
    "agent_reject",
    "counterpart_walk_away",
    "timeout",
    "agreement_violation",
)

# docs/termsbench_adapter_spec.md section 2: agent must respect its own r_A as
# a hard IR constraint; nothing in this milestone hides that seat's role.
VISIBILITY_POLICY = "termsbench_hidden_counterpart_type_v1"

# --------------------------------------------------------------------------
# Pinned source (docs/termsbench_adapter_spec.md's "Pinned source" table).
# --------------------------------------------------------------------------

PAPER_TITLE = "TERMS-Bench: Diagnosing LLM Negotiation Agents Beyond Deal Rate"
PAPER_ARXIV_ID = "2605.13909v2"
PAPER_HTML_SHA256 = "d62f52687a3d03a1fd3252501baed1bcb432bb2857edd66208de34eb26cb1848"
PAPER_PDF_SHA256 = "bea6a0a272f9e4f97539ebace7936239926268cb71c83f8d00203ba8398b1dcf"

# Pilot design (docs/termsbench_adapter_spec.md section 1): 3 families x 2
# regimes x 5 difficulty bins, one seed per cell = 30 scenarios. Candidate
# pool size per (family, regime) cell used only to assign quantile bins
# (Appendix G.3); the pool itself is never part of the pilot manifest.
POOL_SIZE = 60
NUM_DIFFICULTY_BINS = 5

# Fixed simplifications for tonight's pilot (documented deviation from the
# full paper design, which balances agent role and opener role in a 2x2 per
# regime-family cell across a much larger main suite -- section 4.1/H.1.2).
# The pilot instead fixes the agent role and lets opener alternate by seed
# parity (docs/termsbench_adapter_spec.md section 1, last paragraph).
PILOT_AGENT_ROLE = "buyer"


def _counterpart_role(agent_role: str) -> str:
    return "seller" if agent_role == "buyer" else "buyer"


def _opener_for_seed(world_seed: int) -> str:
    """chi, alternated by seed parity (spec section 1)."""
    return "counterpart_opens" if world_seed % 2 == 0 else "agent_opens"


def _candidate_seed_base(family: str, regime: str) -> int:
    """Disjoint per-(family, regime) seed range, leaving 10 unused decades
    per family for a future split (Gate 1 check #6: dev/confirmatory splits
    use disjoint seed ranges, never re-rolled)."""
    family_index = k.FAMILIES.index(family)
    regime_index = REGIMES.index(regime)
    return 1_000_000 + family_index * 100_000 + regime_index * 10_000


def _rng_for_seed(world_seed: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(world_seed))


def _draw_geometry(regime: str, rng: np.random.Generator) -> tuple[float, float, float]:
    """Return (r_buyer, r_seller, midpoint_percentile) per Section 3.1."""
    u_e = float(rng.uniform(0.0, 1.0))
    if regime == "overlap":
        width_min, width_max = k.ZOPA_WIDTH_MIN, k.ZOPA_WIDTH_MAX
        z = width_min + u_e * (width_max - width_min)
        midpoint = float(rng.uniform(k.P_MIN + z / 2.0, k.P_MAX - z / 2.0))
        r_buyer = midpoint + z / 2.0
        r_seller = midpoint - z / 2.0
        return r_buyer, r_seller, u_e
    if regime == "nodeal":
        gap_min, gap_max = k.NODEAL_GAP_MIN, k.NODEAL_GAP_MAX
        q = gap_min + u_e * (gap_max - gap_min)
        midpoint = float(rng.uniform(k.P_MIN + q / 2.0, k.P_MAX - q / 2.0))
        r_buyer = midpoint - q / 2.0
        r_seller = midpoint + q / 2.0
        return r_buyer, r_seller, u_e
    raise ValueError(f"unknown regime: {regime!r}")


def _draw_kappa(rng: np.random.Generator) -> float:
    """D_kappa = Beta(alpha_kappa, beta_kappa) on [0, 1] (Section 3.1)."""
    return float(rng.beta(k.BETA_KAPPA_ALPHA, k.BETA_KAPPA_BETA))


def _draw_stance(rng: np.random.Generator) -> str:
    """eta_B ~ the family's stance prior; uniform for all 3 implemented
    families (Table 3)."""
    return str(rng.choice(k.STANCE_TYPES))


def generate_payload(family: str, regime: str, world_seed: int) -> dict[str, Any]:
    """Draw and freeze one case's environment payload (spec section 1,
    steps 1-6), computed entirely from pre-interaction properties."""
    if family not in k.FAMILY_PRESETS:
        raise ValueError(f"unknown counterpart family: {family!r}")
    if regime not in REGIMES:
        raise ValueError(f"unknown regime: {regime!r}")

    rng = _rng_for_seed(world_seed)
    r_buyer, r_seller, geometry_percentile = _draw_geometry(regime, rng)
    kappa_b = _draw_kappa(rng)
    kappa_agent = _draw_kappa(rng)
    eta_b = _draw_stance(rng)
    opening_harshness = float(rng.uniform(k.D_OPEN_MIN, k.D_OPEN_MAX))

    agent_role = PILOT_AGENT_ROLE
    counterpart_role = _counterpart_role(agent_role)
    r_a = r_buyer if agent_role == "buyer" else r_seller
    r_b = r_seller if agent_role == "buyer" else r_buyer
    delta = r_buyer - r_seller
    price_range = k.P_MAX - k.P_MIN
    chi = _opener_for_seed(world_seed)

    if regime == "overlap":
        difficulty_score = k.overlap_difficulty(
            delta=delta,
            price_range=price_range,
            kappa_agent=kappa_agent,
            kappa_counterpart=kappa_b,
            eta_b=eta_b,
        )
    else:
        difficulty_score = k.nodeal_difficulty(
            delta=delta,
            sigma_scale=price_range,
            cue_channel=k.FAMILY_PRESETS[family]["cue_channel"],
            eta_b=eta_b,
        )

    preset_name = k.FAMILY_PRESETS[family]["economic_preset"]
    preset = k.ECONOMIC_PRESETS[preset_name]
    price_noise_tier = k.FAMILY_PRESETS[family]["price_noise_tier"]

    return {
        "regime": regime,
        "family": family,
        "horizon": k.DEFAULT_HORIZON,
        "agent": {"role": agent_role, "r_a": r_a, "kappa_a": kappa_agent},
        "t_b": {"r_b": r_b, "kappa_b": kappa_b, "eta_b": eta_b},
        "counterpart_role": counterpart_role,
        "chi": chi,
        "price_bounds": {"p_min": k.P_MIN, "p_max": k.P_MAX},
        "opening_harshness": opening_harshness,
        "geometry_percentile": geometry_percentile,
        "delta": delta,
        "difficulty_score": difficulty_score,
        "hyperparameters": {
            "acceptance_model": {"alpha": k.ALPHA, "beta": k.BETA, "gamma": k.GAMMA},
            "economic_preset": {
                "name": preset_name,
                "rho": dict(preset["rho"]),
                "xi": dict(preset["xi"]),
                "lambda2": dict(preset["lambda2"]),
            },
            "walkaway_model": {
                "k_walk": k.k_walk(k.DEFAULT_HORIZON),
                "phi_0": k.PHI_0,
                "phi_delta": k.PHI_DELTA,
                "phi_t": k.PHI_T,
            },
            "counter_offer_model": {
                "lambda_0": k.LAMBDA_0,
                "lambda_1": k.LAMBDA_1,
                "lambda_3": k.LAMBDA_3,
                "lambda_4": k.LAMBDA_4,
                "price_noise_tier": price_noise_tier,
                "sigma_bar_p": k.PRICE_NOISE_SCALE_BY_TIER[price_noise_tier],
            },
            "history_features": {"tau_rigid": k.TAU_RIGID},
            "opening_offer_model": {
                "d_open_min": k.D_OPEN_MIN,
                "d_open_max": k.D_OPEN_MAX,
                "omega_kappa": k.OMEGA_KAPPA,
                "omega_eta": k.OMEGA_ETA,
                "omega_eta_prime": k.OMEGA_ETA_PRIME,
                "phi_min": k.PHI_MIN,
                "phi_max": k.PHI_MAX,
                "sigma_bar_0": k.OPENING_NOISE_SCALE,
            },
            "cue_model": {
                "cue_channel": k.FAMILY_PRESETS[family]["cue_channel"],
                "tau_dead": k.TAU_DEAD,
                "tau_conc": k.TAU_CONC,
                "b_concede": k.B_CONCEDE,
                "b_hold": k.B_HOLD,
                "b_pressure": k.B_PRESSURE,
                "alpha_c": k.ALPHA_C,
                "alpha_p": k.ALPHA_P,
                "beta_c": k.BETA_C,
                "mu_s": k.MU_S,
                "tau_s": k.TAU_S,
                "sigma_s": k.SIGMA_S,
            },
        },
    }


def _difficulty_score_only(family: str, regime: str, world_seed: int) -> float:
    return float(generate_payload(family, regime, world_seed)["difficulty_score"])


def _assign_quantile_bin(rank: int, pool_size: int, num_bins: int = NUM_DIFFICULTY_BINS) -> int:
    """0-based ascending difficulty bin (0 = easiest, num_bins-1 = hardest)."""
    bin_index = (rank * num_bins) // pool_size
    return min(bin_index, num_bins - 1)


def select_pilot_cell_seed(
    family: str, regime: str, difficulty_bin: int, *, pool_size: int = POOL_SIZE
) -> int:
    """Return the one world_seed representing (family, regime, difficulty_bin)
    in the pilot: candidates are ranked ascending by ``difficulty_score``
    over the cell's own candidate pool, binned into ``NUM_DIFFICULTY_BINS``
    quantile bins by that rank, and this returns the seed at the *first
    rank* (lowest ``difficulty_score``, ties broken by ``sorted``'s
    stability, i.e. by ascending seed) whose bin equals ``difficulty_bin`` --
    not necessarily the numerically smallest seed among every candidate that
    lands in that bin."""
    if not 0 <= difficulty_bin < NUM_DIFFICULTY_BINS:
        raise ValueError(f"difficulty_bin must be in [0, {NUM_DIFFICULTY_BINS}); got {difficulty_bin}")
    base = _candidate_seed_base(family, regime)
    seeds = [base + offset for offset in range(pool_size)]
    scored = sorted(
        ((seed, _difficulty_score_only(family, regime, seed)) for seed in seeds),
        key=lambda pair: pair[1],
    )
    for rank, (seed, _score) in enumerate(scored):
        if _assign_quantile_bin(rank, pool_size) == difficulty_bin:
            return seed
    raise AssertionError(
        f"no candidate seed landed in difficulty_bin {difficulty_bin} for "
        f"({family!r}, {regime!r}); increase pool_size"
    )


def pilot_cells() -> list[tuple[str, str, int, int]]:
    """Enumerate the 30 (family, regime, difficulty_bin, world_seed) pilot cells."""
    cells: list[tuple[str, str, int, int]] = []
    for family in k.FAMILIES:
        for regime in REGIMES:
            for difficulty_bin in range(NUM_DIFFICULTY_BINS):
                seed = select_pilot_cell_seed(family, regime, difficulty_bin)
                cells.append((family, regime, difficulty_bin, seed))
    return cells


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1).
# --------------------------------------------------------------------------


def build_case(family: str, regime: str, world_seed: int) -> dict[str, Any]:
    """Build one CaseManifest dict for one (family, regime, world_seed) draw.

    Regenerating with the same (GENERATOR_VERSION, world_seed) reproduces this
    dict byte-for-byte (Gate 1 check #1): every input is a pure function of
    world_seed via a freshly seeded RNG, and content_sha256 covers only the
    generated payload, never a network or filesystem artifact.
    """
    payload = generate_payload(family, regime, world_seed)
    case_id = f"{FAMILY_ID}.{family}.{regime}.{world_seed}"
    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": family,
        "world_seed": world_seed,
        "seats": [
            {"id": "agent", "role": "agent"},
            {"id": "counterpart", "role": "counterpart"},
        ],
        "episode": {
            "max_logical_actions": 2 * k.DEFAULT_HORIZON,
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "review_status": "generated",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (paranoia; cheap, catches canonicalization bugs).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def build_pilot_cases() -> dict[str, dict[str, Any]]:
    """Build all 30 pilot cases, keyed by case_id."""
    cases: dict[str, dict[str, Any]] = {}
    for family, regime, _difficulty_bin, world_seed in pilot_cells():
        case = build_case(family, regime, world_seed)
        if case["case_id"] in cases:
            raise ValueError(f"duplicate case_id: {case['case_id']!r}")
        cases[case["case_id"]] = case
    return cases


PILOT_ID = "termsbench_pilot_v1"


def build_pilot_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the 30-case pilot manifest and its own content hash."""
    cells = pilot_cells()
    case_ids = [f"{FAMILY_ID}.{family}.{regime}.{seed}" for family, regime, _bin, seed in cells]
    missing = [cid for cid in case_ids if cid not in cases]
    if missing:
        raise ValueError(f"pilot case ids not found in the generated corpus: {missing}")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("pilot case ids are not unique (Gate 1 check #5)")

    data: dict[str, Any] = {
        "pilot_id": PILOT_ID,
        "family_id": FAMILY_ID,
        "case_ids": case_ids,
        "cells": [
            {
                "family": family,
                "regime": regime,
                "difficulty_bin": difficulty_bin,
                "world_seed": world_seed,
                "case_id": case_id,
            }
            for (family, regime, difficulty_bin, world_seed), case_id in zip(cells, case_ids)
        ],
        "content_sha256": "0" * 64,
    }
    digest = _pilot_content_sha256(data)
    data["content_sha256"] = digest
    return data


def _pilot_content_sha256(value: Mapping[str, Any]) -> str:
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


# --------------------------------------------------------------------------
# Disk I/O.
# --------------------------------------------------------------------------


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def write_cases(
    output_dir: Path,
    cases: Mapping[str, Mapping[str, Any]],
    pilot_manifest: Mapping[str, Any],
) -> None:
    """Write one file per case plus the pilot manifest."""
    for case_id, case in cases.items():
        _dump_json(output_dir / f"{case_id}.json", case)
    _dump_json(output_dir / "pilot_manifest.json", pilot_manifest)


def run_generate(output_dir: Path) -> None:
    """End-to-end: generate the 30-case pilot corpus and its manifest."""
    cases = build_pilot_cases()
    pilot_manifest = build_pilot_manifest(cases)
    write_cases(output_dir, cases, pilot_manifest)


def _default_output_dir() -> Path:
    # src/aeread_families/termsbench/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "termsbench" / "pilot"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write the 30 pilot case files and pilot_manifest.json",
    )
    args = parser.parse_args(argv)
    run_generate(args.output_dir)


if __name__ == "__main__":
    main()
