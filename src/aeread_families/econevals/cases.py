"""Importer: pinned upstream ``econ-evals-paper`` generators -> AERead cases.

Unlike tau3.retail's fixed 114-task corpus, EconEvals is GENERATOR-based:
``run_<track>_batch.py`` takes a ``(difficulty, seed)`` pair and
deterministically builds one instance via ``generate_instance``
(procurement/pricing) or ``generate_preferences`` (scheduling). This module
enumerates tonight's pilot corpus -- 28 Basic-difficulty instances (8
procurement + 12 scheduling + 8 pricing seeds) -- admits each candidate only
after proving it is byte-reproducible across two independent bridge
subprocess calls, computes each track's exact-optimum reference by
delegating to upstream's own solver, and writes one ``CaseManifest`` JSON
file per admitted instance plus a shared ``pins.json`` and a corpus
``manifest.json``. See ``docs/econevals_adapter_spec.md`` section 1 for the
governing spec this module implements.

This module never reimplements an upstream generator or solver: every
instance-generation and gold-optimum call is delegated to
``EconevalsBridge``, which runs the pinned upstream checkout in a fresh
subprocess per call (see ``econevals_bridge.py``'s module docstring for why
that is not a style choice: procurement's own generator leaks global-RNG
state into its ``budget`` field otherwise).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .econevals_bridge import EconevalsBridge, GurobiLicenseSizeError

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "econevals"
FAMILY_VERSION = "0.1.0"
CASE_ID_PREFIX = "econevals"
DIFFICULTY = "Basic"

TRACKS: tuple[str, ...] = ("procurement", "scheduling", "pricing")

# Every reason this family's environment can terminate for, and nothing
# else -- declared here, next to the manifest that publishes it, and
# enforced by ``environment.py`` so the declaration and the behaviour cannot
# drift apart (mirroring tau3.retail's identical convention for
# ``TERMINATION_REASONS``).
TERMINATION_REASONS = ("max_periods", "error")

MAX_STEPS = 100
MAX_LLM_QUERIES_PER_PERIOD = 40

VISIBILITY_POLICY = "econevals_full_observability_v1"

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1). Frozen at the pinned commit; any
# change to these upstream files invalidates the pilot manifest.
# --------------------------------------------------------------------------

UPSTREAM_REPO = "econ-evals-paper"
UPSTREAM_COMMIT = "e1f2a40fec96f0d27f5414873c4310f2b5c51935"
UPSTREAM_LICENSE = "MIT"

MODULE_SHA256: Mapping[str, str] = {
    "experiments/procurement/generate_instance.py": (
        "75507abd848762751b08d16cfc4ec1fdc5f1d76d51cb995fd438fab0c9e97aee"
    ),
    "experiments/procurement/opt_solver.py": (
        "e2710eadb1ea8ab77125e1d5276516aef67a5424e98bb56673d4fd82babab892"
    ),
    "experiments/scheduling/generate_preferences.py": (
        "a932725fb1c4c9172bab3dd0321a59604e269b04770a96ebdd92e5f631041b56"
    ),
    "experiments/scheduling/stable_matching_environment.py": (
        "6e44d8150941bdff8903dc49ac29994e50c0b4687836c6ca35d562ab23e1b128"
    ),
    "experiments/pricing/generate_instance.py": (
        "45d7743df9a6570c380054f0a12767b295b848004930de3bc9665f3572ce35fe"
    ),
    "experiments/pricing/pricing_market_logic_multiproduct.py": (
        "b2bac943c421d084258bd931d25f22591360c91097a51ab7e716857cb07f1723"
    ),
    "utils/helper_functions.py": (
        "25487b34700c435c2ff35e76104f9647122b43a088f025857e6dc09c744d0506"
    ),
}

# --------------------------------------------------------------------------
# Basic-difficulty generation parameters, one block per track (spec section
# 1). These are shared across every seed of a track -- only ``seed`` (and,
# for scheduling, the seed-derived preference regime) varies per instance.
# Verbatim upstream literals below are sourced by READING the pinned
# checkout's own batch scripts (run_<track>_batch.py), never by guessing.
# --------------------------------------------------------------------------

PROCUREMENT_SEEDS: tuple[int, ...] = tuple(range(8))
PROCUREMENT_PARAMS: Mapping[str, Any] = {
    "num_inputs": 3,
    "num_alternatives_per_input": 4,
    "num_entries": 12,
    "num_items_per_entry_p": 0.8,
    "quantity_per_item_p": 0.5,
    "offer_qty_in_sample_bundle_p": 0.5,
    "min_effectiveness": 1,
    "max_effectiveness": 3,
    "agg_type": "prod",
}


def _procurement_group_weights() -> list[float]:
    num_inputs = PROCUREMENT_PARAMS["num_inputs"]
    return [1 / num_inputs for _ in range(num_inputs)]


SCHEDULING_SEEDS: tuple[int, ...] = tuple(range(12))
SCHEDULING_PARAMS: Mapping[str, Any] = {
    "num_workers": 10,
    "num_blocking_pairs": 1,
    "blocking_pair_selection_method": "random_cache",
}
# run_scheduling_batch.py's own PREFERENCE_GENERATION_PARAMS, each
# replicated 3x -- seeds 0..11 cycle through all 4 regimes exactly 3 times
# each (spec section 1's "full regime balance" claim).
_SCHEDULING_PREFERENCE_REGIMES: tuple[Mapping[str, float | None], ...] = (
    {"score_gap_worker": 1, "score_gap_task": 1},
    {"score_gap_worker": 3, "score_gap_task": 3},
    {"score_gap_worker": None, "score_gap_task": 3},
    {"score_gap_worker": None, "score_gap_task": 1},
)
_SCHEDULING_SCORE_GAP_WORKER_REPLICATION: tuple[float | None, ...] = tuple(
    regime["score_gap_worker"] for regime in _SCHEDULING_PREFERENCE_REGIMES for _ in range(3)
)
_SCHEDULING_SCORE_GAP_TASK_REPLICATION: tuple[float | None, ...] = tuple(
    regime["score_gap_task"] for regime in _SCHEDULING_PREFERENCE_REGIMES for _ in range(3)
)


def _scheduling_score_gaps(seed: int) -> tuple[float | None, float | None]:
    index = seed % len(_SCHEDULING_SCORE_GAP_WORKER_REPLICATION)
    return (
        _SCHEDULING_SCORE_GAP_WORKER_REPLICATION[index],
        _SCHEDULING_SCORE_GAP_TASK_REPLICATION[index],
    )


PRICING_SEEDS: tuple[int, ...] = tuple(range(8))
PRICING_PARAMS: Mapping[str, Any] = {
    "num_products": 1,
    "noise_param": 0.0,
    "sigma": 0.5,
    "mu": 1.0,
    "start_multiplier": 100.0,
    "group_idx_p": 0.2,
    "group_idx_cutoff_proportion": 0.25,
    "num_attempts": 100,
}


def _pricing_product_ids() -> list[str]:
    return [f"Product_{i}" for i in range(1, PRICING_PARAMS["num_products"] + 1)]


def _pricing_env_type(seed: int) -> str:
    # run_pricing_batch.py: ENV_TYPES[seed % 2], ENV_TYPES = ["linear_shifts", "periodic_shifts"].
    return "linear_shifts" if seed % 2 == 0 else "periodic_shifts"


# --------------------------------------------------------------------------
# Typed corpus-admission exclusions (spec section 1: "log as a typed
# exclusion ... never a silent drop").
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseExclusion:
    track: str
    seed: int
    reason: str
    detail: Mapping[str, Any]


class CorpusAdmissionError(RuntimeError):
    """Raised by ``build_corpus`` when ``strict=True`` and a candidate is excluded."""

    def __init__(self, exclusion: CaseExclusion) -> None:
        self.exclusion = exclusion
        super().__init__(
            f"{exclusion.track} seed={exclusion.seed} excluded: {exclusion.reason}"
        )


def _canonical_generator_json(value: Any) -> str:
    """Byte-compare form for double-generation checks (spec section 1, step 1).

    Deliberately upstream's own canonicalization convention
    (``json.dumps(..., sort_keys=True, default=str)``), NOT the kernel's
    stricter ``canonical_json_bytes`` (which rejects anything that is not
    already JSON-safe) -- this check runs on raw bridge output, before it is
    known to be JSON-safe, and ``default=str`` is what makes a mismatch
    surface as a readable diff instead of a ``TypeError``.
    """
    return json.dumps(value, sort_keys=True, default=str)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# pins.json
# --------------------------------------------------------------------------


def build_pins() -> dict[str, Any]:
    """Build the shared pin record (spec section 1)."""
    return {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_license": UPSTREAM_LICENSE,
        "module_sha256": dict(MODULE_SHA256),
        "difficulty": DIFFICULTY,
        "max_steps": MAX_STEPS,
        "max_llm_queries_per_period": MAX_LLM_QUERIES_PER_PERIOD,
        "procurement_params": dict(PROCUREMENT_PARAMS),
        "scheduling_params": dict(SCHEDULING_PARAMS),
        "pricing_params": dict(PRICING_PARAMS),
    }


def verify_module_sha256(upstream_root: Path) -> dict[str, str]:
    """Recompute each pinned module's sha256 against the checkout on disk.

    Returns ``{relative_path: mismatch_description}`` -- empty when every
    pinned hash matches. Never silently trusts ``MODULE_SHA256``; this is
    what makes an upstream re-checkout at a stale or drifted commit fail
    loudly instead of silently building a manifest whose governing-facts
    hashes no longer describe the code that actually ran.
    """
    mismatches: dict[str, str] = {}
    for relative_path, expected in MODULE_SHA256.items():
        path = upstream_root / "econ_evals" / relative_path
        if not path.is_file():
            mismatches[relative_path] = f"missing at {path}"
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            mismatches[relative_path] = f"expected {expected}, got {actual}"
    return mismatches


# --------------------------------------------------------------------------
# Per-track candidate builders (spec section 1's build procedure).
# --------------------------------------------------------------------------


def _build_procurement_candidate(
    bridge: EconevalsBridge, seed: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, CaseExclusion | None]:
    kwargs = dict(
        seed=seed,
        num_inputs=PROCUREMENT_PARAMS["num_inputs"],
        num_alternatives_per_input=PROCUREMENT_PARAMS["num_alternatives_per_input"],
        num_entries=PROCUREMENT_PARAMS["num_entries"],
        num_items_per_entry_p=PROCUREMENT_PARAMS["num_items_per_entry_p"],
        quantity_per_item_p=PROCUREMENT_PARAMS["quantity_per_item_p"],
        offer_qty_in_sample_bundle_p=PROCUREMENT_PARAMS["offer_qty_in_sample_bundle_p"],
        min_effectiveness=PROCUREMENT_PARAMS["min_effectiveness"],
        max_effectiveness=PROCUREMENT_PARAMS["max_effectiveness"],
    )
    first = bridge.generate_procurement_instance(**kwargs)
    second = bridge.generate_procurement_instance(**kwargs)
    canon_first = _canonical_generator_json(first)
    canon_second = _canonical_generator_json(second)
    if canon_first != canon_second:
        return None, None, CaseExclusion(
            track="procurement",
            seed=seed,
            reason="generation_not_reproducible",
            detail={
                "digest_first": _sha256_hex(canon_first),
                "digest_second": _sha256_hex(canon_second),
            },
        )

    group_weights = _procurement_group_weights()
    try:
        gold_optimum = bridge.procurement_reference(
            instance=first, group_weights=group_weights, agg_type=PROCUREMENT_PARAMS["agg_type"]
        )
    except GurobiLicenseSizeError as error:
        return None, None, CaseExclusion(
            track="procurement",
            seed=seed,
            reason="gurobi_license_size",
            detail={"message": str(error)},
        )
    if not gold_optimum["is_feasible"]:
        return None, None, CaseExclusion(
            track="procurement",
            seed=seed,
            reason="opt_alloc_infeasible",
            detail={"invalid_reason": gold_optimum["invalid_reason"]},
        )

    generated_instance = {
        **first,
        "group_weights": group_weights,
        "agg_type": PROCUREMENT_PARAMS["agg_type"],
    }
    return generated_instance, gold_optimum, None


def _build_scheduling_candidate(
    bridge: EconevalsBridge, seed: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, CaseExclusion | None]:
    score_gap_worker, score_gap_task = _scheduling_score_gaps(seed)
    kwargs = dict(
        seed=seed,
        num_workers=SCHEDULING_PARAMS["num_workers"],
        score_gap_worker=score_gap_worker,
        score_gap_task=score_gap_task,
    )
    first = bridge.generate_scheduling_instance(**kwargs)
    second = bridge.generate_scheduling_instance(**kwargs)
    canon_first = _canonical_generator_json(first)
    canon_second = _canonical_generator_json(second)
    if canon_first != canon_second:
        return None, None, CaseExclusion(
            track="scheduling",
            seed=seed,
            reason="generation_not_reproducible",
            detail={
                "digest_first": _sha256_hex(canon_first),
                "digest_second": _sha256_hex(canon_second),
            },
        )

    generated_instance = {
        **first,
        "score_gap_worker": score_gap_worker,
        "score_gap_task": score_gap_task,
    }
    # Scheduling has no upstream optimum SOLVER (spec's "Governing facts"):
    # the reference is the Gale-Shapley existence theorem, an analytic claim
    # that a 0-blocking-pair stable matching is always attainable for a
    # regular one-to-one assignment market -- never computed per instance.
    gold_optimum = {
        "reference_kind": "analytic_existence",
        "claim": "gale_shapley_stable_matching_exists",
        "min_blocking_pairs": 0,
    }
    return generated_instance, gold_optimum, None


def _build_pricing_candidate(
    bridge: EconevalsBridge, seed: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, CaseExclusion | None]:
    kwargs = dict(
        seed=seed,
        num_products=PRICING_PARAMS["num_products"],
        noise_param=PRICING_PARAMS["noise_param"],
        sigma=PRICING_PARAMS["sigma"],
        mu=PRICING_PARAMS["mu"],
        start_multiplier=PRICING_PARAMS["start_multiplier"],
        group_idx_p=PRICING_PARAMS["group_idx_p"],
        group_idx_cutoff_proportion=PRICING_PARAMS["group_idx_cutoff_proportion"],
        num_attempts=PRICING_PARAMS["num_attempts"],
        product_ids=_pricing_product_ids(),
        env_type=_pricing_env_type(seed),
    )
    first = bridge.generate_pricing_instance(**kwargs)
    second = bridge.generate_pricing_instance(**kwargs)
    canon_first = _canonical_generator_json(first)
    canon_second = _canonical_generator_json(second)
    if canon_first != canon_second:
        return None, None, CaseExclusion(
            track="pricing",
            seed=seed,
            reason="generation_not_reproducible",
            detail={
                "digest_first": _sha256_hex(canon_first),
                "digest_second": _sha256_hex(canon_second),
            },
        )

    gold_optimum = bridge.pricing_reference(instance=first)
    return first, gold_optimum, None


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1's case-manifest field table).
# --------------------------------------------------------------------------


def _split_for_track(track: str) -> str:
    return f"{track}_basic"


def build_case(
    *, track: str, seed: int, generated_instance: Mapping[str, Any], gold_optimum: Mapping[str, Any], pins: Mapping[str, Any]
) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one admitted (track, seed) instance."""
    if track not in TRACKS:
        raise ValueError(f"unknown track: {track!r}")
    case_id = f"{CASE_ID_PREFIX}.{track}.basic.{seed}"

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": _split_for_track(track),
        "world_seed": seed,
        "seats": [{"id": "agent", "role": "assistant"}],
        "episode": {
            "max_logical_actions": MAX_STEPS,
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "track": track,
            "difficulty": DIFFICULTY,
            "seed": seed,
            "generated_instance": dict(generated_instance),
            "gold_optimum": dict(gold_optimum),
            "pins": dict(pins),
        },
        "provenance": {
            "generator_id": "econevals_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        # EconEvals has no upstream task list to key off (generator-based
        # corpus, spec section 1): the natural key is (track, difficulty,
        # seed), already carried in payload -- a schema-shape gap, not
        # silently worked around.
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (mirrors tau3.retail's identical paranoia check).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


# --------------------------------------------------------------------------
# Full corpus build.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusBuildResult:
    pins: dict[str, Any]
    cases: dict[str, dict[str, Any]]
    exclusions: tuple[CaseExclusion, ...]


def build_corpus(bridge: EconevalsBridge, *, strict: bool = False) -> CorpusBuildResult:
    """Build every admitted (track, Basic, seed) case in the pilot corpus.

    With ``strict=True``, the first exclusion raises ``CorpusAdmissionError``
    instead of being recorded -- for a production build that must fail
    loudly. The default (``strict=False``) records every exclusion and keeps
    going, so a single non-reproducible seed does not hide how the rest of
    the corpus fared (spec section 1: "log as a typed exclusion ... never a
    silent drop").
    """
    pins = build_pins()
    cases: dict[str, dict[str, Any]] = {}
    exclusions: list[CaseExclusion] = []

    for seed in PROCUREMENT_SEEDS:
        generated_instance, gold_optimum, exclusion = _build_procurement_candidate(bridge, seed)
        if exclusion is not None:
            if strict:
                raise CorpusAdmissionError(exclusion)
            exclusions.append(exclusion)
            continue
        case = build_case(
            track="procurement",
            seed=seed,
            generated_instance=generated_instance,
            gold_optimum=gold_optimum,
            pins=pins,
        )
        cases[case["case_id"]] = case

    for seed in SCHEDULING_SEEDS:
        generated_instance, gold_optimum, exclusion = _build_scheduling_candidate(bridge, seed)
        if exclusion is not None:
            if strict:
                raise CorpusAdmissionError(exclusion)
            exclusions.append(exclusion)
            continue
        case = build_case(
            track="scheduling",
            seed=seed,
            generated_instance=generated_instance,
            gold_optimum=gold_optimum,
            pins=pins,
        )
        cases[case["case_id"]] = case

    for seed in PRICING_SEEDS:
        generated_instance, gold_optimum, exclusion = _build_pricing_candidate(bridge, seed)
        if exclusion is not None:
            if strict:
                raise CorpusAdmissionError(exclusion)
            exclusions.append(exclusion)
            continue
        case = build_case(
            track="pricing",
            seed=seed,
            generated_instance=generated_instance,
            gold_optimum=gold_optimum,
            pins=pins,
        )
        cases[case["case_id"]] = case

    return CorpusBuildResult(pins=pins, cases=cases, exclusions=tuple(exclusions))


# --------------------------------------------------------------------------
# Corpus manifest (task-corpus enumeration with per-task content digests).
# --------------------------------------------------------------------------

MANIFEST_ID = "econevals_pilot_v1"


def build_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the corpus enumeration: every admitted case id, split, and digest."""
    entries = [
        {
            "case_id": case["case_id"],
            "split": case["split"],
            "world_seed": case["world_seed"],
            "content_sha256": case["content_sha256"],
        }
        for case in sorted(cases.values(), key=lambda case: case["case_id"])
    ]
    data: dict[str, Any] = {
        "manifest_id": MANIFEST_ID,
        "family_id": FAMILY_ID,
        "cases": entries,
        "content_sha256": "0" * 64,
    }
    digest = _manifest_content_sha256(data)
    data["content_sha256"] = digest
    return data


def _manifest_content_sha256(value: Mapping[str, Any]) -> str:
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
    pins: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> None:
    """Write ``pins.json``, one file per case (split into per-track subdirs), and ``manifest.json``."""
    _dump_json(output_dir / "pins.json", pins)
    _dump_json(output_dir / "manifest.json", manifest)
    for case in cases.values():
        split_dir = output_dir / case["split"]
        _dump_json(split_dir / f"{case['case_id']}.json", case)


def run_import(output_dir: Path, *, bridge: EconevalsBridge | None = None) -> CorpusBuildResult:
    """End-to-end: build the pilot corpus and write it to ``output_dir``.

    Raises :class:`CorpusAdmissionError` on the first excluded candidate
    (production builds must fail loudly, not silently ship a partial
    corpus).
    """
    resolved_bridge = bridge if bridge is not None else EconevalsBridge.discover()
    result = build_corpus(resolved_bridge, strict=True)
    manifest = build_manifest(result.cases)
    write_cases(output_dir, result.pins, result.cases, manifest)
    return result


def _default_output_dir() -> Path:
    # src/aeread_families/econevals/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "econevals"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json, manifest.json, and one case file per admitted instance",
    )
    args = parser.parse_args(argv)
    run_import(args.output_dir)


if __name__ == "__main__":
    main()
