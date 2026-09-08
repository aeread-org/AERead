"""Published plan seals must verify from their own bundle, not from source.

A frozen `plan_sha256` in a test asserts what the current source produces, and it
moves whenever the environment changes for any reason, scientific or not. That is
design-review defect 12 and it broke seven tests when the environment gained
`check_award`, listing-level verbal bias, and a relaxed action-budget range.

The seal that actually matters is different and lives in the published bundle:
`reports/campaign_plan.json` carries a digest of its own content, so a sealed
campaign stays verifiable even after the source that produced it has moved on.
This test asserts that property directly, for every procurement bundle, and it is
the one that must never be updated to make a run pass.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"
SEALED = sorted(EVIDENCE.glob("procurement_allocation*/reports/campaign_plan.json"))

#: Every sealed procurement plan digest, as published. Values are recorded so a
#: bundle cannot be quietly rewritten together with its own digest.
PUBLISHED_PLAN_DIGESTS = {
    "procurement_allocation_qwen3_235b_atlascloud_case_variance_v1":
        "9b7b2fbea8200eb9900ee063bf34255c3162f9aa7e733a5d76adb7224507a78f",
    "procurement_allocation_qwen3_235b_google_case_variance_v1":
        "7c90ba968b369ab0b03c080ea734f6aa71efdfb981d160d9ac795a2a56fff862",
    "procurement_allocation_qwen3_235b_google_constraint_ledger_v1":
        "af36b6088539cbece9967f066f9954d80e743e2350dfe17bf3b91a7b7380c36d",
    "procurement_allocation_qwen3_235b_google_constraint_ledger_v2":
        "b08c0d86956ce522b7bd401d617acf110fabea0f4637b077749e7722043ff308",
    "procurement_allocation_qwen3_30b_coreweave_case_variance_v2":
        "cef886b5f890c4a14c224a09ea4541ebfdbaacbbf872f633139827a7f42a08d5",
}


def test_at_least_one_sealed_plan_is_present() -> None:
    """Guards against the glob silently matching nothing after a path change."""
    assert SEALED, "no published procurement campaign plans found under evidence/"


@pytest.mark.parametrize("path", SEALED, ids=lambda p: p.parts[-3])
def test_sealed_plan_digest_verifies_against_its_own_content(path: Path) -> None:
    plan = json.loads(path.read_text(encoding="utf-8"))
    declared = plan["plan_sha256"]
    recomputed = hashlib.sha256(
        canonical_json_bytes({k: v for k, v in plan.items() if k != "plan_sha256"})
    ).hexdigest()
    assert recomputed == declared, (
        f"{path.parts[-3]} no longer digests to its published plan_sha256; "
        "the bundle has been edited"
    )


@pytest.mark.parametrize("path", SEALED, ids=lambda p: p.parts[-3])
def test_sealed_plan_digest_matches_the_recorded_value(path: Path) -> None:
    """Self-consistency alone would survive rewriting a bundle and its digest."""
    bundle = path.parts[-3]
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert bundle in PUBLISHED_PLAN_DIGESTS, f"unrecorded sealed bundle: {bundle}"
    assert plan["plan_sha256"] == PUBLISHED_PLAN_DIGESTS[bundle]


def test_every_recorded_digest_still_has_a_bundle() -> None:
    """A seal must not be dropped by deleting the evidence it belongs to."""
    present = {path.parts[-3] for path in SEALED}
    assert set(PUBLISHED_PLAN_DIGESTS) <= present
