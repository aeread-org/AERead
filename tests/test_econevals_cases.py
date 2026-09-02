"""Tests for the econevals foundation stage: pins, importer, corpus admission.

Follows the same ``_bridge()``/skip convention as
``tests/test_tau3_retail_environment.py``: pure structural tests (module
hashes, checked-in case shapes, digest stability, id grammar) run everywhere;
tests that actually generate an instance through the pinned upstream
checkout run for real when a bridge interpreter is provisioned, and are
skipped (never faked) otherwise. See ``conftest.py`` for how
``AEREAD_ECONEVALS_BRIDGE_REQUIRED=1`` turns such a skip into a failure for
a run meant to certify this corpus.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.econevals import cases as econevals_cases
from aeread_families.econevals.econevals_bridge import (
    EconevalsBridge,
    EconevalsBridgeUnavailableError,
    GurobiLicenseSizeError,
    discover_bridge_python,
)

UPSTREAM_ROOT = Path("/Users/sunzeyu/Documents/econ benchmark/upstream-econevals")
CASES_DIR = Path("cases/econevals")

_NO_COLON_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]*[a-z0-9])?$")


def _upstream_available() -> bool:
    return (UPSTREAM_ROOT / "econ_evals" / "__init__.py").is_file()


try:
    BRIDGE_PYTHON = discover_bridge_python()
except EconevalsBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> EconevalsBridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return EconevalsBridge(python_executable=BRIDGE_PYTHON)


# ---------------------------------------------------------------------------
# Governing facts / pin constants (spec section 1).
# ---------------------------------------------------------------------------


def test_pinned_commit_and_repo_constants() -> None:
    assert econevals_cases.UPSTREAM_REPO == "econ-evals-paper"
    assert econevals_cases.UPSTREAM_COMMIT == "e1f2a40fec96f0d27f5414873c4310f2b5c51935"


def test_module_sha256_table_has_the_seven_governing_modules() -> None:
    assert set(econevals_cases.MODULE_SHA256) == {
        "experiments/procurement/generate_instance.py",
        "experiments/procurement/opt_solver.py",
        "experiments/scheduling/generate_preferences.py",
        "experiments/scheduling/stable_matching_environment.py",
        "experiments/pricing/generate_instance.py",
        "experiments/pricing/pricing_market_logic_multiproduct.py",
        "utils/helper_functions.py",
    }
    for digest in econevals_cases.MODULE_SHA256.values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)


@pytest.mark.skipif(not _upstream_available(), reason="pinned upstream checkout not found")
def test_module_sha256_table_matches_the_checkout_on_disk() -> None:
    mismatches = econevals_cases.verify_module_sha256(UPSTREAM_ROOT)
    assert mismatches == {}


def test_seed_lists_match_the_spec() -> None:
    assert econevals_cases.PROCUREMENT_SEEDS == tuple(range(8))
    assert econevals_cases.SCHEDULING_SEEDS == tuple(range(12))
    assert econevals_cases.PRICING_SEEDS == tuple(range(8))


def test_scheduling_seeds_cover_all_four_preference_regimes_three_times_each() -> None:
    regimes = [
        econevals_cases._scheduling_score_gaps(seed) for seed in econevals_cases.SCHEDULING_SEEDS
    ]
    assert len(set(regimes)) == 4
    for regime in set(regimes):
        assert regimes.count(regime) == 3


def test_pricing_env_type_alternates_by_seed_parity() -> None:
    for seed in econevals_cases.PRICING_SEEDS:
        expected = "linear_shifts" if seed % 2 == 0 else "periodic_shifts"
        assert econevals_cases._pricing_env_type(seed) == expected
    even = sum(1 for seed in econevals_cases.PRICING_SEEDS if seed % 2 == 0)
    assert even == 4


# ---------------------------------------------------------------------------
# CaseManifest construction (no bridge needed: uses hand-built instances).
# ---------------------------------------------------------------------------


def _stub_procurement_instance() -> dict:
    return {
        "menu": {
            "Offer_1": {"type": "basic", "contents": {"A1": 1}, "cost": 5.0},
        },
        "budget": 10.0,
        "item_groups": [["A1"]],
        "start_alloc": {"Offer_1": 1},
        "item_to_effectiveness": {"A1": 1},
        "group_weights": [1.0],
        "agg_type": "prod",
    }


def _stub_gold_optimum() -> dict:
    return {
        "opt_alloc": {"Offer_1": 1},
        "opt_cost": 5.0,
        "opt_utility": 1.0,
        "opt_value": 0.0,
        "is_feasible": True,
        "invalid_reason": "",
    }


def test_case_id_has_no_colon_and_matches_the_dot_separated_grammar() -> None:
    case = econevals_cases.build_case(
        track="procurement",
        seed=7,
        generated_instance=_stub_procurement_instance(),
        gold_optimum=_stub_gold_optimum(),
        pins=econevals_cases.build_pins(),
    )
    assert case["case_id"] == "econevals.procurement.basic.7"
    assert ":" not in case["case_id"]
    assert _NO_COLON_RE.fullmatch(case["case_id"])
    assert _NO_COLON_RE.fullmatch(case["split"])


def test_case_round_trips_through_the_strict_case_manifest_grammar() -> None:
    case = econevals_cases.build_case(
        track="procurement",
        seed=0,
        generated_instance=_stub_procurement_instance(),
        gold_optimum=_stub_gold_optimum(),
        pins=econevals_cases.build_pins(),
    )
    manifest = CaseManifest.from_dict(case)
    assert manifest.family_id == "econevals"
    assert manifest.upstream_task_id is None
    assert manifest.content_sha256 == case_content_sha256(case)


def test_unknown_track_is_rejected() -> None:
    with pytest.raises(ValueError):
        econevals_cases.build_case(
            track="not_a_track",
            seed=0,
            generated_instance=_stub_procurement_instance(),
            gold_optimum=_stub_gold_optimum(),
            pins=econevals_cases.build_pins(),
        )


def test_a_malformed_generated_instance_fails_case_manifest_validation() -> None:
    bad_instance = {"not_json_safe": object()}
    with pytest.raises((AuthoringValidationError, TypeError)):
        econevals_cases.build_case(
            track="procurement",
            seed=0,
            generated_instance=bad_instance,
            gold_optimum=_stub_gold_optimum(),
            pins=econevals_cases.build_pins(),
        )


# ---------------------------------------------------------------------------
# Checked-in corpus (spec section 1's 28-instance pilot): static properties.
# ---------------------------------------------------------------------------


def _load_checked_in_manifest() -> dict:
    manifest_path = CASES_DIR / "manifest.json"
    if not manifest_path.is_file():
        pytest.skip(f"no checked-in econevals corpus found under {CASES_DIR}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_checked_in_corpus_has_exactly_28_instances_across_three_splits() -> None:
    manifest = _load_checked_in_manifest()
    entries = manifest["cases"]
    assert len(entries) == 28
    by_split = {}
    for entry in entries:
        by_split.setdefault(entry["split"], []).append(entry)
    assert len(by_split["procurement_basic"]) == 8
    assert len(by_split["scheduling_basic"]) == 12
    assert len(by_split["pricing_basic"]) == 8


def test_checked_in_corpus_case_ids_are_unique_and_colon_free() -> None:
    manifest = _load_checked_in_manifest()
    case_ids = [entry["case_id"] for entry in manifest["cases"]]
    assert len(case_ids) == len(set(case_ids))
    for case_id in case_ids:
        assert ":" not in case_id
        assert _NO_COLON_RE.fullmatch(case_id)


def test_checked_in_case_files_round_trip_and_match_their_manifest_digest() -> None:
    manifest = _load_checked_in_manifest()
    for entry in manifest["cases"]:
        path = CASES_DIR / entry["split"] / f"{entry['case_id']}.json"
        assert path.is_file(), f"missing case file for {entry['case_id']}"
        data = json.loads(path.read_text(encoding="utf-8"))
        manifest_obj = CaseManifest.from_dict(data)
        assert manifest_obj.case_id == entry["case_id"]
        assert manifest_obj.content_sha256 == entry["content_sha256"]
        assert case_content_sha256(data) == entry["content_sha256"]
        assert manifest_obj.upstream_task_id is None
        assert manifest_obj.family_id == "econevals"
        assert manifest_obj.family_version == "0.1.0"


def test_checked_in_pins_json_matches_the_frozen_module_hash_table() -> None:
    pins_path = CASES_DIR / "pins.json"
    if not pins_path.is_file():
        pytest.skip(f"no checked-in pins.json found under {CASES_DIR}")
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    assert pins["upstream_commit"] == econevals_cases.UPSTREAM_COMMIT
    assert pins["module_sha256"] == dict(econevals_cases.MODULE_SHA256)
    assert pins["max_steps"] == 100
    assert pins["max_llm_queries_per_period"] == 40


def test_manifest_content_sha256_is_stable_under_rehash() -> None:
    manifest = _load_checked_in_manifest()
    digest = manifest["content_sha256"]
    assert econevals_cases._manifest_content_sha256(manifest) == digest


# ---------------------------------------------------------------------------
# Gate 1 (corpus admission): generation is byte-reproducible across two
# independent bridge subprocesses; Gurobi resolves every procurement seed;
# this is the regression test for the procurement RNG finding (spec section
# 1/5) -- it must fail loudly if the fresh-subprocess convention is ever
# dropped.
# ---------------------------------------------------------------------------


def test_procurement_generation_is_byte_reproducible_across_fresh_subprocesses() -> None:
    bridge = _bridge()
    kwargs = dict(
        seed=0,
        num_inputs=econevals_cases.PROCUREMENT_PARAMS["num_inputs"],
        num_alternatives_per_input=econevals_cases.PROCUREMENT_PARAMS["num_alternatives_per_input"],
        num_entries=econevals_cases.PROCUREMENT_PARAMS["num_entries"],
        num_items_per_entry_p=econevals_cases.PROCUREMENT_PARAMS["num_items_per_entry_p"],
        quantity_per_item_p=econevals_cases.PROCUREMENT_PARAMS["quantity_per_item_p"],
        offer_qty_in_sample_bundle_p=econevals_cases.PROCUREMENT_PARAMS["offer_qty_in_sample_bundle_p"],
        min_effectiveness=econevals_cases.PROCUREMENT_PARAMS["min_effectiveness"],
        max_effectiveness=econevals_cases.PROCUREMENT_PARAMS["max_effectiveness"],
    )
    first = bridge.generate_procurement_instance(**kwargs)
    second = bridge.generate_procurement_instance(**kwargs)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(
        second, sort_keys=True, default=str
    )
    # The specific measured value from recon (spec's "Governing facts"):
    # same-seed budget is 109.77 when generation is clean.
    assert first["budget"] == 109.77


def test_build_corpus_admits_all_28_pilot_instances_with_no_exclusions() -> None:
    bridge = _bridge()
    result = econevals_cases.build_corpus(bridge, strict=False)
    assert result.exclusions == ()
    assert len(result.cases) == 28
    by_split: dict[str, int] = {}
    for case in result.cases.values():
        by_split[case["split"]] = by_split.get(case["split"], 0) + 1
    assert by_split == {
        "procurement_basic": 8,
        "scheduling_basic": 12,
        "pricing_basic": 8,
    }


def test_gurobi_resolves_every_basic_procurement_seed_without_a_license_error() -> None:
    bridge = _bridge()
    for seed in econevals_cases.PROCUREMENT_SEEDS:
        generated_instance, gold_optimum, exclusion = econevals_cases._build_procurement_candidate(
            bridge, seed
        )
        assert exclusion is None, f"seed {seed} excluded: {exclusion}"
        assert gold_optimum["is_feasible"] is True
        assert not isinstance(exclusion, GurobiLicenseSizeError)


def test_scheduling_gold_optimum_is_the_analytic_gale_shapley_existence_claim() -> None:
    bridge = _bridge()
    _instance, gold_optimum, exclusion = econevals_cases._build_scheduling_candidate(bridge, 0)
    assert exclusion is None
    assert gold_optimum == {
        "reference_kind": "analytic_existence",
        "claim": "gale_shapley_stable_matching_exists",
        "min_blocking_pairs": 0,
    }


def test_pricing_gold_optimum_covers_every_period() -> None:
    bridge = _bridge()
    instance, gold_optimum, exclusion = econevals_cases._build_pricing_candidate(bridge, 0)
    assert exclusion is None
    num_periods = econevals_cases.PRICING_PARAMS["num_attempts"]
    assert len(gold_optimum["prices_by_period"]) == num_periods
    assert len(gold_optimum["profits_by_period"]) == num_periods
    assert len(instance["alpha_list"]) == num_periods


def test_checked_in_corpus_matches_a_fresh_build_byte_for_byte() -> None:
    """Cross-check: the checked-in ``cases/econevals`` corpus is not stale."""
    manifest = _load_checked_in_manifest()
    bridge = _bridge()
    result = econevals_cases.build_corpus(bridge, strict=True)
    fresh_ids = {case["case_id"]: case["content_sha256"] for case in result.cases.values()}
    checked_in_ids = {entry["case_id"]: entry["content_sha256"] for entry in manifest["cases"]}
    assert fresh_ids == checked_in_ids
