"""Importer: pinned upstream AgenticPay bilateral tasks -> AERead cases.

Wraps SafeRL-Lab/AgenticPay (arXiv 2602.06008, MIT, pinned at commit
``1ff4e1a2686eac6a07ff559df6d50329c6fd9f69``) per
``docs/agenticpay_adapter_spec.md``. Tonight's scope is the
``single_buyer_product_seller`` topology only (Mode B / bilateral, one buyer
seat and one seller seat): 3 "basic" tasks
(``agenticpay/envs/single_buyer_product_seller/Task*.py``) plus 25
"realistic" MAUT-contract scenarios whose ``contract_config``/``product_info``
literals are statically extracted from the CLI driver scripts under
``agenticpay/examples/single_buyer_product_seller/Task{4..28}_s{1..25}_*.py``
(spec section 1).

This module never imports ``agenticpay`` itself and never executes any
upstream source file: everything below is a plain file read plus an
``ast``-based *static* extraction of literal Python values (dict/list/str/
number/bool/None). A scenario driver script unconditionally imports concrete
LLM/VLM backends at module top level with no ``try/except`` guard (spec's
governing facts) -- importing or executing one is out of scope entirely, so
every value here is pulled out of the parsed syntax tree, never obtained by
running the file.

Two upstream source shapes recur across all 28 driver scripts (basic and
realistic alike): a call to the registration factory ``make(<id>, ...)``
whose keyword arguments become this family's environment constructor
arguments, and a call to ``env.reset(...)`` whose keyword arguments become
the reset arguments. A handful of those keyword values are themselves
references to an earlier local variable (most commonly
``"contract_config": contract_config`` inside ``environment_info``, or
``buyer_max_price = contract_config["buyer_preferences"]["v_base"]``) rather
than a literal in place; ``_eval_literal`` resolves those by walking the
driver script's top-level assignments in source order and looking the name
up in a small symbol table, never by executing the script. A few scenarios
(the five taxi ones) build their product image path with
``os.path.join(project_root, ...)`` -- a machine-local absolute path that
would not be portable across checkouts even if it *could* be resolved
statically. Rather than guess at ``project_root`` (which this module never
receives) or silently drop the field, ``_eval_literal`` records any node it
cannot evaluate as a literal as an opaque, clearly-marked
``{"__unresolved_source__": "<unparsed source text>"}`` value. This never
loses information (the exact source expression is preserved verbatim) and
never fabricates a path. The field in question (``product_info["image_url"]``)
is never read by upstream's scoring path, so this only affects a cosmetic,
inert field in the replayed observation -- see the module docstring note in
``environment.py``.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1/3).
# --------------------------------------------------------------------------

FAMILY_ID = "agenticpay.bilateral"
FAMILY_VERSION = "0.1.0"
BASIC_SPLIT = "basic"
REALISTIC_SPLIT = "realistic"
CASE_ID_PREFIX = "agenticpay.bilateral"

VISIBILITY_POLICY = "agenticpay_bilateral_private_reservation_v1"

# Every reason this family's bilateral environment can terminate for --
# upstream's own `info["termination_reason"]` is exactly `"agreed"` (the
# tolerance/contract-compatibility check in `_check_agreement` fired) or
# `"timeout"` (`current_round >= max_rounds` with no agreement) -- and
# nothing else (`Task1BasicPriceNegotiation.step`, spec section "Governing
# facts").
TERMINATION_REASONS = ("agreed", "timeout")

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1/6).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "SafeRL-Lab/AgenticPay"
UPSTREAM_COMMIT = "1ff4e1a2686eac6a07ff559df6d50329c6fd9f69"
UPSTREAM_LICENSE = "MIT"

# The bridge venv this adapter was provisioned and verified against this
# session (see tools/agenticpay_bridge/provision.sh). These describe *our*
# choice of delegate interpreter, not anything read out of upstream source,
# so -- unlike every hash below -- they are genuine adapter-owned pins, not
# derived values.
BRIDGE_PYTHON = "3.11"
BRIDGE_DEPS: tuple[str, ...] = ("loguru==0.7.3", "numpy==2.4.6")

_BASIC_ENV_DIR = Path("agenticpay/envs/single_buyer_product_seller")
_EXAMPLES_DIR = Path("agenticpay/examples/single_buyer_product_seller")
_ENVS_ROOT = Path("agenticpay/envs")
_EXAMPLES_ROOT = Path("agenticpay/examples")
_ENV_REGISTRATION_FILE = Path("agenticpay/envs/__init__.py")

# Anchored: matches "Task14_s11_taxi_1.py" but not
# "Task1_basic_price_negotiation_sglang_example.py" (which merely contains
# the substring "_s" as part of "_sglang").
_SCENARIO_FILE_RE = re.compile(r"^Task(?P<task_num>\d+)_s(?P<scenario_num>\d+)_(?P<slug>.+)\.py$")
_BASIC_CLASS_DIGIT_RE = re.compile(r"^Task(\d+)")

PAYLOAD_FIELDS = frozenset(
    {
        "kind",
        "env_module",
        "env_class",
        "constructor_kwargs",
        "reset_kwargs",
        "scenario_id",
        "description",
        "provenance_files",
        "pins",
    }
)


class SourceExtractionError(RuntimeError):
    """A driver script did not have the shape this static extractor expects.

    Raised only while parsing upstream source with ``ast``; never raised
    because upstream source was executed and failed.
    """


# --------------------------------------------------------------------------
# Generic, execution-free AST literal extraction.
# --------------------------------------------------------------------------


def _unparse(node: ast.AST) -> str:
    return ast.unparse(node)


def _json_dict_key(key: Any) -> str:
    """Coerce a dict key to the string a case manifest (plain JSON) requires.

    Discovered empirically: two of the 25 realistic scenarios
    (``extra_condiments``/``include_utilities``) declare a *boolean*-valued
    discrete contract term, so their literal ``discrete_weights`` dicts use
    Python ``True``/``False`` as dict keys in source. ``CaseManifest``'s
    payload freezing requires string keys (``schemas._freeze_json``), and
    JSON itself has no non-string key syntax at all. This applies the same
    coercion ``json.dumps`` itself silently performs on a dict with a bool
    key (``True`` -> ``"true"``, ``False`` -> ``"false"``) -- a standard,
    well-known convention, not an invented one. Restoring the exact Python
    bool a live upstream call needs is the bridge driver's job (see
    ``agenticpay_bridge_driver._restore_bool_discrete_keys``), scoped
    narrowly to exactly the ``discrete_weights`` terms whose paired
    ``discrete_options`` entry is itself boolean-valued -- never a blanket
    "any string that looks like true/false" guess.
    """
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if key is None:
        return "null"
    if isinstance(key, (int, float)):
        return str(key)
    raise SourceExtractionError(f"unsupported dict key type in static extraction: {key!r}")


def _eval_literal(node: ast.AST, symbols: Mapping[str, Any]) -> Any:
    """Best-effort, execution-free evaluation of a literal-shaped AST node.

    Handles constants, dict/list/tuple literals, unary +/- on a numeric
    constant, a bare name looked up in ``symbols`` (an earlier top-level
    assignment in the same driver script), and a subscript chain rooted at
    such a name (e.g. ``contract_config["buyer_preferences"]["v_base"]``).
    Anything else (a function call, an f-string, a binary op, ...) is
    recorded as an opaque, never-executed source fragment -- see the module
    docstring.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = _eval_literal(node.operand, symbols)
        if isinstance(operand, (int, float)) and not isinstance(operand, bool):
            return -operand if isinstance(node.op, ast.USub) else operand
        return {"__unresolved_source__": _unparse(node)}
    if isinstance(node, ast.Dict):
        result: dict[str, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                raise SourceExtractionError(f"unsupported dict unpacking: {_unparse(node)}")
            key = _json_dict_key(_eval_literal(key_node, symbols))
            result[key] = _eval_literal(value_node, symbols)
        return result
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_literal(item, symbols) for item in node.elts]
    if isinstance(node, ast.Name):
        if node.id in symbols:
            return symbols[node.id]
        raise SourceExtractionError(f"unresolved name in static extraction: {node.id!r}")
    if isinstance(node, ast.Subscript):
        base = _eval_literal(node.value, symbols)
        key = _eval_literal(node.slice, symbols)
        if not isinstance(base, Mapping) or key not in base:
            raise SourceExtractionError(f"cannot resolve subscript statically: {_unparse(node)}")
        return base[key]
    # A Call (e.g. os.path.join(...)), a JoinedStr (f-string), a BinOp, an
    # Attribute access, ... -- never executed, never guessed at.
    return {"__unresolved_source__": _unparse(node)}


def _iter_top_level_assigns(func: ast.FunctionDef):
    for stmt in func.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            yield stmt.targets[0].id, stmt.value


def _build_symbol_table(func: ast.FunctionDef, seed: Mapping[str, Any]) -> dict[str, Any]:
    """Build ``main()``'s top-level assignment symbol table.

    ``seed`` supplies names the driver script imports rather than assigns
    (every one of the 28 scripts does
    ``from agenticpay.examples.config import reward_weights, max_rounds,
    price_tolerance``, so ``max_rounds`` etc. never appear as an
    ``ast.Assign`` inside ``main()`` itself) -- see
    ``load_examples_config``. A local assignment of the same name (never
    observed upstream) would still take precedence, since it is applied
    after the seed below.
    """
    symbols: dict[str, Any] = dict(seed)
    for name, value_node in _iter_top_level_assigns(func):
        try:
            symbols[name] = _eval_literal(value_node, symbols)
        except SourceExtractionError:
            symbols[name] = {"__unresolved_source__": _unparse(value_node)}
    return symbols


def _find_main(tree: ast.Module, path: Path) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise SourceExtractionError(f"{path}: no def main(...) found")


def _find_call(func: ast.FunctionDef, path: Path, *, func_name: str | None = None, attr_name: str | None = None) -> ast.Call:
    matches = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and (
            (func_name is not None and isinstance(node.func, ast.Name) and node.func.id == func_name)
            or (attr_name is not None and isinstance(node.func, ast.Attribute) and node.func.attr == attr_name)
        )
    ]
    if len(matches) != 1:
        raise SourceExtractionError(
            f"{path}: expected exactly one call matching "
            f"func_name={func_name!r}/attr_name={attr_name!r}, found {len(matches)}"
        )
    return matches[0]


def _call_kwargs(call: ast.Call, symbols: Mapping[str, Any]) -> dict[str, Any]:
    return {kw.arg: _eval_literal(kw.value, symbols) for kw in call.keywords if kw.arg is not None}


def _call_first_positional_str(call: ast.Call, path: Path) -> str:
    if not call.args:
        raise SourceExtractionError(f"{path}: call has no positional arguments")
    value = ast.literal_eval(call.args[0])
    if not isinstance(value, str):
        raise SourceExtractionError(f"{path}: expected a string literal, got {value!r}")
    return value


@dataclass(frozen=True)
class DriverExtraction:
    registration_id: str
    constructor_kwargs: dict[str, Any]
    reset_kwargs: dict[str, Any]
    description: dict[str, Any] | None


def extract_driver_script(path: Path, *, config_symbols: Mapping[str, Any] | None = None) -> DriverExtraction:
    """Statically extract one driver script's ``make(...)``/``env.reset(...)`` kwargs.

    ``config_symbols`` seeds names imported from
    ``agenticpay.examples.config`` (``reward_weights``, ``max_rounds``,
    ``price_tolerance``, ...) -- see ``load_examples_config`` and
    ``_build_symbol_table``. Never imports or executes ``path`` itself; see
    the module docstring.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    main_fn = _find_main(tree, path)
    symbols = _build_symbol_table(main_fn, config_symbols or {})

    make_call = _find_call(main_fn, path, func_name="make")
    registration_id = _call_first_positional_str(make_call, path)
    constructor_kwargs = _call_kwargs(make_call, symbols)
    for structural_key in ("buyer_agent", "seller_agent"):
        constructor_kwargs.pop(structural_key, None)

    reset_call = _find_call(main_fn, path, attr_name="reset")
    reset_kwargs = _call_kwargs(reset_call, symbols)

    description: dict[str, Any] | None = None
    for name, value_node in _iter_top_level_assigns(main_fn):
        if name == "results" and isinstance(value_node, ast.Dict):
            literal = _eval_literal(value_node, symbols)
            if isinstance(literal, dict) and "category" in literal:
                description = {
                    "category": literal.get("category"),
                    "scenario": literal.get("scenario"),
                    "task": literal.get("task"),
                }
            break

    return DriverExtraction(
        registration_id=registration_id,
        constructor_kwargs=constructor_kwargs,
        reset_kwargs=reset_kwargs,
        description=description,
    )


def load_examples_config(upstream_root: Path) -> dict[str, Any]:
    """Statically extract ``agenticpay/examples/config.py``'s module-level literals.

    Every one of the 28 driver scripts imports ``reward_weights``,
    ``max_rounds``, and ``price_tolerance`` from this file rather than
    hardcoding them; reading it once here (never importing it) is the same
    execution-free static-extraction discipline as ``extract_driver_script``.
    """
    path = upstream_root / "agenticpay" / "examples" / "config.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: dict[str, Any] = {}
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            name = stmt.targets[0].id
            try:
                symbols[name] = _eval_literal(stmt.value, symbols)
            except SourceExtractionError:
                symbols[name] = {"__unresolved_source__": _unparse(stmt.value)}
    return symbols


def parse_env_registration(upstream_root: Path) -> dict[str, tuple[str, str]]:
    """Statically extract ``agenticpay/envs/__init__.py``'s ``register(...)`` table.

    Returns ``{registration_id: (module, class_name)}``, derived from
    upstream's own ``entry_point="module:Class"`` strings -- never
    hand-typed, so a future upstream rename cannot silently drift from this
    adapter's constants.
    """
    path = upstream_root / _ENV_REGISTRATION_FILE
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    table: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            id_node = kwargs.get("id")
            entry_node = kwargs.get("entry_point")
            if id_node is None or entry_node is None:
                continue
            registration_id = ast.literal_eval(id_node)
            entry_point = ast.literal_eval(entry_node)
            module, _, class_name = entry_point.partition(":")
            table[registration_id] = (module, class_name)
    return table


def _sole_class_name(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise SourceExtractionError(f"{path}: expected exactly one top-level class, found {classes}")
    return classes[0]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


# --------------------------------------------------------------------------
# Enumeration (Gate 1: enumerate, don't trust a claimed count).
# --------------------------------------------------------------------------


def enumerate_basic_env_files(upstream_root: Path) -> list[Path]:
    directory = upstream_root / _BASIC_ENV_DIR
    files = sorted(
        (p for p in directory.glob("Task*.py") if p.name != "__init__.py"),
        key=lambda p: p.name,
    )
    if len(files) != 3:
        raise ValueError(
            f"expected exactly 3 basic bilateral env files under {directory}, "
            f"found {[p.name for p in files]}"
        )
    return files


def enumerate_realistic_driver_files(upstream_root: Path) -> list[tuple[int, str, Path]]:
    """Return ``(scenario_number, scenario_id, path)`` sorted by scenario number."""
    directory = upstream_root / _EXAMPLES_DIR
    matches: list[tuple[int, str, Path]] = []
    for path in directory.iterdir():
        match = _SCENARIO_FILE_RE.match(path.name)
        if match is None:
            continue
        slug = match.group("slug")
        if slug.endswith("_negotiation"):
            slug = slug[: -len("_negotiation")]
        scenario_num = int(match.group("scenario_num"))
        scenario_id = f"s{scenario_num:02d}_{slug}"
        matches.append((scenario_num, scenario_id, path))
    matches.sort(key=lambda item: item[0])
    if len(matches) != 25:
        raise ValueError(
            f"expected exactly 25 realistic bilateral scenario drivers under {directory}, "
            f"found {len(matches)}"
        )
    return matches


def _count_files_matching(directory: Path, predicate) -> int:
    return sum(1 for path in directory.iterdir() if path.is_file() and predicate(path.name))


def enumerated_counts(upstream_root: Path) -> dict[str, int]:
    basic_bilateral = len(enumerate_basic_env_files(upstream_root))
    realistic_bilateral = len(enumerate_realistic_driver_files(upstream_root))

    envs_root = upstream_root / _ENVS_ROOT
    basic_total = sum(
        _count_files_matching(child, lambda name: name.startswith("Task") and name.endswith(".py"))
        for child in envs_root.iterdir()
        if child.is_dir() and not child.name.startswith("__")
    )

    examples_root = upstream_root / _EXAMPLES_ROOT
    realistic_total_examples_dir = sum(
        _count_files_matching(child, lambda name: _SCENARIO_FILE_RE.match(name) is not None)
        for child in examples_root.iterdir()
        if child.is_dir() and not child.name.startswith("__") and child.name != "utils"
    )

    text_only_dir = upstream_root / _EXAMPLES_DIR / "text_only"
    text_only_bilateral = _count_files_matching(
        text_only_dir, lambda name: name.startswith("Task") and name.endswith(".py")
    )

    return {
        "basic_bilateral": basic_bilateral,
        "realistic_bilateral": realistic_bilateral,
        "basic_total": basic_total,
        "realistic_total_examples_dir": realistic_total_examples_dir,
        "text_only_bilateral": text_only_bilateral,
    }


# --------------------------------------------------------------------------
# pins.json (spec section 1).
# --------------------------------------------------------------------------


def build_pins(upstream_root: Path, config_symbols: Mapping[str, Any] | None = None) -> dict[str, Any]:
    config_symbols = config_symbols if config_symbols is not None else load_examples_config(upstream_root)
    env_source_sha256 = {
        path.name: _sha256_file(path) for path in enumerate_basic_env_files(upstream_root)
    }
    scenario_extraction_sha256: dict[str, str] = {}
    for _num, scenario_id, path in enumerate_realistic_driver_files(upstream_root):
        extraction = extract_driver_script(path, config_symbols=config_symbols)
        environment_info = extraction.constructor_kwargs.get("environment_info") or {}
        contract_config = environment_info.get("contract_config")
        scenario_extraction_sha256[scenario_id] = _sha256_bytes(
            canonical_json_bytes(contract_config)
        )
    return {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_license": UPSTREAM_LICENSE,
        "env_source_sha256": env_source_sha256,
        "scenario_extraction_sha256": scenario_extraction_sha256,
        "enumerated_counts": enumerated_counts(upstream_root),
        "bridge_python": BRIDGE_PYTHON,
        "bridge_deps": list(BRIDGE_DEPS),
    }


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1/3).
# --------------------------------------------------------------------------


def _basic_local_id(env_class: str) -> str:
    match = _BASIC_CLASS_DIGIT_RE.match(env_class)
    if match is None:
        raise SourceExtractionError(f"cannot derive a local id from env class {env_class!r}")
    return f"task{match.group(1)}"


def _finish_case(data: dict[str, Any]) -> dict[str, Any]:
    data["content_sha256"] = "0" * 64
    digest = case_content_sha256(data)
    data["content_sha256"] = digest
    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (mirrors tau3_retail's importer paranoia check).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {data['case_id']!r}")
    return data


def build_basic_case(
    env_file: Path,
    upstream_root: Path,
    pins: Mapping[str, Any],
    registration_table: Mapping[str, tuple[str, str]],
    config_symbols: Mapping[str, Any],
) -> dict[str, Any]:
    env_class = _sole_class_name(env_file)
    driver_file = upstream_root / _EXAMPLES_DIR / env_file.name
    if not driver_file.is_file():
        raise ValueError(f"no matching example driver script for {env_file.name}: expected {driver_file}")
    extraction = extract_driver_script(driver_file, config_symbols=config_symbols)
    env_module, registered_class = registration_table[extraction.registration_id]
    if registered_class != env_class:
        raise AssertionError(
            f"{driver_file}: make({extraction.registration_id!r}, ...) resolves to "
            f"{registered_class!r} via envs/__init__.py, but {env_file} defines {env_class!r}"
        )

    local_id = _basic_local_id(env_class)
    case_id = f"{CASE_ID_PREFIX}.{BASIC_SPLIT}.{local_id}"
    world_seed = int(_BASIC_CLASS_DIGIT_RE.match(env_class).group(1))

    payload: dict[str, Any] = {
        "kind": "basic",
        "env_module": env_module,
        "env_class": env_class,
        "constructor_kwargs": extraction.constructor_kwargs,
        "reset_kwargs": extraction.reset_kwargs,
        "scenario_id": None,
        "description": None,
        "provenance_files": {
            "env_source": {
                "path": str(env_file.relative_to(upstream_root)),
                "sha256": pins["env_source_sha256"][env_file.name],
            },
            "driver_source": {
                "path": str(driver_file.relative_to(upstream_root)),
                "sha256": _sha256_file(driver_file),
            },
        },
        "pins": dict(pins),
    }
    if set(payload) != PAYLOAD_FIELDS:
        raise AssertionError(f"payload field drift for {case_id!r}: {sorted(payload)}")

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": BASIC_SPLIT,
        "world_seed": world_seed,
        "seats": [
            {"id": "buyer", "role": "buyer"},
            {"id": "seller", "role": "seller"},
        ],
        "episode": {
            "max_logical_actions": int(extraction.constructor_kwargs["max_rounds"]),
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {
            "generator_id": "agenticpay_bilateral_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        "upstream_task_id": env_class,
        "content_sha256": "0" * 64,
    }
    return _finish_case(data)


def build_realistic_case(
    scenario_id: str,
    driver_file: Path,
    upstream_root: Path,
    pins: Mapping[str, Any],
    registration_table: Mapping[str, tuple[str, str]],
    config_symbols: Mapping[str, Any],
) -> dict[str, Any]:
    extraction = extract_driver_script(driver_file, config_symbols=config_symbols)
    env_module, env_class = registration_table[extraction.registration_id]
    contract_config = (extraction.constructor_kwargs.get("environment_info") or {}).get(
        "contract_config"
    )
    if not isinstance(contract_config, dict) or not contract_config:
        raise ValueError(f"{driver_file}: expected a non-empty contract_config in environment_info")

    case_id = f"{CASE_ID_PREFIX}.{REALISTIC_SPLIT}.{scenario_id}"
    scenario_num = int(scenario_id.split("_", 1)[0][1:])

    basic_env_file = upstream_root / _BASIC_ENV_DIR / (Path(env_module.rsplit(".", 1)[-1] + ".py"))

    payload: dict[str, Any] = {
        "kind": "realistic",
        "env_module": env_module,
        "env_class": env_class,
        "constructor_kwargs": extraction.constructor_kwargs,
        "reset_kwargs": extraction.reset_kwargs,
        "scenario_id": scenario_id,
        "description": extraction.description,
        "provenance_files": {
            "env_source": {
                "path": str(basic_env_file.relative_to(upstream_root)),
                "sha256": _sha256_file(basic_env_file),
            },
            "driver_source": {
                "path": str(driver_file.relative_to(upstream_root)),
                "sha256": _sha256_file(driver_file),
            },
        },
        "pins": dict(pins),
    }
    if set(payload) != PAYLOAD_FIELDS:
        raise AssertionError(f"payload field drift for {case_id!r}: {sorted(payload)}")

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": REALISTIC_SPLIT,
        "world_seed": scenario_num,
        "seats": [
            {"id": "buyer", "role": "buyer"},
            {"id": "seller", "role": "seller"},
        ],
        "episode": {
            "max_logical_actions": int(extraction.constructor_kwargs["max_rounds"]),
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {
            "generator_id": "agenticpay_bilateral_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        "upstream_task_id": driver_file.stem,
        "content_sha256": "0" * 64,
    }
    return _finish_case(data)


def import_all_cases(upstream_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Import all 3 basic + 25 realistic bilateral cases (tonight's full scope).

    Returns ``(pins, {case_id: case_dict})``.
    """
    config_symbols = load_examples_config(upstream_root)
    pins = build_pins(upstream_root, config_symbols)
    registration_table = parse_env_registration(upstream_root)
    cases: dict[str, dict[str, Any]] = {}
    for env_file in enumerate_basic_env_files(upstream_root):
        case = build_basic_case(env_file, upstream_root, pins, registration_table, config_symbols)
        if case["case_id"] in cases:
            raise ValueError(f"duplicate case_id: {case['case_id']!r}")
        cases[case["case_id"]] = case
    for _num, scenario_id, driver_file in enumerate_realistic_driver_files(upstream_root):
        case = build_realistic_case(
            scenario_id, driver_file, upstream_root, pins, registration_table, config_symbols
        )
        if case["case_id"] in cases:
            raise ValueError(f"duplicate case_id: {case['case_id']!r}")
        cases[case["case_id"]] = case
    return pins, cases


# --------------------------------------------------------------------------
# Disk I/O.
# --------------------------------------------------------------------------


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def write_cases(output_dir: Path, pins: Mapping[str, Any], cases: Mapping[str, Mapping[str, Any]]) -> None:
    """Write the shared ``pins.json`` plus one case file per split subdirectory."""
    _dump_json(output_dir / "pins.json", pins)
    for case_id, case in cases.items():
        _dump_json(output_dir / case["split"] / f"{case_id}.json", case)


def run_import(upstream_root: Path, output_dir: Path) -> None:
    """End-to-end: import all 28 tonight-scope cases and write them to disk."""
    pins, cases = import_all_cases(upstream_root)
    write_cases(output_dir, pins, cases)


def _default_output_dir() -> Path:
    # src/aeread_families/agenticpay_bilateral/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "agenticpay_bilateral"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        required=True,
        help="path to the pinned AgenticPay checkout (commit 1ff4e1a2686eac6a07ff559df6d50329c6fd9f69)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json and the basic/realistic case files",
    )
    args = parser.parse_args(argv)
    run_import(args.upstream_root, args.output_dir)


if __name__ == "__main__":
    main()
