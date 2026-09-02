"""Gate-1 corpus-admission tests for the ``steer`` family foundation stage.

These tests exercise the real pinned upstream checkout (read-only, git-lfs
pointer files only) and the real cached corpus bytes at
``bridges/steer-data/`` through a fresh bridge subprocess per test -- never
against a value this test suite invents. The expected counts below are
copied verbatim from ``docs/steer_adapter_spec.md``'s Governing Facts table,
which this session verified against the pinned upstream checkout directly.

No network call happens anywhere in this module: ``flatten_element`` reads
only bytes already cached at ``bridges/steer-data/<element>/*.pkl`` and
re-verifies their sha256 against the pinned checkout's own git-lfs pointer
files (a local, offline read) -- see ``steer_bridge_driver.py``'s module
docstring.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest, is_exportable_id
from aeread_families.steer import cases as steer_cases
from aeread_families.steer.steer_bridge import (
    SteerBridge,
    SteerBridgeError,
    SteerBridgeUnavailableError,
    discover_bridge_python,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_STEER_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-steer",
    )
    root = Path(candidate)
    marker = root / "elements" / "transitivity" / "questions.pkl"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream STEER checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent -- mirrors
            # tests/test_tau3_retail_cases.py's identical convention.
            allow_module_level=True,
        )
    return root


def _cache_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_STEER_DATA_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/bridges/steer-data",
    )
    root = Path(candidate)
    marker = root / "transitivity" / "questions.pkl"
    if not marker.is_file():
        pytest.skip(
            f"cached STEER corpus bytes not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()
CACHE_ROOT = _cache_root()

try:
    BRIDGE_PYTHON = discover_bridge_python()
except SteerBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""

pytestmark = pytest.mark.skipif(
    BRIDGE_PYTHON is None, reason=_BRIDGE_SKIP_REASON or "bridge python unavailable"
)


def _bridge() -> SteerBridge:
    assert BRIDGE_PYTHON is not None
    # `expected_commit` is threaded through on every real bridge invocation
    # this module makes, so the whole file's existing coverage doubles as
    # regression coverage for the positive case: every one of these tests
    # only passes today because the real, pinned upstream checkout's actual
    # `git rev-parse HEAD` genuinely matches `UPSTREAM_COMMIT` (finding 2,
    # docs/steer_codex_triage.md).
    return SteerBridge(
        python_executable=BRIDGE_PYTHON,
        upstream_root=UPSTREAM_ROOT,
        cache_root=CACHE_ROOT,
        expected_commit=steer_cases.UPSTREAM_COMMIT,
    )


# ---------------------------------------------------------------------------
# Governing facts about the upstream corpus (docs/steer_adapter_spec.md).
# ---------------------------------------------------------------------------

EXPECTED_COUNTS = {
    "transitivity": {"total": 16610, "exactly_one_correct": 16452, "zero_correct": 158, "multi_correct": 0},
    "certainty_effect": {"total": 8030, "exactly_one_correct": 7970, "zero_correct": 60, "multi_correct": 0},
    "pure_nash": {"total": 18597, "exactly_one_correct": 6047, "zero_correct": 12550, "multi_correct": 0},
    "backward_induction": {"total": 23810, "exactly_one_correct": 23260, "zero_correct": 550, "multi_correct": 0},
    "plurality_voting": {"total": 10020, "exactly_one_correct": 10020, "zero_correct": 0, "multi_correct": 0},
    "borda_count": {"total": 15030, "exactly_one_correct": 15030, "zero_correct": 0, "multi_correct": 0},
    "dsic_mechanism": {"total": 2417, "exactly_one_correct": 652, "zero_correct": 1760, "multi_correct": 5},
    "ir_mechanism": {"total": 435, "exactly_one_correct": 195, "zero_correct": 240, "multi_correct": 0},
}

# The pinned checkout's own git-lfs pointer ``oid`` per file -- the value
# this session fetched, hashed, and matched 32/32 against media.githubusercontent.com.
EXPECTED_FILE_SHA256 = {
    "transitivity": {
        "questions": "3acd6c076d97315aff3646629c8a8f5b294174a24bc3615db9d9f760de6b9a90",
        "options": "32596c30c758734f7b9e7c3baf19c665c66b0c95c72fb117b976a2672445a3e5",
        "answers": "d057bb260ec1f10ca9c24acf3daa45ad13dd778875a8bcd4f69b48280d4458d4",
        "questions_metadata": "f2b485883e66b7139aef2557506c3d7301e3e56c03fbfade7b93ad003063a683",
    },
    "certainty_effect": {
        "questions": "9217bed5b4fa8c4416fea16fe59018cc1c81a45e49c82b042d8218106f2307b1",
        "options": "077eb6a36072efca2a440a032d7af215e0d68cc9687923dde2d537fc8ded2000",
        "answers": "86ae36035553557abaa511674dfb42b0be3f9fd02612424686a27a5dd6da0817",
        "questions_metadata": "57e1cccf31b83586ee05aa69aba2f7ecfc8da84aa583868572b9594a4393e301",
    },
    "pure_nash": {
        "questions": "9ee82f87e2f378a7a8766393106c1bd46b5d9aff2ef289d6f8da472dc426d6c0",
        "options": "75d375421accbfd3d0ef6c046f3ece6a986636731f8c40d7eee57b366b68fdbb",
        "answers": "fdc204a754f0a7a87cb1eb1203484baad620c04417f19c7abde952883a92a5b9",
        "questions_metadata": "2098cd2e871e1c17e4f79b639a8a9a2c4eb42b9707a2010853a729813927b0c5",
    },
    "backward_induction": {
        "questions": "daf74fd615f58ff3da250bb2eecf2c1fb1bafb8eebc2243ca4ca7e12cce567a5",
        "options": "9a791c35c2db35fa2b796c7bd20ed6e0bc6db947f4d9387348cf9eb60b3cb36f",
        "answers": "29fb1d9b045ca2fc83e872ac21b15d07eb74f04f8e59f2bbad255d1f2017b020",
        "questions_metadata": "ca2d386aa80e535222a098c3268e043c0293cf90a0bcdd216d4e46340f2dda31",
    },
    "plurality_voting": {
        "questions": "43f8077bb88ece1c7aaff1b11024afee9f5e972c960e547575149a5cac221785",
        "options": "cc6627ec18de35de3a314011cd16b34de89458dbb75defa589da4a92d420e3f3",
        "answers": "690989b6455504b7b545b518570bbd98c238bfe94230ff5292b22404a4c6a0ae",
        "questions_metadata": "23f38f7cd1d4c6623a3a2ec8ed3f6156c10dba825caa440789fbad93e285c744",
    },
    "borda_count": {
        "questions": "7f15df38ee5ac9e070a3d63c6968abd65d2726fc09eb1412e909d48d3c0c7e5b",
        "options": "eefc93f0536c9a301a56725731a4485362711f0c3ef9914f6ae70d95b368da37",
        "answers": "2f461a24934c932ba9493e0c13be8c785ca8c90922426a71aaa2f83940be1e8d",
        "questions_metadata": "2e52e886493c4a48db1cb89d34f03dc5b7f9ebfc82e3ce62e57d85e9a67dbceb",
    },
    "dsic_mechanism": {
        "questions": "57e2103112ba7f547f4af05278c54ff105b508403976580982909c8be3598d56",
        "options": "d0922467d1e57ecd317af52168d449f44768908e9736c4d567ac16531b383f12",
        "answers": "0481042f9b6b84d4a405e58d7b97ded4f060d9e6da998e97cca62439d8d7ea70",
        "questions_metadata": "4b799faf183674b9c0cf67e430b17d2f345e993923491c0e72c08ded4ac345f8",
    },
    "ir_mechanism": {
        "questions": "587e6b8f714032f46bdcdb04014e88ca840e016f0c52d18112d2f030f571a53a",
        "options": "896626c01ae323ce58c0b058dff64333160312d8be8ecd04fbaaf5b3404b6241",
        "answers": "0c2a0d14dcc77c62d7ac645c869551408727d96892eef0216e0053a20ed8dd3c",
        "questions_metadata": "8bb22af79fec73a864688d20ecea9f18b78893ceb6b1c8b1ac58395ac13b9e29",
    },
}

assert set(EXPECTED_COUNTS) == set(steer_cases.DECLARED_ELEMENTS)
assert set(EXPECTED_FILE_SHA256) == set(steer_cases.DECLARED_ELEMENTS)


@pytest.mark.parametrize("element", steer_cases.DECLARED_ELEMENTS)
def test_file_sha256_matches_pinned_git_lfs_oid(element: str) -> None:
    """32/32 files (4 per element x 8 elements) byte-verified, fresh subprocess."""
    response = _bridge().flatten_element(element, head_n=1)
    assert response["file_hashes"] == EXPECTED_FILE_SHA256[element]


@pytest.mark.parametrize("element", steer_cases.DECLARED_ELEMENTS)
def test_admission_counts_reproduce_the_governing_facts_table(element: str) -> None:
    """Regression guard for the schema-drift finding: a future importer that

    hardcodes one ``Answers`` column name (``correct`` vs ``correct_answer``)
    must fail this test loudly rather than silently zero out an element.
    """
    response = _bridge().flatten_element(element, head_n=1)
    assert response["counts"] == EXPECTED_COUNTS[element]
    counts = response["counts"]
    assert (
        counts["exactly_one_correct"] + counts["zero_correct"] + counts["multi_correct"]
        == counts["total"]
    )


def test_pure_nash_nan_correct_values_are_not_counted_as_truthy() -> None:
    """Regression test for a major review finding: ``pure_nash`` is the only
    declared element whose ``correct`` column mixes real bool values with
    NaN placeholders (60,000 of its 66,047 non-null-looking rows). A bare
    ``.astype(bool)`` on that object-dtype column silently reads a NaN row
    as ``True`` (Python's own ``bool(float("nan")) is True``), which
    misclassifies 12,000 already-excluded question_ids as multi-correct
    instead of zero-correct without ever admitting a wrong one -- still a
    corrupted count, not a cosmetic one, since the table in
    ``docs/steer_adapter_spec.md`` reports it as fact. This pins the
    NaN-safe reading directly, not just through the full
    ``EXPECTED_COUNTS`` table above."""
    response = _bridge().flatten_element("pure_nash", head_n=steer_cases.HEAD_N)
    counts = response["counts"]
    assert counts["zero_correct"] == 12550
    assert counts["multi_correct"] == 0


@pytest.mark.parametrize("element", steer_cases.DECLARED_ELEMENTS)
def test_head_n_admitted_rows_capped_at_availability(element: str) -> None:
    response = _bridge().flatten_element(element, head_n=steer_cases.HEAD_N)
    expected = min(steer_cases.HEAD_N, EXPECTED_COUNTS[element]["exactly_one_correct"])
    assert len(response["admitted"]) == expected


def test_ir_mechanism_is_the_only_element_below_head_n() -> None:
    below_head_n = [
        element
        for element in steer_cases.DECLARED_ELEMENTS
        if EXPECTED_COUNTS[element]["exactly_one_correct"] < steer_cases.HEAD_N
    ]
    assert below_head_n == ["ir_mechanism"]
    assert EXPECTED_COUNTS["ir_mechanism"]["exactly_one_correct"] == 195


@pytest.mark.parametrize("element", steer_cases.DECLARED_ELEMENTS)
def test_admitted_rows_have_exactly_one_gold_option_within_range(element: str) -> None:
    response = _bridge().flatten_element(element, head_n=steer_cases.HEAD_N)
    for row in response["admitted"]:
        options_count = len(row["options"])
        assert options_count >= 2
        assert [option["option_id"] for option in row["options"]] == list(range(options_count))
        assert 0 <= row["correct_option_id"] < options_count


@pytest.mark.parametrize("element", steer_cases.DECLARED_ELEMENTS)
def test_zero_correct_sample_is_a_real_zero_correct_question_id(element: str) -> None:
    """Golden 5's fixture (spec section 4) must be real upstream data, not a

    fabricated stand-in: every declared element with a nonzero zero-correct
    count must yield one, and the flatten routine must never accidentally
    admit it.
    """
    response = _bridge().flatten_element(element, head_n=steer_cases.HEAD_N)
    admitted_ids = {row["question_id"] for row in response["admitted"]}
    sample = response["zero_correct_sample_question_id"]
    if EXPECTED_COUNTS[element]["zero_correct"] > 0:
        assert sample is not None
        assert sample not in admitted_ids
    else:
        assert sample is None


def test_flatten_is_deterministic_across_two_independent_subprocesses() -> None:
    """Import-determinism parity (spec section 5): flattening the same cached

    bytes twice yields byte-identical admitted rows, mirroring
    tau3_retail_adapter_spec.md section 1's P1 check.
    """
    first = _bridge().flatten_element("dsic_mechanism", head_n=steer_cases.HEAD_N)
    second = _bridge().flatten_element("dsic_mechanism", head_n=steer_cases.HEAD_N)
    assert first["admitted"] == second["admitted"]
    assert first["counts"] == second["counts"]
    assert first["file_hashes"] == second["file_hashes"]


# ---------------------------------------------------------------------------
# Finding 2 (docs/steer_codex_triage.md): false upstream pinning. Nowhere in
# cases.py/steer_bridge.py/steer_bridge_driver.py ever read the real upstream
# checkout's own git state -- `pins.json`'s `upstream_commit` was only ever
# compared against the same hardcoded constant that wrote it. A bridge
# pointed at a checkout whose real `git rev-parse HEAD` does not match the
# commit the caller expects must now refuse outright, never silently import
# from it.
# ---------------------------------------------------------------------------


def test_bridge_refuses_to_flatten_against_an_upstream_checkout_at_the_wrong_commit() -> None:
    assert BRIDGE_PYTHON is not None
    bridge = SteerBridge(
        python_executable=BRIDGE_PYTHON,
        upstream_root=UPSTREAM_ROOT,
        cache_root=CACHE_ROOT,
        expected_commit="0" * 40,
    )
    with pytest.raises(SteerBridgeError, match="revision mismatch"):
        bridge.flatten_element("transitivity", head_n=1)


def test_bridge_refuses_an_upstream_root_that_is_not_a_git_checkout(tmp_path: Path) -> None:
    assert BRIDGE_PYTHON is not None
    bridge = SteerBridge(
        python_executable=BRIDGE_PYTHON,
        upstream_root=tmp_path,
        cache_root=CACHE_ROOT,
        expected_commit=steer_cases.UPSTREAM_COMMIT,
    )
    with pytest.raises(SteerBridgeError, match="not a readable git checkout"):
        bridge.flatten_element("transitivity", head_n=1)


# ---------------------------------------------------------------------------
# CaseManifest construction (spec section 1's case-manifest field table).
# ---------------------------------------------------------------------------


def test_build_case_produces_a_license_safe_payload_with_a_stable_digest() -> None:
    response = _bridge().flatten_element("transitivity", head_n=1)
    pins = steer_cases.build_pins(
        {"transitivity": response["file_hashes"]},
        {"transitivity": response["counts"]},
        {"transitivity": response["zero_correct_sample_question_id"]},
    )
    row = response["admitted"][0]
    case = steer_cases.build_case("transitivity", row, pins)

    assert case["case_id"] == f"steer.transitivity.{row['question_id']}"
    assert is_exportable_id(case["case_id"])
    assert ":" not in case["case_id"]
    assert case["split"] == "utility_theory"
    assert case["episode"] == {"max_logical_actions": 1, "termination": ["answered", "error"]}
    assert case["seats"] == [{"id": "agent", "role": "assistant"}]
    assert case["upstream_task_id"] == row["question_id"]

    payload = case["payload"]
    assert set(payload) == {"element", "question_id", "options_count", "source_sha256", "pins"}
    assert payload["source_sha256"] == row["source_sha256"]
    assert payload["options_count"] == len(row["options"])
    # The licensing regression guard: no raw question/option/explanation text
    # anywhere in the payload.
    serialized_payload = json.dumps(payload)
    assert row["question_text"] not in serialized_payload
    for option in row["options"]:
        assert option["option_text"] not in serialized_payload

    manifest = CaseManifest.from_dict(case)
    assert manifest.content_sha256 == case_content_sha256(case)

    # Re-running the builder over the same row is byte-identical (flatten
    # determinism carried through to case construction).
    again = steer_cases.build_case("transitivity", row, pins)
    assert again == case


def test_build_case_rejects_an_undeclared_element() -> None:
    row = {
        "question_id": "0_0",
        "options": [{"option_id": 0, "option_text": "a"}, {"option_id": 1, "option_text": "b"}],
        "source_sha256": "0" * 64,
    }
    with pytest.raises(ValueError, match="not one of the declared elements"):
        steer_cases.build_case("independence", row, {})


@pytest.mark.parametrize(
    "element,branch",
    [
        ("transitivity", "utility_theory"),
        ("certainty_effect", "utility_theory"),
        ("pure_nash", "game_theory"),
        ("backward_induction", "game_theory"),
        ("plurality_voting", "social_choice"),
        ("borda_count", "social_choice"),
        ("dsic_mechanism", "mechanism_design"),
        ("ir_mechanism", "mechanism_design"),
    ],
)
def test_branch_assignment_is_two_per_taxonomy_branch(element: str, branch: str) -> None:
    assert steer_cases.BRANCH_BY_ELEMENT[element] == branch


def test_declared_corpus_is_two_per_branch_across_four_branches() -> None:
    branches = list(steer_cases.BRANCH_BY_ELEMENT.values())
    assert sorted(set(branches)) == ["game_theory", "mechanism_design", "social_choice", "utility_theory"]
    for branch in set(branches):
        assert branches.count(branch) == 2


# ---------------------------------------------------------------------------
# The already-built corpus on disk (cases/steer/).
# ---------------------------------------------------------------------------

CASES_DIR = Path(__file__).resolve().parents[1] / "cases" / "steer"


def _iter_written_case_paths():
    for branch_dir in sorted(p for p in CASES_DIR.iterdir() if p.is_dir()):
        yield from sorted(branch_dir.glob("*.json"))


@pytest.fixture(scope="module")
def written_cases() -> list[dict]:
    if not CASES_DIR.is_dir():
        pytest.skip(f"cases/steer/ not built yet at {CASES_DIR}")
    paths = list(_iter_written_case_paths())
    if not paths:
        pytest.skip("cases/steer/ contains no case files")
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def test_written_corpus_admits_1595_cases_total(written_cases: list[dict]) -> None:
    assert len(written_cases) == 200 * 7 + 195


def test_written_corpus_case_ids_have_no_colon_and_are_exportable(written_cases: list[dict]) -> None:
    for case in written_cases:
        assert is_exportable_id(case["case_id"])
        assert ":" not in case["case_id"]


def test_written_corpus_payload_never_carries_forbidden_text_fields(written_cases: list[dict]) -> None:
    forbidden = {"question_text", "option_text", "explanation", "domain", "tags"}
    for case in written_cases:
        assert set(case["payload"]) == {
            "element",
            "question_id",
            "options_count",
            "source_sha256",
            "pins",
        }
        assert forbidden.isdisjoint(case["payload"])


def test_written_corpus_manifests_are_authoring_valid_with_stable_digests(
    written_cases: list[dict],
) -> None:
    for case in written_cases:
        manifest = CaseManifest.from_dict(case)
        assert manifest.content_sha256 == case["content_sha256"]
        assert case_content_sha256(case) == case["content_sha256"]


def test_written_corpus_per_element_counts_match_head_n_cap(written_cases: list[dict]) -> None:
    per_element: dict[str, int] = {}
    for case in written_cases:
        per_element[case["payload"]["element"]] = per_element.get(case["payload"]["element"], 0) + 1
    for element in steer_cases.DECLARED_ELEMENTS:
        expected = min(steer_cases.HEAD_N, EXPECTED_COUNTS[element]["exactly_one_correct"])
        assert per_element[element] == expected


def test_corpus_manifest_enumerates_every_written_case() -> None:
    path = CASES_DIR / "corpus_manifest.json"
    if not path.is_file():
        pytest.skip(f"corpus_manifest.json not built yet at {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    written_ids = {path.stem for path in _iter_written_case_paths()}
    assert set(manifest["case_ids"]) == written_ids
    assert len(manifest["case_ids"]) == len(set(manifest["case_ids"]))
    from aeread.shared_runner.resolver import canonical_json_bytes
    import hashlib

    normalized = dict(manifest)
    normalized["content_sha256"] = "0" * 64
    assert hashlib.sha256(canonical_json_bytes(normalized)).hexdigest() == manifest["content_sha256"]


def test_pins_json_matches_the_bridges_own_flatten_output() -> None:
    path = CASES_DIR / "pins.json"
    if not path.is_file():
        pytest.skip(f"pins.json not built yet at {path}")
    pins = json.loads(path.read_text(encoding="utf-8"))
    assert pins["upstream_repo"] == steer_cases.UPSTREAM_REPO
    assert pins["upstream_commit"] == steer_cases.UPSTREAM_COMMIT
    assert pins["file_sha256_by_element"] == EXPECTED_FILE_SHA256
    assert pins["counts_by_element"] == EXPECTED_COUNTS
