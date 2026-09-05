"""Importer: pinned upstream AmazonPriceHistory sessions -> AERead cases.

Turns upstream's 930 single-product bargaining sessions (18 category JSON
files under ``data/AmazonHistoryPrice/``, pinned at commit
``834ad9066d0627f0332504d5fa6d236706f2402b``) into ``pins.json`` (a
file-level pin record over all 18 files, plus the full 930-session
declared enumeration -- Gate 1) and one ``CaseManifest`` JSON file per
*materialized* session. Tonight only the 45-session pilot pair
(``home-kitchen`` + ``toys-games``) is materialized; see
``docs/amazonbarg_adapter_spec.md`` sections 1-1.2 for the governing spec
and the reason the other 885 sessions are digested at the file level only.

This module never reimplements upstream's price/cost derivation or its
``codename`` construction: both are delegated to the pinned
``product.CamelAmazon`` loader via ``upstream_shim.import_camel_amazon_inventories``
(rule 2 of the adapter build). The raw per-record JSON (title, description,
list/high/low prices, and every other upstream field) is read directly
(a plain file read, not a delegated import) and stored verbatim in each
materialized case's payload alongside the delegated derivation, so a case
is fully self-describing and auditable without a second lookup into
``pins.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import upstream_shim

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1.1).
# --------------------------------------------------------------------------

FAMILY_ID = "amazonbarg.bilateral"
FAMILY_VERSION = "0.1.0"
SPLIT = "pilot"
CASE_ID_PREFIX = "amazonbarg.bilateral"

# Seller cost is private information the buyer seat never observes -- the
# defining asymmetry of this benchmark (product.py's own docstring: "cost
# is private information of seller. invisible to buyer").
VISIBILITY_POLICY = "amazonbarg_seller_cost_private_v1"

# Every reason this family's environment can terminate for, and nothing
# else -- mirrors upstream's own `errormsg` vocabulary in
# `session.Agent2AgentSession.agents_talk_with_action` ("BUYER:deal" /
# "SELLER:deal" / "...:quit" / "...:action error" / "turn limit"), reduced
# to the action-type dimension (which seat produced it is recorded
# separately in the terminal state, not in this vocabulary).
TERMINATION_REASONS = ("deal", "quit", "action_error", "turn_limit")

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "TianXiaSJTU/AmazonPriceHistory"
UPSTREAM_COMMIT = "834ad9066d0627f0332504d5fa6d236706f2402b"
UPSTREAM_LICENSE = "Apache-2.0"

# Upstream's own run scripts (run_2stages.sh, run_3stages.sh) pin this
# value; this adapter pins the same one (spec "Governing facts").
BUDGET_RATIO = 0.8

# Upstream's own `run_session.py:main` default, never overridden by either
# `run_2stages.sh` or `run_3stages.sh` -- read from the pinned checkout,
# never executed, exactly like tau3_retail's MAX_STEPS (spec addendum:
# this constant was missing from the original spec draft; added here after
# verifying it against the pinned source, per this build's own rule to
# update the spec when reality forces a correction).
MAX_TURNS = 6

CORPUS_SUBDIR = ("data", "AmazonHistoryPrice")

# The 18 pinned category files, in the exact `sorted(os.listdir(...))`
# order `product.CamelAmazon` itself iterates in (verified against the
# pinned checkout; every file's own `category` field equals its filename
# stem for every one of its records).
CATEGORY_FILES: tuple[str, ...] = (
    "automotive.json",
    "baby-products.json",
    "beauty.json",
    "books.json",
    "electronics.json",
    "health-personal-care.json",
    "home-kitchen.json",
    "industrial-scientific.json",
    "movies-tv.json",
    "music.json",
    "other.json",
    "patio-lawn-garden.json",
    "pet-supplies.json",
    "software.json",
    "sports-outdoors.json",
    "tools-home-improvement.json",
    "toys-games.json",
    "video-games.json",
)

# Pilot corpus: one category pair, 45 sessions (spec section 1.2). Chosen
# because their sum (23 + 22) lands in the requested 40-60 range while
# still including at least one conflicting-interest session
# (`toys-games_22`, the DJI Mini 4 Pro drone).
PILOT_CATEGORY_FILES: tuple[str, ...] = ("home-kitchen.json", "toys-games.json")
PILOT_ID = "amazonbarg_pilot_v1"


# --------------------------------------------------------------------------
# Identifier grammar and sanitization (spec section 1.1).
# --------------------------------------------------------------------------

_SANITIZE_PASSTHROUGH_RE = re.compile(r"[a-z0-9_.\-]")
_SANITIZE_MARKER_RE = re.compile(r"_x([0-9a-f]{4})_")

# Codex-review finding 8: the literal characters `_`, `x`, and hex digits
# are themselves inside `_SANITIZE_PASSTHROUGH_RE`'s passthrough set, so a
# codename that already happens to *contain* the literal marker text (e.g.
# "a_x003a_b") was previously left untouched and became indistinguishable
# from the escaped form of "a:b" (both produced "a_x003a_b") -- sanitize was
# the identity on today's fixed 930-codename corpus but not a true injection
# in general, contradicting its own docstring's "safe, unique id" intent.
# `sanitize` cannot simply stop passing `_` through unchanged (real
# codenames like "home-kitchen_2" rely on that passthrough for a stable,
# human-readable case_id -- see `test_sanitize_is_the_identity_on_every_one
# _of_the_930_real_codenames`); instead, only a raw underscore that would
# otherwise combine with the literal text immediately following it in the
# INPUT to form something indistinguishable from a genuine escape marker is
# itself escaped. This matches exactly one marker shape and needs one
# character of lookahead into the *raw, unescaped* input, never into
# already-produced output.
_DANGEROUS_UNDERSCORE_LOOKAHEAD_RE = re.compile(r"x[0-9a-f]{4}_")


def sanitize(codename: str) -> str:
    """Pass ``[a-z0-9_.-]`` through unchanged; escape everything else.

    Every other character becomes ``_x{ord(c):04x}_``. All 930 upstream
    codenames in this corpus already satisfy the export grammar (verified
    below, not assumed), so this is the identity function on every case
    built tonight; it exists so a future non-conforming category name does
    not silently produce a colon-bearing or otherwise unsafe id. A raw
    underscore that would otherwise be followed by text shaped exactly like
    the rest of a genuine escape marker (``x{4 hex digits}_``) is itself
    escaped too, rather than passed through, so this function stays
    injective even on an adversarial or coincidentally marker-shaped input
    (codex-review finding 8) -- every real codename in the pinned corpus has
    no such lookalike substring, so this changes nothing for any case built
    tonight.
    """
    out: list[str] = []
    index = 0
    length = len(codename)
    while index < length:
        character = codename[index]
        if character == "_" and _DANGEROUS_UNDERSCORE_LOOKAHEAD_RE.match(
            codename, index + 1
        ):
            out.append(f"_x{ord('_'):04x}_")
        elif _SANITIZE_PASSTHROUGH_RE.fullmatch(character):
            out.append(character)
        else:
            out.append(f"_x{ord(character):04x}_")
        index += 1
    return "".join(out)


def desanitize(value: str) -> str:
    """Invert :func:`sanitize`. The identity except at ``_xHHHH_`` markers."""

    def _replace(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return _SANITIZE_MARKER_RE.sub(_replace, value)


def case_id_for_codename(codename: str) -> str:
    return f"{CASE_ID_PREFIX}.{sanitize(codename)}"


# --------------------------------------------------------------------------
# Upstream data access.
# --------------------------------------------------------------------------


def _corpus_dir(upstream_root: Path) -> Path:
    directory = upstream_root
    for part in CORPUS_SUBDIR:
        directory = directory / part
    return directory


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return _sha256_bytes(data), len(data)


def load_raw_category_records(upstream_root: Path, category_file: str) -> list[dict[str, Any]]:
    """Load one category file's verbatim upstream JSON record list."""
    path = _corpus_dir(upstream_root) / category_file
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def codename_category(codename: str) -> str:
    # `codename = f"{category}_{idx+1}"` (product.py); every one of the 18
    # category names uses hyphens, never underscores, so splitting on the
    # last underscore recovers the category unambiguously.
    category, _, _suffix = codename.rpartition("_")
    return category


class _DerivedProduct:
    __slots__ = ("codename", "category", "title", "description", "price", "cost", "budget")

    def __init__(self, codename: str, title: str, description: str, price: float, cost: float) -> None:
        self.codename = codename
        self.category = codename_category(codename)
        self.title = title
        self.description = description
        self.price = price
        self.cost = cost
        self.budget = price * BUDGET_RATIO


def load_all_derived_products(upstream_root: Path) -> list[_DerivedProduct]:
    """Delegate to upstream's own loader for every one of the 930 sessions.

    Never reimplements the ``price = max(highest_price, list_price)`` /
    ``cost = lowest_price`` / ``codename = f"{category}_{idx+1}"``
    derivation -- this calls the pinned ``product.CamelAmazon`` loader
    itself (spec section 3.1 point 4: zero third-party imports, no shim
    needed) and only re-shapes its output.
    """
    inventories = upstream_shim.import_camel_amazon_inventories(
        upstream_root, _corpus_dir(upstream_root)
    )
    products: list[_DerivedProduct] = []
    for inventory in inventories:
        (product,) = inventory.products  # each session has exactly one product
        products.append(
            _DerivedProduct(
                codename=product.codename,
                title=product.title,
                description=product.description,
                price=float(product.price),
                cost=float(product.cost),
            )
        )
    return products


# --------------------------------------------------------------------------
# pins.json (Gate 1: pinned source, corpus enumeration, content digest).
# --------------------------------------------------------------------------


def build_pins(upstream_root: Path) -> dict[str, Any]:
    """Build the file-level pin record plus the declared 930-session enumeration.

    Every one of the 18 pinned category files gets its real byte-length
    and ``sha256`` (cheap, done for all 18 now, so a future upstream data
    revision is caught immediately) -- but this does *not* build a
    ``CaseManifest`` per session; that per-session walk is declared here
    (``session_count``/``mutual_interest_count``/``conflicting_interest_count``)
    and materialized only for the 45-session pilot pair (see
    :func:`import_pilot_cases`).
    """
    corpus_dir = _corpus_dir(upstream_root)
    category_files: list[dict[str, Any]] = []
    total_records = 0
    for filename in CATEGORY_FILES:
        path = corpus_dir / filename
        sha256, byte_count = _sha256_file(path)
        with path.open("r", encoding="utf-8") as handle:
            record_count = len(json.load(handle))
        total_records += record_count
        category_files.append(
            {
                "file": filename,
                "category": filename.removesuffix(".json"),
                "sha256": sha256,
                "bytes": byte_count,
                "record_count": record_count,
            }
        )

    products = load_all_derived_products(upstream_root)
    if len(products) != total_records:
        raise AssertionError(
            "delegated product.CamelAmazon() session count "
            f"({len(products)}) does not match the file-level record count ({total_records})"
        )
    mutual_interest = sum(1 for product in products if product.cost <= product.budget)
    conflicting_interest = len(products) - mutual_interest

    return {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "license": UPSTREAM_LICENSE,
        "budget_ratio": BUDGET_RATIO,
        "max_turns": MAX_TURNS,
        "category_files": category_files,
        "total_records": total_records,
        "total_mutual_interest": mutual_interest,
        "total_conflicting_interest": conflicting_interest,
        "pilot_category_files": list(PILOT_CATEGORY_FILES),
    }


def enumerate_all_codenames(upstream_root: Path) -> list[dict[str, Any]]:
    """Declared (not materialized) enumeration of all 930 sessions (Gate 1).

    One entry per session: ``codename``, ``category``, and ``interest``
    (``"mutual"`` when ``cost <= budget``, else ``"conflicting"``) --
    enough to verify the corpus-wide MI/CI split and the sanitization
    round-trip (test plan P6) without building a ``CaseManifest`` for any
    of the 885 non-pilot sessions.
    """
    products = load_all_derived_products(upstream_root)
    return [
        {
            "codename": product.codename,
            "category": product.category,
            "interest": "mutual" if product.cost <= product.budget else "conflicting",
        }
        for product in products
    ]


# --------------------------------------------------------------------------
# CaseManifest construction (spec sections 1.2, 3).
# --------------------------------------------------------------------------


def _world_seed_index(codenames_in_corpus_order: list[str], codename: str) -> int:
    return codenames_in_corpus_order.index(codename)


def build_case(
    *,
    codename: str,
    world_seed: int,
    raw_record: Mapping[str, Any],
    derived: _DerivedProduct,
    category_file: str,
    category_file_sha256: str,
    category_file_bytes: int,
    index_in_file: int,
) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one materialized session."""
    case_id = case_id_for_codename(codename)
    interest = "mutual" if derived.cost <= derived.budget else "conflicting"

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": SPLIT,
        "world_seed": world_seed,
        "seats": [
            {"id": "buyer", "role": "buyer"},
            {"id": "seller", "role": "seller"},
        ],
        "episode": {
            "max_logical_actions": 2 * MAX_TURNS,
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "product": dict(raw_record),
            "derived": {
                "codename": derived.codename,
                "category": derived.category,
                "category_file": category_file,
                "index_in_file": index_in_file,
                "title": derived.title,
                "description": derived.description,
                "price": derived.price,
                "cost": derived.cost,
                "budget": derived.budget,
                "interest": interest,
            },
            "pins": {
                "upstream_repo": UPSTREAM_REPO,
                "upstream_commit": UPSTREAM_COMMIT,
                "license": UPSTREAM_LICENSE,
                "budget_ratio": BUDGET_RATIO,
                "max_turns": MAX_TURNS,
                "category_file_sha256": category_file_sha256,
                "category_file_bytes": category_file_bytes,
            },
        },
        "provenance": {
            "generator_id": "amazonbarg_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        "upstream_task_id": codename,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (paranoia; cheap and catches canonicalization
    # bugs early rather than at resolve time).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def import_pilot_cases(upstream_root: Path) -> dict[str, dict[str, Any]]:
    """Materialize the 45-session pilot pair into ``CaseManifest`` dicts.

    Delegates price/cost/codename derivation to
    :func:`load_all_derived_products` (upstream's own loader) and reads
    each pilot file's raw records directly for full per-case provenance.
    Returns ``{case_id: case_dict}`` in pinned-corpus order (home-kitchen
    before toys-games, both in upstream's own within-file order).
    """
    products = load_all_derived_products(upstream_root)
    codenames_in_corpus_order = [product.codename for product in products]
    products_by_codename = {product.codename: product for product in products}

    corpus_dir = _corpus_dir(upstream_root)
    cases: dict[str, dict[str, Any]] = {}
    for category_file in PILOT_CATEGORY_FILES:
        category = category_file.removesuffix(".json")
        path = corpus_dir / category_file
        category_sha256, category_bytes = _sha256_file(path)
        raw_records = load_raw_category_records(upstream_root, category_file)
        for index_in_file, raw_record in enumerate(raw_records):
            codename = f"{category}_{index_in_file + 1}"
            derived = products_by_codename.get(codename)
            if derived is None:
                raise AssertionError(
                    f"delegated product.CamelAmazon() never produced codename {codename!r} "
                    f"expected from {category_file!r} record {index_in_file}"
                )
            if raw_record.get("category") != category:
                raise AssertionError(
                    f"raw record {index_in_file} in {category_file!r} declares category "
                    f"{raw_record.get('category')!r}, expected {category!r}"
                )
            case = build_case(
                codename=codename,
                world_seed=_world_seed_index(codenames_in_corpus_order, codename),
                raw_record=raw_record,
                derived=derived,
                category_file=category_file,
                category_file_sha256=category_sha256,
                category_file_bytes=category_bytes,
                index_in_file=index_in_file,
            )
            if case["case_id"] in cases:
                raise ValueError(f"duplicate case_id: {case['case_id']!r}")
            cases[case["case_id"]] = case
    return cases


# --------------------------------------------------------------------------
# Pilot manifest.
# --------------------------------------------------------------------------


def build_pilot_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the 45-session pilot manifest and its own content hash."""
    # Preserve insertion order (home-kitchen_1..23, then toys-games_1..22)
    # rather than sorting -- `import_pilot_cases` already builds `cases` in
    # that natural, human-readable order and Python dicts preserve it. This
    # is purely a readability choice, not a determinism requirement:
    # `_pilot_content_sha256` digests a sorted copy of `case_ids` (codex-
    # review finding 9), so a caller that assembled the identical 45-case
    # set in a different sequence would still get the identical
    # `content_sha256` for what is the same membership.
    case_ids = list(cases)
    if len(case_ids) != 45:
        raise ValueError(f"pilot manifest expected 45 cases, got {len(case_ids)}")

    data: dict[str, Any] = {
        "pilot_id": PILOT_ID,
        "family_id": FAMILY_ID,
        "split": SPLIT,
        "category_files": list(PILOT_CATEGORY_FILES),
        "case_ids": case_ids,
        "content_sha256": "0" * 64,
    }
    digest = _pilot_content_sha256(data)
    data["content_sha256"] = digest
    return data


def _pilot_content_sha256(value: Mapping[str, Any]) -> str:
    """Digest the manifest's *membership*, never its incidental list order.

    Codex-review finding 9: ``case_ids`` represents pilot membership (a set
    of 45 sessions), not a meaningful total order -- two callers assembling
    the identical 45-case set in a different sequence must get the
    identical digest for what is the same content. Only the copy fed to
    the digest is sorted here; the manifest's own ``case_ids`` field (see
    :func:`build_pilot_manifest`) is left exactly as its caller built it,
    still the natural, human-readable corpus order every real caller
    produces today.
    """
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    if "case_ids" in normalized:
        normalized["case_ids"] = sorted(normalized["case_ids"])
    return _sha256_bytes(canonical_json_bytes(normalized))


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
    pilot_manifest: Mapping[str, Any],
) -> None:
    """Write ``pins.json``, one file per materialized case, and the pilot manifest."""
    _dump_json(output_dir / "pins.json", pins)
    for case_id, case in cases.items():
        _dump_json(output_dir / f"{case_id}.json", case)
    _dump_json(output_dir / "pilot_manifest.json", pilot_manifest)


def run_import(upstream_root: Path, output_dir: Path) -> None:
    """End-to-end: build pins.json, the 45-session pilot, and its manifest."""
    pins = build_pins(upstream_root)
    cases = import_pilot_cases(upstream_root)
    pilot_manifest = build_pilot_manifest(cases)
    write_cases(output_dir, pins, cases, pilot_manifest)


def _default_output_dir() -> Path:
    # src/aeread_families/amazonbarg/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "amazonbarg" / "pilot"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        required=True,
        help="path to the pinned AmazonPriceHistory checkout (commit 834ad9066d0627f0332504d5fa6d236706f2402b)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json, the 45 pilot case files, and pilot_manifest.json",
    )
    args = parser.parse_args(argv)
    run_import(args.upstream_root, args.output_dir)


if __name__ == "__main__":
    main()
