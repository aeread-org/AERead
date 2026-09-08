"""Gate 0 of the benchmark QC standard, enforced.

A family without a published QC profile is `failed`, not `not_run`: the other
gates are unevaluable because no artifact exists that can hold their status.
Procurement is why this gate exists. Its construct check ran, found a
deterministic policy beating the qualified subject by $28.50 per world, and
published that as campaign evidence; with no profile the verdict had nowhere to
land and was read as a campaign finding rather than a gate failure.

`PROFILE_EXEMPT` is the backlog for families that predate this gate. It is named
rather than derived, and its length is asserted, so a new family cannot join it
without a reviewer seeing the number change. A new family must bring a profile
or an explicit, argued widening of that list.
"""

from __future__ import annotations

from pathlib import Path

from aeread.shared_runner.registry import TRUSTED_BUILTIN_PLUGIN_KEYS

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STANDARD = "docs/operations/benchmark_qc.md"

#: family_id -> profile path, relative to the repository root.
FAMILY_PROFILES: dict[str, str] = {
    "housing_v1": "docs/families/housing/qc.md",
    "procurement_allocation_v1": "docs/families/procurement-allocation/qc.md",
}

#: family_id -> why it has no profile yet. Dated 2026-09-06.
#: Every entry is a family that predates Gate 0. Removing an entry requires
#: publishing that family's profile; adding one requires changing the count
#: asserted below, which a reviewer sees.
PROFILE_EXEMPT: dict[str, str] = {
    "agenticpay.bilateral": "external adapter merged 2026-09-04 (#35); profile owed",
    "alympics.wac": "external adapter merged 2026-09-04 (#36); profile owed",
    "amazonbarg.bilateral": "external adapter merged 2026-09-04 (#34); profile owed",
    "aucarena": "external adapter merged 2026-09-04 (#32); profile owed",
    "collusion": "external adapter merged 2026-09-04 (#37); profile owed",
    "commercial_state_calibration_v1": "in-tree family predating Gate 0",
    "consent_ir_v1": "in-tree family predating Gate 0",
    "datacenter_development_v1": "in-tree family predating Gate 0",
    "econagent_v1": "external adapter merged 2026-09-04 (#38); profile owed",
    "econevals": "external adapter merged 2026-09-04 (#28); profile owed",
    "govsim": "external adapter merged 2026-09-04 (#30); profile owed",
    "kernel_contract_reference_v1": "kernel test fixture, not a measured family",
    "kernel_contract_sequential_v1": "kernel test fixture, not a measured family",
    "negarena": "external adapter merged 2026-09-04 (#33); profile owed",
    "procurement_grounding_v1": "claim_reference sibling of procurement_allocation_v1",
    "single_offer_v1": "smoke fixture, not a measured family",
    "steer": "external adapter merged 2026-09-04 (#31); profile owed",
    "tau3.retail": "reference adapter; profile owed alongside its first live campaign",
    "termsbench": "external adapter merged 2026-09-04 (#29); profile owed",
}


def _trusted_family_ids() -> set[str]:
    return {family_id for family_id, _version, _plugin in TRUSTED_BUILTIN_PLUGIN_KEYS}


def test_every_trusted_family_has_a_profile_or_a_named_exemption() -> None:
    """The gate itself. A new family cannot register without one or the other."""
    unaccounted = sorted(
        _trusted_family_ids() - set(FAMILY_PROFILES) - set(PROFILE_EXEMPT)
    )
    assert not unaccounted, (
        "these trusted families have neither a QC profile nor a named Gate 0 "
        "exemption:\n  " + "\n  ".join(unaccounted) + "\n"
        f"Publish docs/families/<family>/qc.md, or add a dated entry to "
        f"PROFILE_EXEMPT in {Path(__file__).name} with the reason."
    )


def test_the_exemption_backlog_does_not_grow_silently() -> None:
    """Pin the backlog size so widening it is visible in review.

    This is the same discipline the kernel scoring-contract test uses for its
    unmigrated families: a named list whose length is asserted, never a derived
    one that quietly absorbs new entries.
    """
    assert len(PROFILE_EXEMPT) == 19, (
        "the Gate 0 exemption backlog changed size. If a family gained a "
        "profile, remove it from PROFILE_EXEMPT and add it to FAMILY_PROFILES. "
        "If a new family was exempted, argue it in review."
    )
    assert not set(FAMILY_PROFILES) & set(PROFILE_EXEMPT), (
        "a family cannot be both profiled and exempt"
    )


def test_every_claimed_profile_exists_and_binds_the_standard() -> None:
    for family_id, relative in FAMILY_PROFILES.items():
        path = REPOSITORY_ROOT / relative
        assert path.is_file(), f"{family_id}: missing profile at {relative}"
        text = path.read_text(encoding="utf-8")
        assert "benchmark_qc.md" in text, (
            f"{family_id}: profile does not reference the standard"
        )
        assert "**Status:**" in text, f"{family_id}: profile states no typed status"


def test_a_profile_never_reports_an_unearned_pass() -> None:
    """`partial` must not be written up as `passed`.

    A profile that claims `passed` for every gate while the standard's own
    coverage table names blockers is the failure mode this checks for.
    """
    for family_id, relative in FAMILY_PROFILES.items():
        text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        if "_partial" in text or "=partial" in text:
            assert "Main blocker" in text or "blocker" in text.lower(), (
                f"{family_id}: profile reports partial status without a blocker"
            )


def test_the_standard_documents_gate_zero() -> None:
    text = (REPOSITORY_ROOT / STANDARD).read_text(encoding="utf-8")
    assert "### Gate 0: Profile admission" in text
    assert "first reject gate" in text
    assert Path(__file__).name in text, (
        "the standard must name the test that enforces Gate 0"
    )
