"""Tests for the agenticpay.bilateral foundation stage: pins, importer, cases.

These tests exercise the real pinned upstream checkout on disk (read-only,
plain file reads and ``ast``-based static extraction only -- never imports or
executes upstream source). Where a computed value is asserted, it is
compared against upstream's own governing facts
(docs/agenticpay_adapter_spec.md) or against the kernel's own resolver
helpers -- never a value this test suite invents.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.agenticpay_bilateral import cases as ap_cases


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AGENTICPAY_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-agenticpay",
    )
    root = Path(candidate)
    marker = root / "agenticpay" / "envs" / "single_buyer_product_seller" / "Task1_basic_price_negotiation.py"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream AgenticPay checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent -- a module-level skip without this flag
            # is treated as a collection error, not a skip.
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()


# ---------------------------------------------------------------------------
# Governing facts about the upstream corpus (spec section 1/"Governing facts").
# ---------------------------------------------------------------------------


def test_enumerate_basic_env_files_finds_exactly_3() -> None:
    files = ap_cases.enumerate_basic_env_files(UPSTREAM_ROOT)
    assert [path.name for path in files] == [
        "Task1_basic_price_negotiation.py",
        "Task2_close_price_negotiation.py",
        "Task3_close_to_market_price_negotiation.py",
    ]


def test_enumerate_realistic_driver_files_finds_exactly_25_sorted_by_scenario_number() -> None:
    matches = ap_cases.enumerate_realistic_driver_files(UPSTREAM_ROOT)
    assert [num for num, _sid, _path in matches] == list(range(1, 26))
    assert matches[0][1] == "s01_beauty_product"
    assert matches[-1][1] == "s25_rent_house_5"
    # A naive substring match ("Task1_basic_price_negotiation_sglang_example.py"
    # contains "_s" as part of "_sglang") must not leak into this enumeration.
    assert all("sglang" not in path.name for _num, _sid, path in matches)
    assert all("api_example" not in path.name for _num, _sid, path in matches)
    assert all("vllm_example" not in path.name for _num, _sid, path in matches)


def test_enumerated_counts_match_the_spec_exactly() -> None:
    counts = ap_cases.enumerated_counts(UPSTREAM_ROOT)
    assert counts == {
        "basic_bilateral": 3,
        "realistic_bilateral": 25,
        "basic_total": 31,
        "realistic_total_examples_dir": 200,
        "text_only_bilateral": 25,
    }


def test_parse_env_registration_resolves_the_three_basic_ids() -> None:
    table = ap_cases.parse_env_registration(UPSTREAM_ROOT)
    assert table["Task1_basic_price_negotiation-v0"] == (
        "agenticpay.envs.single_buyer_product_seller.Task1_basic_price_negotiation",
        "Task1BasicPriceNegotiation",
    )
    assert table["Task2_close_price_negotiation-v0"] == (
        "agenticpay.envs.single_buyer_product_seller.Task2_close_price_negotiation",
        "Task2ClosePriceNegotiation",
    )
    assert table["Task3_close_to_market_price_negotiation-v0"] == (
        "agenticpay.envs.single_buyer_product_seller.Task3_close_to_market_price_negotiation",
        "Task3CloseToMarketPriceNegotiation",
    )


def test_load_examples_config_matches_upstream_source() -> None:
    config = ap_cases.load_examples_config(UPSTREAM_ROOT)
    assert config["max_rounds"] == 20
    assert config["price_tolerance"] == 0.0
    assert config["reward_weights"] == {
        "buyer_savings": 1.0,
        "seller_profit": 1.0,
        "time_cost": 0.1,
    }


# ---------------------------------------------------------------------------
# pins.json
# ---------------------------------------------------------------------------


def test_build_pins_facts() -> None:
    pins = ap_cases.build_pins(UPSTREAM_ROOT)
    assert pins["upstream_repo"] == "SafeRL-Lab/AgenticPay"
    assert pins["upstream_commit"] == "1ff4e1a2686eac6a07ff559df6d50329c6fd9f69"
    assert pins["upstream_license"] == "MIT"
    assert set(pins["env_source_sha256"]) == {
        "Task1_basic_price_negotiation.py",
        "Task2_close_price_negotiation.py",
        "Task3_close_to_market_price_negotiation.py",
    }
    assert set(pins["scenario_extraction_sha256"]) == {
        matches[1] for matches in ap_cases.enumerate_realistic_driver_files(UPSTREAM_ROOT)
    }
    for value in pins["env_source_sha256"].values():
        assert isinstance(value, str) and len(value) == 64
        int(value, 16)
    assert pins["bridge_python"] == "3.11"
    assert pins["bridge_deps"] == ["loguru==0.7.3", "numpy==2.4.6"]


# ---------------------------------------------------------------------------
# Driver-script static extraction (never imports/executes upstream).
# ---------------------------------------------------------------------------


def test_extract_basic_task1_driver_matches_known_source_values() -> None:
    config_symbols = ap_cases.load_examples_config(UPSTREAM_ROOT)
    path = UPSTREAM_ROOT / ap_cases._EXAMPLES_DIR / "Task1_basic_price_negotiation.py"
    extraction = ap_cases.extract_driver_script(path, config_symbols=config_symbols)

    assert extraction.registration_id == "Task1_basic_price_negotiation-v0"
    assert extraction.constructor_kwargs["buyer_max_price"] == 150.0
    assert extraction.constructor_kwargs["seller_min_price"] == 80.0
    assert extraction.constructor_kwargs["initial_seller_price"] == 150.0
    assert extraction.constructor_kwargs["max_rounds"] == 20
    assert extraction.constructor_kwargs["price_tolerance"] == 0.0
    assert "buyer_agent" not in extraction.constructor_kwargs
    assert "seller_agent" not in extraction.constructor_kwargs
    assert extraction.reset_kwargs["product_info"]["price"] == 180.0
    assert extraction.description is None


def test_extract_realistic_s01_beauty_product_matches_known_source_values() -> None:
    config_symbols = ap_cases.load_examples_config(UPSTREAM_ROOT)
    _num, scenario_id, path = ap_cases.enumerate_realistic_driver_files(UPSTREAM_ROOT)[0]
    assert scenario_id == "s01_beauty_product"
    extraction = ap_cases.extract_driver_script(path, config_symbols=config_symbols)

    assert extraction.registration_id == "Task1_basic_price_negotiation-v0"
    contract_config = extraction.constructor_kwargs["environment_info"]["contract_config"]
    assert contract_config["buyer_preferences"]["v_base"] == 6.24
    assert contract_config["seller_preferences"]["c_base"] == 5.11
    assert extraction.constructor_kwargs["buyer_max_price"] == 6.24
    assert extraction.constructor_kwargs["seller_min_price"] == 5.11
    assert "initial_seller_price" not in extraction.constructor_kwargs
    assert extraction.reset_kwargs["user_requirement"] == contract_config["contrainfo"]["product_request"]
    assert extraction.description == {
        "category": "Daily Life Consumption",
        "scenario": "Maybelline Expert Wear Eyeshadow transaction",
        "task": "Task4_s1_beauty_product_negotiation",
    }


def test_extract_realistic_taxi_scenario_marks_the_local_image_path_unresolved() -> None:
    config_symbols = ap_cases.load_examples_config(UPSTREAM_ROOT)
    matches = {sid: path for _num, sid, path in ap_cases.enumerate_realistic_driver_files(UPSTREAM_ROOT)}
    extraction = ap_cases.extract_driver_script(matches["s11_taxi_1"], config_symbols=config_symbols)
    image = extraction.reset_kwargs["product_info"]["image_url"]
    assert isinstance(image, dict)
    assert "os.path.join" in image["__unresolved_source__"]


def test_extract_realistic_food_delivery_scenario_normalizes_boolean_discrete_keys() -> None:
    config_symbols = ap_cases.load_examples_config(UPSTREAM_ROOT)
    matches = {sid: path for _num, sid, path in ap_cases.enumerate_realistic_driver_files(UPSTREAM_ROOT)}
    extraction = ap_cases.extract_driver_script(matches["s16_food_delivery_1"], config_symbols=config_symbols)
    contract_config = extraction.constructor_kwargs["environment_info"]["contract_config"]
    weights = contract_config["buyer_preferences"]["discrete_weights"]["extra_condiments"]
    # JSON (and CaseManifest.payload) cannot hold a non-string dict key; the
    # importer coerces True/False -> "true"/"false" the same way json.dumps
    # itself would. The bridge driver restores the real bool before handing
    # this to a live upstream call -- see agenticpay_bridge_driver.py.
    assert weights == {"true": 1.5, "false": 0.0}
    assert True in contract_config["discrete_options"]["extra_condiments"]
    assert False in contract_config["discrete_options"]["extra_condiments"]


# ---------------------------------------------------------------------------
# Case records (spec section 1/3).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def imported() -> tuple[dict, dict[str, dict]]:
    return ap_cases.import_all_cases(UPSTREAM_ROOT)


def test_imports_exactly_28_cases(imported) -> None:
    _pins, cases = imported
    assert len(cases) == 28
    basic = [cid for cid in cases if cid.startswith("agenticpay.bilateral.basic.")]
    realistic = [cid for cid in cases if cid.startswith("agenticpay.bilateral.realistic.")]
    assert len(basic) == 3
    assert len(realistic) == 25


def test_basic_case_identity_and_world_seed(imported) -> None:
    _pins, cases = imported
    case = cases["agenticpay.bilateral.basic.task1"]
    assert case["case_id"] == "agenticpay.bilateral.basic.task1"
    assert case["family_id"] == "agenticpay.bilateral"
    assert case["family_version"] == "0.1.0"
    assert case["split"] == "basic"
    assert case["world_seed"] == 1
    assert case["upstream_task_id"] == "Task1BasicPriceNegotiation"
    seat_ids = {seat["id"] for seat in case["seats"]}
    assert seat_ids == {"buyer", "seller"}
    assert tuple(case["episode"]["termination"]) == ("agreed", "timeout")
    assert case["provenance"] == {
        "generator_id": "agenticpay_bilateral_importer",
        "generator_version": "0.1.0",
        "review_status": "upstream_pinned",
    }


def test_realistic_case_identity_and_world_seed(imported) -> None:
    _pins, cases = imported
    case = cases["agenticpay.bilateral.realistic.s01_beauty_product"]
    assert case["case_id"] == "agenticpay.bilateral.realistic.s01_beauty_product"
    assert case["split"] == "realistic"
    assert case["world_seed"] == 1
    assert case["upstream_task_id"] == "Task4_s1_beauty_product_negotiation"
    assert case["payload"]["scenario_id"] == "s01_beauty_product"
    assert case["payload"]["env_class"] == "Task1BasicPriceNegotiation"


def test_case_record_round_trips_through_the_strict_r1_grammar(imported) -> None:
    _pins, cases = imported
    for case in cases.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]


def test_case_content_sha256_matches_the_kernel_resolver_computation(imported) -> None:
    _pins, cases = imported
    case = cases["agenticpay.bilateral.realistic.s16_food_delivery_1"]
    assert case_content_sha256(case) == case["content_sha256"]

    mutated = copy.deepcopy(case)
    mutated["payload"]["reset_kwargs"]["user_requirement"] = "mutated"
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_case_id_grammar_rejects_a_naive_colon_joined_upstream_id() -> None:
    # A naive "family:split:id" join is exactly what the kernel's identifier
    # grammar forbids (a colon once collapsed GRPO grouping downstream); the
    # importer must mint "agenticpay.bilateral.basic.task1" instead, never
    # this.
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "agenticpay.bilateral:basic:task1",
                "family_id": "agenticpay.bilateral",
                "family_version": "0.1.0",
                "split": "basic",
                "world_seed": 1,
                "seats": [{"id": "buyer", "role": "buyer"}],
                "episode": {"max_logical_actions": 1, "termination": ["agreed"]},
                "visibility_policy": "x",
                "payload": {},
                "provenance": {
                    "generator_id": "g",
                    "generator_version": "0.1.0",
                    "review_status": "upstream_pinned",
                },
                "content_sha256": "0" * 64,
            }
        )


def test_all_case_ids_pass_the_identifier_grammar_with_no_colons(imported) -> None:
    _pins, cases = imported
    for case_id in cases:
        assert ":" not in case_id
        # Round-tripping through CaseManifest.from_dict already enforces the
        # grammar (test above); this is an explicit, human-readable belt.


# ---------------------------------------------------------------------------
# P1 -- import determinism: two importer runs must be byte-identical.
# ---------------------------------------------------------------------------


def test_importer_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    ap_cases.run_import(UPSTREAM_ROOT, out_a)
    ap_cases.run_import(UPSTREAM_ROOT, out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 28 case files + 1 shared pins.json
    assert len(files_a) == 29

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two importer runs"


def test_importer_writes_exactly_28_case_files_plus_shared_pins(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    ap_cases.run_import(UPSTREAM_ROOT, out_dir)

    basic_files = sorted((out_dir / "basic").glob("agenticpay.bilateral.basic.*.json"))
    realistic_files = sorted((out_dir / "realistic").glob("agenticpay.bilateral.realistic.*.json"))
    assert len(basic_files) == 3
    assert len(realistic_files) == 25

    pins = json.loads((out_dir / "pins.json").read_text(encoding="utf-8"))
    assert pins["upstream_commit"] == "1ff4e1a2686eac6a07ff559df6d50329c6fd9f69"


# ---------------------------------------------------------------------------
# Checked-in case files (cases/agenticpay_bilateral/) match a fresh import.
# ---------------------------------------------------------------------------


def test_checked_in_cases_match_a_fresh_import(imported) -> None:
    pins, cases = imported
    repo_root = Path(__file__).resolve().parent.parent
    checked_in_dir = repo_root / "cases" / "agenticpay_bilateral"
    if not checked_in_dir.is_dir():
        pytest.skip("cases/agenticpay_bilateral/ not present in this checkout")

    checked_in_pins = json.loads((checked_in_dir / "pins.json").read_text(encoding="utf-8"))
    assert checked_in_pins == pins

    for case_id, case in cases.items():
        path = checked_in_dir / case["split"] / f"{case_id}.json"
        checked_in_case = json.loads(path.read_text(encoding="utf-8"))
        # Normalize both sides through the same plain-JSON round trip: the
        # freshly imported, in-memory case dict still carries tuples
        # (e.g. episode.termination) where the checked-in file -- read back
        # through json.loads -- only ever has lists. That difference is not
        # a real content mismatch.
        assert checked_in_case == json.loads(json.dumps(case))
