"""Generator v0.2.0: the corpus of the TERMS-Bench reproduction, in the paper's stated geometry.

The plan is ``docs/families/termsbench/reproduction_plan.md`` (identity ``termsbench_repro_v1``, Section 2, TB-D-09).
v0.1.0 (:mod:`.cases`) drew prices on [0, 200] with a ZOPA width U[20, 100], played the buyer only, and chose one
quintile-boundary seed per difficulty bin; this module draws what the paper states (Appendix H.2 and Fig. 21) and
leaves :mod:`.cases` and :mod:`.kernel` unedited, so every published pilot keeps regenerating:

- prices on [0, 100]; an overlap world's ZOPA width ``Delta ~ U[10, 40]``, a no-deal world's gap ``~ U[10, 40]``, the
  midpoint uniform where the interval fits inside the bounds;
- the agent's role and the opener balanced 2 x 2 within each family and regime;
- uniform draws on fresh seeds, no difficulty binning. The difficulty score is still computed (the plugin requires it)
  from the same kernel formulas, with the price range of 100.

The counterpart kernel reads the price range from each case's ``price_bounds`` (``kernel.py``), so the new bounds reach
the counterpart without a kernel change. The draw order per seed is v0.1.0's: the width or gap, the midpoint, the
counterpart's urgency, the agent's urgency, the stance, the opening harshness.

Seeds come from one formula, ``seed(family, regime, role, opener, block, j)``, disjoint from v0.1.0's range
(1,000,000 to 1,299,999) and from the design review's baseline seeds. Block 1 is development (Stages 1 to 3 of the
plan); block 2 is the confirmatory corpus: 48 overlap worlds (3 families x 2 roles x 2 openers x 4) and 12 no-deal
worlds (2 per family and role, one per opener).

Cases carry family version ``0.2.0``: they are played by the reproduction's plugin version
(:mod:`.environment_v2`), never by v0.1.0's.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import cases as v1
from . import kernel as k

FAMILY_ID = v1.FAMILY_ID
FAMILY_VERSION = "0.2.0"
GENERATOR_ID = "termsbench_generator"
GENERATOR_VERSION = "0.2.0"
IDENTITY = "termsbench_repro_v1"

P_MIN, P_MAX = 0.0, 100.0
WIDTH_MIN, WIDTH_MAX = 10.0, 40.0
GAP_MIN, GAP_MAX = 10.0, 40.0
FAMILIES = ("candid", "expressive", "taciturn")
REGIMES = v1.REGIMES
ROLES = ("buyer", "seller")
OPENERS = ("agent_opens", "counterpart_opens")
SEED_BASE = 3_000_000
DEVELOPMENT, CONFIRMATORY = 1, 2
OVERLAP_PER_CELL = 4
NODEAL_PER_FAMILY_ROLE = 2
REPO = Path(__file__).resolve().parents[3]
CASES_DIR = REPO / "cases" / "termsbench" / "repro_v1"


def seed(family: str, regime: str, role: str, opener: str, block: int, j: int) -> int:
    if not 0 <= j < 10 or block not in (DEVELOPMENT, CONFIRMATORY):
        raise ValueError("j must be in [0, 10) and block 1 or 2")
    return (SEED_BASE + 100_000 * FAMILIES.index(family) + 10_000 * REGIMES.index(regime) + 1_000 * ROLES.index(role)
            + 100 * OPENERS.index(opener) + 10 * block + j)


def _geometry(regime: str, rng: np.random.Generator) -> tuple[float, float, float]:
    """(r_buyer, r_seller, the width or gap's percentile), as v0.1.0 draws them on the paper's bounds."""
    u = float(rng.uniform(0.0, 1.0))
    if regime == "overlap":
        z = WIDTH_MIN + u * (WIDTH_MAX - WIDTH_MIN)
        mid = float(rng.uniform(P_MIN + z / 2.0, P_MAX - z / 2.0))
        return mid + z / 2.0, mid - z / 2.0, u
    q = GAP_MIN + u * (GAP_MAX - GAP_MIN)
    mid = float(rng.uniform(P_MIN + q / 2.0, P_MAX - q / 2.0))
    return mid - q / 2.0, mid + q / 2.0, u


def generate_payload(family: str, regime: str, role: str, opener: str, world_seed: int) -> dict[str, Any]:
    if family not in FAMILIES or regime not in REGIMES or role not in ROLES or opener not in OPENERS:
        raise ValueError("unknown family, regime, role or opener")
    rng = np.random.Generator(np.random.PCG64(world_seed))
    r_buyer, r_seller, percentile = _geometry(regime, rng)
    kappa_b = float(rng.beta(k.BETA_KAPPA_ALPHA, k.BETA_KAPPA_BETA))
    kappa_agent = float(rng.beta(k.BETA_KAPPA_ALPHA, k.BETA_KAPPA_BETA))
    eta_b = str(rng.choice(k.STANCE_TYPES))
    opening_harshness = float(rng.uniform(k.D_OPEN_MIN, k.D_OPEN_MAX))
    counterpart_role = "seller" if role == "buyer" else "buyer"
    r_a = r_buyer if role == "buyer" else r_seller
    r_b = r_seller if role == "buyer" else r_buyer
    delta = r_buyer - r_seller
    price_range = P_MAX - P_MIN
    if regime == "overlap":
        difficulty = k.overlap_difficulty(delta=delta, price_range=price_range, kappa_agent=kappa_agent,
                                          kappa_counterpart=kappa_b, eta_b=eta_b)
    else:
        difficulty = k.nodeal_difficulty(delta=delta, sigma_scale=price_range,
                                         cue_channel=k.FAMILY_PRESETS[family]["cue_channel"], eta_b=eta_b)
    # v0.1.0's hyperparameter block is a function of the family alone (its regime and seed do not enter it)
    hyperparameters = v1.generate_payload(family, regime, v1._candidate_seed_base(family, regime))["hyperparameters"]
    return {
        "regime": regime, "family": family, "horizon": k.DEFAULT_HORIZON,
        "agent": {"role": role, "r_a": r_a, "kappa_a": kappa_agent},
        "t_b": {"r_b": r_b, "kappa_b": kappa_b, "eta_b": eta_b},
        "counterpart_role": counterpart_role, "chi": opener,
        "price_bounds": {"p_min": P_MIN, "p_max": P_MAX},
        "opening_harshness": opening_harshness, "geometry_percentile": percentile, "delta": delta,
        "difficulty_score": difficulty, "hyperparameters": hyperparameters,
    }


def build_case(family: str, regime: str, role: str, opener: str, world_seed: int, split: str) -> dict[str, Any]:
    payload = generate_payload(family, regime, role, opener, world_seed)
    case_id = f"{FAMILY_ID}.repro.{family}.{regime}.{role}.{opener.split('_')[0]}.{world_seed}"
    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION, "case_id": case_id, "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION, "split": split, "world_seed": world_seed,
        "seats": [{"id": "agent", "role": "agent"}, {"id": "counterpart", "role": "counterpart"}],
        "episode": {"max_logical_actions": 2 * k.DEFAULT_HORIZON, "termination": v1.TERMINATION_REASONS},
        "visibility_policy": v1.VISIBILITY_POLICY, "payload": payload,
        "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
        "upstream_task_id": None, "content_sha256": "0" * 64,
    }
    data["content_sha256"] = case_content_sha256(data)
    CaseManifest.from_dict(data)
    return data


def corpus(block: int) -> list[dict[str, Any]]:
    """The block's cases: 48 overlap worlds and 12 no-deal worlds, in a fixed order."""
    split = {DEVELOPMENT: "repro_v1_development", CONFIRMATORY: "repro_v1_confirmatory"}[block]
    out = []
    for family in FAMILIES:
        for role in ROLES:
            for opener in OPENERS:
                for j in range(OVERLAP_PER_CELL):
                    out.append(build_case(family, "overlap", role, opener, seed(family, "overlap", role, opener, block, j), split))
            for j, opener in enumerate(OPENERS[:NODEAL_PER_FAMILY_ROLE]):
                out.append(build_case(family, "nodeal", role, opener, seed(family, "nodeal", role, opener, block, j), split))
    return out


def restamped_pilot() -> list[dict[str, Any]]:
    """The 30 published pilot worlds with their v0.1.0 payloads unchanged, as family version 0.2.0 cases (Stage 1: the
    new protocol on the old worlds, so a level shift that closes is the protocol's, not the geometry's)."""
    out = []
    for family, regime, _bin, world_seed in v1.pilot_cells():
        payload = v1.generate_payload(family, regime, world_seed)
        data = {
            "spec_version": CaseManifest.SPEC_VERSION, "case_id": f"{FAMILY_ID}.repro.pilot.{family}.{regime}.{world_seed}",
            "family_id": FAMILY_ID, "family_version": FAMILY_VERSION, "split": "repro_v1_pilot_restamped",
            "world_seed": world_seed,
            "seats": [{"id": "agent", "role": "agent"}, {"id": "counterpart", "role": "counterpart"}],
            "episode": {"max_logical_actions": 2 * k.DEFAULT_HORIZON, "termination": v1.TERMINATION_REASONS},
            "visibility_policy": v1.VISIBILITY_POLICY, "payload": payload,
            "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
            "upstream_task_id": None, "content_sha256": "0" * 64,
        }
        data["content_sha256"] = case_content_sha256(data)
        CaseManifest.from_dict(data)
        out.append(data)
    return out


def files() -> dict[str, str]:
    out = {}
    for name, cases in (("development", corpus(DEVELOPMENT)), ("confirmatory", corpus(CONFIRMATORY)),
                        ("pilot_restamped", restamped_pilot())):
        out[f"{name}.jsonl"] = "".join(json.dumps(c, sort_keys=True, separators=(",", ":")) + "\n" for c in cases)
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    made = files()
    if args.write:
        CASES_DIR.mkdir(parents=True, exist_ok=True)
        for name, text in made.items():
            (CASES_DIR / name).write_text(text)
        print(f"wrote {len(made)} files to {CASES_DIR}")
    if args.check:
        differ = [n for n, t in made.items() if not (CASES_DIR / n).is_file() or (CASES_DIR / n).read_text() != t]
        print("differs: " + ", ".join(differ) if differ else f"identical: {len(made)} files")
        return 1 if differ else 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
