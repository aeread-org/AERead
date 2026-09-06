from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread_families.procurement_allocation.failure_register import (
    REGISTER_ID,
    build_register,
    publish_register,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def register() -> dict:
    return build_register(repository_root=REPOSITORY_ROOT)


def test_the_register_only_counts_rows_that_actually_executed(register: dict) -> None:
    """Derived reports also publish a `rows` key.

    The regret decomposition publishes one analysis row per published trajectory
    with no execution `status`. An earlier draft read all 216 of them as untyped
    operational failures, which would have made the register over-report by two
    orders of magnitude. Every counted row must carry a status.
    """
    for failure in register["failures"]:
        assert "status" in failure, failure["source"]
    summary = register["summary"]
    assert summary["operational_failures"] < summary["rows_scanned"] / 10, (
        "implausible operational failure rate; the extractor is probably reading "
        "a derived report's rows as trajectories"
    )


def test_every_failure_names_a_source_and_a_kind(register: dict) -> None:
    for failure in register["failures"]:
        assert failure["source"].startswith("evidence/")
        assert failure["kind"] in {"operational", "measured_violation"}
        if failure["kind"] == "measured_violation":
            assert failure["violations"], failure["case_id"]
            assert failure["status"] == "completed"
        else:
            assert failure["status"] != "completed"


def test_sources_are_digest_bound_and_current(register: dict) -> None:
    import hashlib

    assert register["sources"], "no evidence reports were scanned"
    for relative, digest in register["sources"].items():
        path = REPOSITORY_ROOT / relative
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, relative


def test_the_register_is_regenerable_and_digest_stable() -> None:
    first = build_register(repository_root=REPOSITORY_ROOT)
    second = build_register(repository_root=REPOSITORY_ROOT)
    assert first["artifact_sha256"] == second["artifact_sha256"]


def test_publish_writes_a_bound_manifest(tmp_path: Path, register: dict) -> None:
    import hashlib

    root = tmp_path / "evidence" / REGISTER_ID
    manifest = publish_register(register, publication_root=root)
    written = root / "reports" / "failure_register.json"
    assert json.loads(written.read_text())["artifact_sha256"] == register["artifact_sha256"]
    assert manifest["artifacts"]["reports/failure_register.json"] == hashlib.sha256(
        written.read_bytes()
    ).hexdigest()
    with pytest.raises(ValueError):
        publish_register(register, publication_root=tmp_path / "runs" / REGISTER_ID)
