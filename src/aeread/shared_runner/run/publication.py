"""Family-neutral publication sanitization and atomic evidence writes.

A publication is the tracked, sanitized projection of a local run. These
helpers are the parts every family needs identically: the prohibited-text
scan, the sanitization declaration each manifest repeats, refuse-to-overwrite
atomic writes, JSONL encoding, and the receipt field whitelist. Family modules
keep their own transcript projections, summaries, and README text.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .resolver import canonical_json_bytes

PROHIBITED_PUBLIC_TEXT: tuple[str, ...] = (
    '"raw_response"',
    '"failure_message"',
    '"output_text"',
    '"user_id"',
    "authorization:",
    "api_key",
    "/users/",
)

SANITIZATION_DECLARATION: Mapping[str, bool] = MappingProxyType(
    {
        "raw_provider_responses_included": False,
        "full_prompts_included": False,
        "model_reasoning_included": False,
        "complete_receipts_included": False,
        "failure_messages_included": False,
    }
)


def assert_public_payload(
    name: str, payload: bytes, *, prohibited: Sequence[str] = PROHIBITED_PUBLIC_TEXT
) -> None:
    """Refuse bytes that carry any prohibited token, matched case-insensitively."""

    text = payload.decode("utf-8").lower()
    matches = [token for token in prohibited if token in text]
    if matches:
        raise ValueError(f"{name} contains prohibited public fields: {matches}")


def atomic_publish(path: Path, payload: bytes) -> None:
    """Write ``payload`` once; identical bytes are a no-op, different bytes an error."""

    if path.exists():
        if path.is_file() and not path.is_symlink() and path.read_bytes() == payload:
            return
        raise ValueError(f"refusing to overwrite different publication bytes: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError(f"publication parent must not be a symlink: {path.parent}")
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def receipt_projection(
    receipt: Mapping[str, Any], *, campaign_cell_key: str
) -> dict[str, Any]:
    """Project one evaluation receipt onto the fields that are safe to publish.

    The failure record is reduced to its typed condition and class so provider
    text never leaves the local run directory. Every whitelisted field is
    required; a receipt missing one is not publishable.
    """

    failure = receipt.get("failure")
    safe_failure = None
    if isinstance(failure, Mapping):
        safe_failure = {
            "condition": failure.get("condition"),
            "failure_class": failure.get("failure_class"),
        }
    return {
        "source_receipt_sha256": receipt["receipt_sha256"],
        "spec_version": receipt["spec_version"],
        "status": receipt["status"],
        "inclusion_status": receipt["inclusion_status"],
        "run_plan_id": receipt["run_plan_id"],
        "run_plan_sha256": receipt["run_plan_sha256"],
        "cell_id": receipt["cell_id"],
        "case_id": receipt["case_id"],
        "case_sha256": receipt["case_sha256"],
        "episode_id": receipt["episode_id"],
        "episode_attempt_id": receipt["episode_attempt_id"],
        "cluster_id": receipt["cluster_id"],
        "cluster_level": receipt["cluster_level"],
        "primary_leaf_id": receipt["primary_leaf_id"],
        "deferred_leaf_ids": receipt.get("deferred_leaf_ids", ()),
        "replay_level": receipt["replay_level"],
        "evidence": receipt["evidence"],
        "failure": safe_failure,
        "scores": receipt["scores"],
        "observability_limits": receipt["observability_limits"],
        "campaign_cell_key": campaign_cell_key,
    }


TRAJECTORY_ROW_SCHEMA_VERSION = "aeread.sanitized_trajectory_row/0.1"
KERNEL_MANIFEST_SCHEMA_VERSION = "aeread.publication_manifest/0.1"

_PROVIDER_RESULT_PUBLIC_FIELDS = (
    "requested_model",
    "resolved_model",
    "response_id",
    "finish_reason",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "visible_output_tokens",
)
_CANONICAL_RESPONSE_PUBLIC_FIELDS = (
    "finish_reason",
    "empty",
    "truncated",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "cost_usd",
    "provider_call_ids",
    "tool_invocation_ids",
)


def _field(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)


def _pick(payload: Any, fields: Sequence[str]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    return {name: payload[name] for name in fields if name in payload}


def sanitized_trajectory_rows(evidence: Any, receipt: Any) -> tuple[dict[str, Any], ...]:
    """Project one sealed evidence store onto publishable per-action rows.

    One row per logical action, in event order, carrying what a reader needs
    to follow the trajectory and trace it back: identities and ordering, the
    parsed action, its legality and typed outcome, every attempt with its
    provider calls' route, token and cost facts, and tool dispositions. It
    never carries observations, prompts, messages, provider text or raw
    responses, or environment state; those stay in the local run directory.

    ``evidence`` is the sealed ``EvidenceStore`` of the attempt and ``receipt``
    its ``EvaluationReceipt`` (typed or as read from durable JSON); the two
    must describe the same episode attempt.
    """

    seal = evidence.verify_seal()
    for name in ("run_plan_id", "cell_id", "episode_id", "episode_attempt_id"):
        if getattr(seal, name) != _field(receipt, name):
            raise ValueError(
                f"receipt does not belong to this evidence store: {name} differs"
            )
    identity = {
        "schema_version": TRAJECTORY_ROW_SCHEMA_VERSION,
        "source_receipt_sha256": _field(receipt, "receipt_sha256"),
        "run_plan_id": _field(receipt, "run_plan_id"),
        "run_plan_sha256": _field(receipt, "run_plan_sha256"),
        "cell_id": _field(receipt, "cell_id"),
        "case_id": _field(receipt, "case_id"),
        "episode_id": _field(receipt, "episode_id"),
        "episode_attempt_id": _field(receipt, "episode_attempt_id"),
    }

    rows: list[dict[str, Any]] = []
    row_by_action: dict[str, dict[str, Any]] = {}
    attempt_by_id: dict[str, dict[str, Any]] = {}
    call_by_id: dict[str, dict[str, Any]] = {}

    for event in evidence.read_events():
        kind = event.event_type
        if kind == "logical_action_started":
            payload = evidence.read_event_payload(event)
            request = payload.get("request") if isinstance(payload, Mapping) else None
            row = {
                **identity,
                "step_index": len(rows),
                "logical_action_id": event.logical_action_id,
                "phase_id": _field(request, "phase_id"),
                "phase_instance_id": event.phase_instance_id,
                "seat_id": _field(request, "seat_id"),
                "role": _field(request, "role"),
                "profile_id": _field(request, "profile_id")
                or (payload.get("profile_id") if isinstance(payload, Mapping) else None),
                "attempts": [],
                "parse": None,
                "action": None,
                "legality": None,
                "outcome": {"status": None, "valid": None, "failure_code": None},
                "tools": [],
            }
            rows.append(row)
            row_by_action[event.logical_action_id] = row
            continue

        if kind in ("provider_call_succeeded", "provider_call_failed", "provider_call_outcome_unknown"):
            # Provider-call outcomes are recorded by the provider port, which
            # only knows the call id; resolve them through it.
            call = call_by_id.get(event.provider_call_id or "")
            if call is None:
                continue
            payload = evidence.read_event_payload(event)
            call["status"] = kind.removeprefix("provider_call_")
            if isinstance(payload, Mapping):
                call.update(_pick(payload.get("provider_result"), _PROVIDER_RESULT_PUBLIC_FIELDS))
                call.update(_pick(payload, ("cost_usd", "pricing_id", "failure_condition", "retryable", "status_code")))
            continue

        row = row_by_action.get(event.logical_action_id or "")
        if row is None:
            continue

        if kind == "action_attempt_started":
            payload = evidence.read_event_payload(event)
            attempt = {
                "action_attempt_id": event.action_attempt_id,
                **_pick(payload, ("ordinal", "retry_reason", "session_mode", "max_output_tokens")),
                "status": None,
                "failure_condition": None,
                "provider_calls": [],
                "response": None,
            }
            row["attempts"].append(attempt)
            attempt_by_id[event.action_attempt_id] = attempt
        elif kind in ("action_attempt_succeeded", "action_attempt_failed", "action_attempt_outcome_unknown"):
            attempt = attempt_by_id.get(event.action_attempt_id or "")
            if attempt is None:
                continue
            payload = evidence.read_event_payload(event)
            attempt["status"] = kind.removeprefix("action_attempt_")
            if isinstance(payload, Mapping):
                attempt["failure_condition"] = payload.get("failure_condition")
                response = payload.get("canonical_response")
                if isinstance(response, Mapping):
                    attempt["response"] = _pick(response, _CANONICAL_RESPONSE_PUBLIC_FIELDS)
        elif kind == "provider_call_started":
            attempt = attempt_by_id.get(event.action_attempt_id or "")
            if attempt is None:
                continue
            payload = evidence.read_event_payload(event)
            request = payload.get("request") if isinstance(payload, Mapping) else None
            call = {
                "provider_call_id": event.provider_call_id,
                "round": payload.get("round") if isinstance(payload, Mapping) else None,
                "provider": _field(request, "provider"),
                "requested_model": _field(request, "model"),
                "request_sha256": _field(request, "request_sha256"),
                "status": None,
            }
            attempt["provider_calls"].append(call)
            call_by_id[event.provider_call_id] = call
        elif kind == "action_parsed":
            payload = evidence.read_event_payload(event)
            result = payload.get("parse_result") if isinstance(payload, Mapping) else None
            row["parse"] = _pick(result, ("ok", "error_code"))
            row["action"] = _field(result, "action")
        elif kind == "action_legality_checked":
            payload = evidence.read_event_payload(event)
            row["legality"] = _pick(
                payload.get("legality_result") if isinstance(payload, Mapping) else None,
                ("legal", "reason"),
            )
        elif kind.startswith("logical_action_"):
            # Every terminal disposition the executor records: succeeded, failed,
            # outcome_unknown, and agent_action_failure (an invalid action the
            # environment answered with its default transition).
            payload = evidence.read_event_payload(event)
            row["outcome"] = {
                "status": kind.removeprefix("logical_action_"),
                "valid": payload.get("valid") if isinstance(payload, Mapping) else None,
                "failure_code": (
                    payload.get("failure_code", payload.get("failure_condition"))
                    if isinstance(payload, Mapping)
                    else None
                ),
            }
        elif kind.startswith(("tool_dispatch_", "tool_invocation_")):
            payload = evidence.read_event_payload(event)
            row["tools"].append(
                {
                    "event_type": kind,
                    "tool_invocation_id": event.tool_invocation_id,
                    "provider_call_id": event.provider_call_id,
                    **_pick(payload, ("tool_id", "tool_name", "failure_condition")),
                }
            )
    return tuple(rows)


def sanitized_trajectory_jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Encode trajectory rows as JSONL and refuse them if any prohibited text leaks."""

    payload = jsonl(rows)
    assert_public_payload("trajectories/sanitized.jsonl", payload)
    return payload


def _replace_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def add_publication_artifact(
    bundle_root: Path | str, relative_path: str, payload: bytes
) -> dict[str, Any]:
    """Add one artifact to a kernel-standard publication and re-seal its manifest.

    Adding a grain to an already-published bundle is a mechanical correction
    under QC §4: the artifact is written once (identical bytes are a no-op,
    different bytes are refused), the manifest's artifact table gains its
    digest, and ``manifest_sha256`` is recomputed. The previous manifest stays
    in history. Only ``aeread.publication_manifest/0.1`` manifests are known.
    """

    root = Path(bundle_root)
    manifest_path = root / "publication_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != KERNEL_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported publication manifest schema: {manifest.get('schema_version') if isinstance(manifest, Mapping) else None!r}"
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in artifacts.items()
    ):
        raise ValueError("publication manifest artifacts must map paths to digests")
    if not relative_path or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise ValueError("artifact path must be relative to the bundle root")

    atomic_publish(root / relative_path, payload)
    digest = hashlib.sha256(payload).hexdigest()
    updated_artifacts = dict(sorted({**artifacts, relative_path: digest}.items()))
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    core["artifacts"] = updated_artifacts
    updated = _sealed_manifest(core)
    if updated != dict(manifest):
        _replace_file(manifest_path, canonical_json_bytes(updated) + b"\n")
    return updated


MANIFEST_FILENAME = "publication_manifest.json"
_MANIFEST_SEAL_FIELDS = ("manifest_sha256", "publication_sha256")


def _sealed_manifest(core: Mapping[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in core.items() if key not in _MANIFEST_SEAL_FIELDS}
    return {**body, "manifest_sha256": hashlib.sha256(canonical_json_bytes(body)).hexdigest()}


def bundle_artifact_digests(bundle_root: Path | str) -> dict[str, str]:
    """Digest every published file under a bundle, keyed by path relative to the root.

    The manifest itself, hidden files, and temporary files are not artifacts.
    """

    root = Path(bundle_root)
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or path.is_symlink():
            continue
        if rel == MANIFEST_FILENAME or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if path.suffix == ".tmp":
            continue
        digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def seal_publication_manifest(
    bundle_root: Path | str,
    *,
    publication_id: str,
    privacy_boundary: Mapping[str, str],
    campaign_id: str | None = None,
    source_bindings: Mapping[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Write a fresh kernel-standard manifest over every file in the bundle.

    The one manifest layout every bundle should share: ``schema_version``,
    ``publication_id``, ``campaign_id``, ``artifacts`` (path → sha256 of
    every published file), ``privacy_boundary`` (what is included and what
    is excluded), the sanitization declaration, ``source_bindings`` (what
    the bundle was produced from), any extra family fields, and
    ``manifest_sha256`` over the rest. Refuses to overwrite an existing
    manifest; use :func:`rebuild_publication_manifest` for that.
    """

    root = Path(bundle_root)
    manifest_path = root / MANIFEST_FILENAME
    if manifest_path.exists():
        raise ValueError(f"manifest already exists, rebuild it instead: {manifest_path}")
    if set(privacy_boundary) != {"included", "excluded"}:
        raise ValueError("privacy_boundary must state exactly 'included' and 'excluded'")
    reserved = set(_MANIFEST_SEAL_FIELDS) | {"schema_version", "artifacts", "sanitization"}
    if reserved & set(fields):
        raise ValueError(f"reserved manifest fields: {sorted(reserved & set(fields))}")
    core = {
        "schema_version": KERNEL_MANIFEST_SCHEMA_VERSION,
        "publication_id": publication_id,
        "campaign_id": campaign_id,
        "artifacts": bundle_artifact_digests(root),
        "privacy_boundary": dict(privacy_boundary),
        "sanitization": dict(SANITIZATION_DECLARATION),
        "source_bindings": dict(source_bindings or {}),
        **fields,
    }
    manifest = _sealed_manifest(core)
    atomic_publish(manifest_path, canonical_json_bytes(manifest) + b"\n")
    return manifest


def rebuild_publication_manifest(
    bundle_root: Path | str, *, privacy_boundary: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Re-seal an existing manifest in the kernel layout from the files on disk.

    Every field except the artifact table and the seal is carried over, so
    provenance written by the family survives. The artifact table is
    recomputed from the bundle and compared with what the old manifest
    claimed, whichever layout it used (the path → sha256 map, or a list of
    ``{path, sha256}`` rows): a file whose digest disagrees with its recorded
    one is refused, because a rebuild must never absorb a changed report.
    New files are added, and a recorded path that no longer exists is refused.

    A manifest written without a ``privacy_boundary`` can be given one here;
    a boundary that is already declared is never silently replaced.
    """

    if privacy_boundary is not None and set(privacy_boundary) != {"included", "excluded"}:
        raise ValueError("privacy_boundary must state exactly 'included' and 'excluded'")
    root = Path(bundle_root)
    manifest_path = root / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != KERNEL_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported publication manifest schema: {manifest.get('schema_version') if isinstance(manifest, Mapping) else None!r}"
        )
    recorded_raw = manifest.get("artifacts")
    recorded: dict[str, str] = {}
    if isinstance(recorded_raw, Mapping):
        recorded = {str(path): str(digest) for path, digest in recorded_raw.items()}
    elif isinstance(recorded_raw, Sequence) and not isinstance(recorded_raw, (str, bytes)):
        for row in recorded_raw:
            if not isinstance(row, Mapping) or "path" not in row or "sha256" not in row:
                raise ValueError("artifact rows must carry 'path' and 'sha256'")
            recorded[str(row["path"])] = str(row["sha256"])
    else:
        raise ValueError("publication manifest artifacts must be a map or a list of rows")

    actual = bundle_artifact_digests(root)
    missing = sorted(set(recorded) - set(actual))
    if missing:
        raise ValueError(f"recorded artifacts missing from the bundle: {missing}")
    changed = sorted(path for path, digest in recorded.items() if actual[path] != digest)
    if changed:
        raise ValueError(f"artifact bytes differ from the recorded digest, refusing to rebuild: {changed}")

    core = {key: value for key, value in manifest.items() if key not in _MANIFEST_SEAL_FIELDS and key != "artifacts"}
    core.setdefault("sanitization", dict(SANITIZATION_DECLARATION))
    if privacy_boundary is not None:
        declared = core.get("privacy_boundary")
        if declared is not None and dict(declared) != dict(privacy_boundary):
            raise ValueError("manifest already declares a different privacy_boundary")
        core["privacy_boundary"] = dict(privacy_boundary)
    core["artifacts"] = actual
    updated = _sealed_manifest(core)
    if updated != dict(manifest):
        _replace_file(manifest_path, canonical_json_bytes(updated) + b"\n")
    return updated


__all__ = [
    "KERNEL_MANIFEST_SCHEMA_VERSION",
    "MANIFEST_FILENAME",
    "PROHIBITED_PUBLIC_TEXT",
    "SANITIZATION_DECLARATION",
    "TRAJECTORY_ROW_SCHEMA_VERSION",
    "add_publication_artifact",
    "assert_public_payload",
    "atomic_publish",
    "bundle_artifact_digests",
    "jsonl",
    "rebuild_publication_manifest",
    "receipt_projection",
    "sanitized_trajectory_jsonl",
    "sanitized_trajectory_rows",
    "seal_publication_manifest",
]
