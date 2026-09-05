import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.contract import (
    ContractError,
    load_contract,
    read_sealed,
    require_claim_boundary,
    require_disjoint_seeds,
    require_positive_number,
    require_seed_panel,
    sealed,
    sha256_bytes,
    sha256_json,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes


def test_sha256_json_hashes_canonical_bytes() -> None:
    value = {"b": 1, "a": [1, 2, {"z": None}]}
    assert sha256_json(value) == hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})
    assert sha256_bytes(b"x") == hashlib.sha256(b"x").hexdigest()


def test_sealed_adds_digest_over_core_and_is_idempotent() -> None:
    artifact = sealed({"schema_version": "x/0.1", "rows": [1, 2]})
    core = {"schema_version": "x/0.1", "rows": [1, 2]}
    assert artifact == {**core, "artifact_sha256": sha256_json(core)}
    assert sealed(artifact) == artifact
    assert sealed({**core, "artifact_sha256": "stale"}) == artifact


def test_read_sealed_accepts_intact_and_rejects_tampered_or_non_object(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(canonical_json_bytes(sealed({"k": "v"})))
    assert read_sealed(path) == sealed({"k": "v"})

    tampered = dict(sealed({"k": "v"}))
    tampered["k"] = "w"
    path.write_bytes(canonical_json_bytes(tampered))
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        read_sealed(path)

    path.write_bytes(b"[1, 2]")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        read_sealed(path)


def _write_contract(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_load_contract_returns_the_raw_object_when_shape_and_schema_match(tmp_path: Path) -> None:
    path = _write_contract(tmp_path, {"schema_version": "f/0.1", "campaign_id": "c1"})
    loaded = load_contract(
        path, schema_version="f/0.1", required_keys={"schema_version", "campaign_id"}
    )
    assert loaded == {"schema_version": "f/0.1", "campaign_id": "c1"}
    assert isinstance(loaded, dict)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ([1], "must be a JSON object"),
        ({"schema_version": "f/0.1"}, "fields are incomplete or unexpected"),
        (
            {"schema_version": "f/0.1", "campaign_id": "c1", "extra": 1},
            "fields are incomplete or unexpected",
        ),
        ({"schema_version": "f/0.2", "campaign_id": "c1"}, "unsupported contract schema"),
    ],
)
def test_load_contract_rejects_shape_and_schema_drift(
    tmp_path: Path, value: object, message: str
) -> None:
    path = _write_contract(tmp_path, value)
    with pytest.raises(ContractError, match=message):
        load_contract(
            path, schema_version="f/0.1", required_keys={"schema_version", "campaign_id"}
        )


def test_load_contract_runs_family_validators_in_order_and_propagates(tmp_path: Path) -> None:
    path = _write_contract(tmp_path, {"schema_version": "f/0.1", "campaign_id": "c1"})
    seen: list[str] = []

    def first(contract: dict) -> None:
        seen.append("first")

    def second(contract: dict) -> None:
        seen.append("second")
        raise ValueError("family-specific drift")

    with pytest.raises(ValueError, match="family-specific drift"):
        load_contract(
            path,
            schema_version="f/0.1",
            required_keys={"schema_version", "campaign_id"},
            validators=(first, second),
        )
    assert seen == ["first", "second"]


def test_contract_error_is_a_value_error() -> None:
    assert issubclass(ContractError, ValueError)


def test_require_seed_panel_returns_tuple_for_valid_seeds() -> None:
    assert require_seed_panel([3, 1, 2]) == (3, 1, 2)
    assert require_seed_panel([7], minimum=1) == (7,)


@pytest.mark.parametrize(
    "seeds",
    [None, "1,2,3", [], [1, 1], [-1], [True, 2], [1.0, 2], [1, 2]],
)
def test_require_seed_panel_rejects_invalid_or_short_panels(seeds: object) -> None:
    with pytest.raises(ContractError, match="inference seeds"):
        require_seed_panel(seeds, minimum=3)


def test_require_seed_panel_labels_the_stage_in_its_error() -> None:
    with pytest.raises(ContractError, match="variance_pilot inference seeds"):
        require_seed_panel([1, 1], label="variance_pilot")


def test_require_disjoint_seeds_rejects_overlap_between_any_two_stages() -> None:
    require_disjoint_seeds(("full", [1]), ("pilot", [2, 3]), ("holdout", [4]))
    with pytest.raises(ContractError, match="full and holdout"):
        require_disjoint_seeds(("full", [1]), ("pilot", [2]), ("holdout", [1, 4]))


def test_require_claim_boundary_demands_literal_false_for_each_claim_key() -> None:
    require_claim_boundary({"winner_claim_allowed": False, "other": 1})
    require_claim_boundary(
        {"winner_claim_allowed": False, "inferential_model_ranking_allowed": False},
        keys=("winner_claim_allowed", "inferential_model_ranking_allowed"),
    )
    for bad in ({"winner_claim_allowed": True}, {"winner_claim_allowed": None}, {}):
        with pytest.raises(ContractError, match="winner_claim_allowed"):
            require_claim_boundary(bad)
    with pytest.raises(ContractError, match="variance_pilot"):
        require_claim_boundary({"winner_claim_allowed": 0}, label="variance_pilot")


@pytest.mark.parametrize("value", [1, 0.5, 10**9])
def test_require_positive_number_accepts_positive_ints_and_floats(value: object) -> None:
    assert require_positive_number(value, label="cost_ceiling_usd") == value


@pytest.mark.parametrize("value", [0, -1, True, "1", None, float("nan")])
def test_require_positive_number_rejects_non_positive_bool_and_non_numeric(value: object) -> None:
    with pytest.raises(ContractError, match="cost_ceiling_usd"):
        require_positive_number(value, label="cost_ceiling_usd")
