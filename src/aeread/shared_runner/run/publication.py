"""Family-neutral publication sanitization and atomic evidence writes.

A publication is the tracked, sanitized projection of a local run. These
helpers are the parts every family needs identically: the prohibited-text
scan, the sanitization declaration each manifest repeats, refuse-to-overwrite
atomic writes, JSONL encoding, and the receipt field whitelist. Family modules
keep their own transcript projections, summaries, and README text.
"""

from __future__ import annotations

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


__all__ = [
    "PROHIBITED_PUBLIC_TEXT",
    "SANITIZATION_DECLARATION",
    "assert_public_payload",
    "atomic_publish",
    "jsonl",
    "receipt_projection",
]
