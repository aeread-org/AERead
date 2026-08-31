"""Importer: pinned upstream tau2-bench retail/base tasks -> AERead cases.

Turns the 114 tasks in upstream's ``data/tau2/domains/retail/tasks.json``
(pinned at commit ``fc0055dc4e0a316c3f83133267fbd6faaa770992``) into one
``CaseManifest`` JSON file per task plus a shared ``pins.json`` pin record and
an 18-task pilot manifest.  See ``docs/tau3_retail_adapter_spec.md`` sections
1-3 for the governing spec.

This module never reimplements upstream tool bodies, scoring rules, or
database mutations (rule 2 of the adapter build).  The one pin field that can
only be produced by *running* upstream code -- ``tool_schema_sha256``, the
aggregate hash of every retail tool's OpenAI function-calling schema -- is
computed by importing the pinned upstream package and calling its own
``Tool.openai_schema`` property; it is never hand-derived from docstrings.
When the pinned upstream package cannot be imported in the current
environment (e.g. its small pure-Python runtime dependencies -- notably
``docstring_parser``, which materially shapes schema descriptions and cannot
be safely stubbed -- are not installed, and installing them would require a
network call this adapter must never make), that one field is left ``None``
with an explicit ``tool_schema_sha256_unavailable_reason`` rather than being
guessed at.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 3).
# --------------------------------------------------------------------------

FAMILY_ID = "tau3.retail"
FAMILY_VERSION = "0.1.0"
SPLIT = "base"
CASE_ID_PREFIX = "tau3.retail.base"

# The environment is symmetric in tools/policy but each task's
# ``user_scenario`` (the simulated customer's ground-truth persona and
# instructions) is authored for the user seat only and is never shown to the
# assistant seat -- mirroring upstream's own flip_roles design. UNRESOLVED per
# docs/tau3_retail_adapter_spec.md Q3 (no registry of legal
# ``visibility_policy`` values exists yet); revisit once the kernel owner
# answers Q3.
VISIBILITY_POLICY = "tau3_retail_user_scenario_private_v1"

# Every reason this family's environment can terminate for, and nothing else.
# Declared here, next to the manifest that publishes it, and enforced in
# `environment.py`'s `_set_termination` so the declaration and the behaviour
# cannot drift apart.
#
# `agent_stop` is deliberately absent: upstream's retail LLMAgent never
# overrides `Participant.is_stop`, which returns False, so only the user
# simulator can emit a stop signal in this domain.
TERMINATION_REASONS = ("user_stop", "max_steps", "too_many_errors")

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "tau2-bench"
UPSTREAM_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"

# Verbatim upstream constants below are sourced by *reading* the pinned
# checkout's source, never by executing it -- there is no need to run tau2 to
# learn a literal string constant or an `int = 100` default, and reading is
# strictly less risky than importing a package whose runtime dependencies may
# be absent.
#
#   src/tau2/orchestrator/orchestrator.py:
#     DEFAULT_FIRST_AGENT_MESSAGE = AssistantMessage(
#         role="assistant", content="Hi! How can I help you today?", cost=0.0
#     )
GREETING_MESSAGE = "Hi! How can I help you today?"
#   src/tau2/orchestrator/orchestrator.py:
#     def __init__(self, ..., max_steps: int = 100, ...):
MAX_STEPS = 100

JUDGE_MODEL = "gpt-4.1-2025-04-14"
JUDGE_ARGS: Mapping[str, Any] = {"temperature": 0.0}
USER_SIM_MODEL = "gpt-4.1-2025-04-14"
USER_SIM_ARGS: Mapping[str, Any] = {"temperature": 0.0}

# 18-task pilot (docs/tau3_retail_adapter_spec.md section 3 and
# docs/refund_external_benchmark_integration.md section 5); order matches the
# five documented strata concatenated in order.
PILOT_UPSTREAM_TASK_IDS: tuple[str, ...] = (
    "14", "53", "73", "108",
    "10", "11", "82", "83",
    "5", "48", "84", "91",
    "16", "28", "103", "104",
    "30", "46",
)

PILOT_ID = "tau3_retail_pilot_v1"


class Tau2NotImportableError(RuntimeError):
    """The pinned upstream tau2 package could not be imported for delegation.

    Raised only by :func:`compute_tool_schema_sha256`. Never caught silently
    with a fabricated hash -- callers decide whether a missing tool-schema
    hash is acceptable for their purpose.
    """


# --------------------------------------------------------------------------
# Upstream data access (plain file reads; no tau2 import required).
# --------------------------------------------------------------------------


def _retail_data_dir(upstream_root: Path) -> Path:
    return upstream_root / "data" / "tau2" / "domains" / "retail"


def _user_sim_guidelines_path(upstream_root: Path) -> Path:
    # Non-voice, non-tools text user simulator (the retail default): see
    # src/tau2/user/user_simulator.py:get_global_user_sim_guidelines(use_tools=False)
    # and src/tau2/runner/helpers.py:get_info (non-voice branch).
    return upstream_root / "data" / "tau2" / "user_simulator" / "simulation_guidelines.md"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return _sha256_bytes(data), len(data)


def load_upstream_tasks(upstream_root: Path) -> list[dict]:
    """Load the verbatim upstream retail task records (list of 114 dicts)."""
    tasks_path = _retail_data_dir(upstream_root) / "tasks.json"
    with tasks_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_upstream_split(upstream_root: Path) -> dict[str, list[str]]:
    """Load ``split_tasks.json`` (``train``/``test``/``base`` id lists)."""
    split_path = _retail_data_dir(upstream_root) / "split_tasks.json"
    with split_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# tool_schema_sha256: the one pin field that requires delegating to upstream.
# --------------------------------------------------------------------------


def compute_tool_schema_sha256(upstream_root: Path) -> str:
    """Delegate to the pinned upstream package for the tool-schema hash.

    Mirrors upstream's own ``get_dict_hash({t.name: t.openai_schema for t in
    env.get_tools()})`` (``tau2.utils.utils.get_dict_hash`` is
    ``sha256(json.dumps(obj, sort_keys=True, default=str))`` -- a three-line
    hashing helper, reproduced verbatim here per spec section 1; this is not a
    tool body, scoring rule, or database mutation). The schema *content*
    itself -- names, descriptions, and JSON-schema shapes derived from
    upstream's docstrings and pydantic models via ``docstring_parser`` -- is
    never hand-derived: this function always imports and runs the pinned
    upstream package to get it.

    Raises:
        Tau2NotImportableError: if the pinned upstream package (or one of its
            runtime dependencies) cannot be imported in this environment.
    """
    src_dir = str(upstream_root / "src")
    inserted = src_dir not in sys.path
    if inserted:
        sys.path.insert(0, src_dir)
    try:
        try:
            from tau2.domains.retail.environment import get_environment
        except ModuleNotFoundError as exc:
            raise Tau2NotImportableError(
                "cannot import the pinned upstream tau2 package (looked under "
                f"{src_dir!r}) to compute tool_schema_sha256 by delegation: {exc}"
            ) from exc
        env = get_environment()
        schema_by_name = {tool.name: tool.openai_schema for tool in env.get_tools()}
        blob = json.dumps(schema_by_name, sort_keys=True, default=str)
        return _sha256_bytes(blob.encode())
    finally:
        if inserted and src_dir in sys.path:
            sys.path.remove(src_dir)


# --------------------------------------------------------------------------
# pins.json
# --------------------------------------------------------------------------


def build_pins(upstream_root: Path, *, require_tool_schema: bool = False) -> dict[str, Any]:
    """Build the pin record (spec section 1).

    When ``require_tool_schema`` is False (the default) and the pinned
    upstream package cannot be imported, ``tool_schema_sha256`` is left
    ``None`` and ``tool_schema_sha256_unavailable_reason`` explains why,
    instead of raising -- so the rest of the importer (case records, which do
    not depend on this field) can still be produced and verified. Set
    ``require_tool_schema=True`` for a production build that must fail loudly
    if the hash cannot be computed.
    """
    retail_dir = _retail_data_dir(upstream_root)
    db_sha256, db_bytes = _sha256_file(retail_dir / "db.json")
    tasks_sha256, _tasks_bytes = _sha256_file(retail_dir / "tasks.json")
    policy_sha256, _policy_bytes = _sha256_file(retail_dir / "policy.md")
    user_sim_guidelines_sha256, _guidelines_bytes = _sha256_file(
        _user_sim_guidelines_path(upstream_root)
    )

    tool_schema_sha256: str | None
    tool_schema_unavailable_reason: str | None
    try:
        tool_schema_sha256 = compute_tool_schema_sha256(upstream_root)
        tool_schema_unavailable_reason = None
    except Tau2NotImportableError as exc:
        if require_tool_schema:
            raise
        tool_schema_sha256 = None
        tool_schema_unavailable_reason = str(exc)

    pins: dict[str, Any] = {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "db_sha256": db_sha256,
        "db_bytes": db_bytes,
        "tasks_sha256": tasks_sha256,
        "policy_sha256": policy_sha256,
        "user_sim_guidelines_sha256": user_sim_guidelines_sha256,
        "tool_schema_sha256": tool_schema_sha256,
        "greeting_message": GREETING_MESSAGE,
        "max_steps": MAX_STEPS,
        "judge_model": JUDGE_MODEL,
        "judge_args": dict(JUDGE_ARGS),
        "user_sim_model": USER_SIM_MODEL,
        "user_sim_args": dict(USER_SIM_ARGS),
    }
    if tool_schema_unavailable_reason is not None:
        pins["tool_schema_sha256_unavailable_reason"] = tool_schema_unavailable_reason
    return pins


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 3).
# --------------------------------------------------------------------------


def build_case(task: Mapping[str, Any], pins: Mapping[str, Any]) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one verbatim upstream task record."""
    upstream_id = task["id"]
    if not isinstance(upstream_id, str) or not upstream_id:
        raise ValueError(f"upstream task id must be a non-empty string, got {upstream_id!r}")
    case_id = f"{CASE_ID_PREFIX}.{upstream_id}"

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": SPLIT,
        "world_seed": int(upstream_id),
        "seats": [
            {"id": "assistant", "role": "assistant"},
            {"id": "user", "role": "user"},
        ],
        "episode": {
            "max_logical_actions": pins["max_steps"],
            # Exactly the reasons this family's environment can produce.
            # `agent_stop` is unreachable in retail -- upstream's LLMAgent
            # never overrides Participant.is_stop, which returns False -- and
            # `too_many_errors` was missing, so an episode that hit the tool
            # error ceiling terminated with a reason absent from its own
            # declared vocabulary.
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {"task": task, "pins": dict(pins)},
        "provenance": {
            "generator_id": "tau3_retail_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        "upstream_task_id": upstream_id,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (paranoia; cheap and catches canonicalization bugs
    # early rather than at resolve time).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def import_all_cases(upstream_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Import every upstream retail/base task into a case record.

    Returns ``(pins, {case_id: case_dict})`` in upstream task order.
    """
    pins = build_pins(upstream_root)
    tasks = load_upstream_tasks(upstream_root)
    cases: dict[str, dict[str, Any]] = {}
    for task in tasks:
        case = build_case(task, pins)
        if case["case_id"] in cases:
            raise ValueError(f"duplicate case_id: {case['case_id']!r}")
        cases[case["case_id"]] = case
    return pins, cases


# --------------------------------------------------------------------------
# Pilot manifest.
# --------------------------------------------------------------------------


def _pilot_case_id(upstream_task_id: str) -> str:
    return f"{CASE_ID_PREFIX}.{upstream_task_id}"


def build_pilot_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the 18-task pilot manifest and its own content hash.

    Raises if any pilot id fails to resolve against ``cases``.
    """
    case_ids = [_pilot_case_id(task_id) for task_id in PILOT_UPSTREAM_TASK_IDS]
    missing = [cid for cid in case_ids if cid not in cases]
    if missing:
        raise ValueError(f"pilot case ids not found in imported corpus: {missing}")
    mismatched = [
        cid
        for cid, task_id in zip(case_ids, PILOT_UPSTREAM_TASK_IDS)
        if cases[cid]["upstream_task_id"] != task_id
    ]
    if mismatched:
        raise AssertionError(f"pilot case upstream_task_id mismatch: {mismatched}")

    data: dict[str, Any] = {
        "pilot_id": PILOT_ID,
        "family_id": FAMILY_ID,
        "split": SPLIT,
        "upstream_task_ids": list(PILOT_UPSTREAM_TASK_IDS),
        "case_ids": case_ids,
        "content_sha256": "0" * 64,
    }
    digest = _pilot_content_sha256(data)
    data["content_sha256"] = digest
    return data


def _pilot_content_sha256(value: Mapping[str, Any]) -> str:
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
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
    """Write ``pins.json``, one file per case, and the pilot manifest."""
    _dump_json(output_dir / "pins.json", pins)
    for case_id, case in cases.items():
        _dump_json(output_dir / f"{case_id}.json", case)
    _dump_json(output_dir / "pilot_manifest.json", pilot_manifest)


def run_import(upstream_root: Path, output_dir: Path) -> None:
    """End-to-end: import all 114 tasks and write the case set + pilot manifest."""
    pins, cases = import_all_cases(upstream_root)
    pilot_manifest = build_pilot_manifest(cases)
    write_cases(output_dir, pins, cases, pilot_manifest)


def _default_output_dir() -> Path:
    # src/aeread_families/tau3_retail/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "tau3_retail" / "base"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        required=True,
        help="path to the pinned tau2-bench checkout (commit fc0055dc4e0a316c3f83133267fbd6faaa770992)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json, the 114 case files, and pilot_manifest.json",
    )
    args = parser.parse_args(argv)
    run_import(args.upstream_root, args.output_dir)


if __name__ == "__main__":
    main()
