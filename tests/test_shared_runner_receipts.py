from __future__ import annotations

import dataclasses

import pytest

import hashlib

from aeread.shared_runner import (
    EvaluationFailure,
    EvaluationReceipt,
    EvidenceSeal,
    EstimandSpec,
    ImplementationPin,
    MeasurementContractError,
    MeasurementImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
    canonical_json_bytes,
    read_evaluation_receipt,
    seal_evaluation_receipt,
    verify_evaluation_receipt,
    write_evaluation_receipt,
)


def _implementation(identifier: str, marker: str) -> MeasurementImplementationRef:
    return MeasurementImplementationRef(identifier, "1.0.0", marker * 64)


def _leaf(identifier: str = "housing_social_welfare") -> MeasurementLeafSpec:
    domain = ValidityDomainSpec(
        domain_id="housing_v1_terminal_domain",
        domain_version="1.0.0",
        schema_ref="housing_v1/outcome/1",
        predicate=_implementation("housing_outcome_validity", "a"),
    )
    estimand = EstimandSpec(
        estimand_id=identifier,
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="utility_points",
        validity_domain=domain,
    )
    return MeasurementLeafSpec(
        leaf_id=f"{identifier}_leaf",
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="housing_full_information_upper_bound",
                reference_version="1.0.0",
                reference_kind="objective_upper_bound",
                input_scope="terminal_state",
                units="utility_points",
                source_sha256="b" * 64,
                implementation=_implementation("housing_exact_assignment", "c"),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id=identifier,
                objective_version="1.0.0",
                direction="maximize",
                units="utility_points",
                feasible_set="one tenant and one landlord per signed lease",
                information_set="full case values and costs",
                horizon="one housing episode",
                environment_condition="pinned housing world",
                opponent_condition="controlled landlord policy",
                validity_domain=domain,
            ),
        ),
        scorer=_implementation("housing_social_welfare_scorer", "d"),
    )


def _score(*, valid: bool = True, identifier: str = "housing_social_welfare") -> ScoreEnvelope:
    leaf = _leaf(identifier)
    if valid:
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(7.0, "utility_points"),
            metrics={"social_welfare": MetricValue(7.0, "utility_points")},
            reference_values={
                "feasible_floor": MetricValue(0.0, "utility_points"),
                "oracle_upper_bound": MetricValue(10.0, "utility_points"),
            },
            validity=ValidityReport("valid"),
            evidence_refs=("artifact_outcome",),
        )
    return ScoreEnvelope(
        status="invalid_measurement",
        leaf=leaf,
        primary=None,
        metrics={},
        reference_values={},
        validity=ValidityReport("invalid", ("oracle bound is below observed welfare",)),
        evidence_refs=("artifact_outcome",),
    )


def _seal() -> EvidenceSeal:
    return EvidenceSeal(
        run_plan_id="run_plan_001",
        cell_id="cell_001",
        episode_id="episode_001",
        episode_attempt_id="episode_attempt_001",
        event_count=12,
        artifact_count=4,
        event_root_sha256="e" * 64,
        artifact_root_sha256="f" * 64,
    )


def _plan_pins(score: ScoreEnvelope) -> tuple[ImplementationPin, ...]:
    implementations = (
        (score.leaf.estimand.validity_domain.predicate, "scorer"),
        (score.leaf.verifier.reference.implementation, "reference"),
        (score.leaf.scorer, "scorer"),
    )
    return tuple(
        ImplementationPin(
            component_id=implementation.implementation_id,
            kind=kind,
            version=implementation.version,
            sha256=implementation.content_sha256,
        )
        for implementation, kind in implementations
    )


def _receipt(**changes: object) -> EvaluationReceipt:
    score = _score()
    values: dict[str, object] = {
        "spec_version": "aeread.receipt/0.1",
        "receipt_sha256": None,
        "status": "ok",
        "inclusion_status": "included",
        "run_plan_id": "run_plan_001",
        "run_plan_sha256": "1" * 64,
        "cell_id": "cell_001",
        "case_id": "housing_case_001",
        "case_sha256": "2" * 64,
        "suite_id": "housing_suite_v1",
        "suite_version": "1.0.0",
        "block_id": "housing_controlled_landlords",
        "sampling_plan_id": "housing_sample_v1",
        "analysis_plan_id": "housing_analysis_v1",
        "episode_id": "episode_001",
        "episode_attempt_id": "episode_attempt_001",
        "cluster_id": "housing_world_001",
        "cluster_level": "world",
        "observations_per_cluster": 6,
        "parent_cluster_id": None,
        "pair_id": "housing_world_001_pair",
        "paired_fields": {"world_seed": 11},
        "replicate_index": 0,
        "panel_mode": "fixed_panel",
        "agent_profile_sha256_by_seat": {"tenant_0": "3" * 64},
        "implementation_refs": (
            score.leaf.estimand.validity_domain.predicate,
            score.leaf.verifier.reference.implementation,
            score.leaf.scorer,
        ),
        "plan_implementation_pins": _plan_pins(score),
        "evidence": _seal(),
        "primary_leaf_id": score.leaf.leaf_id,
        "scores": (score,),
        "failure": None,
        "observability_limits": (),
        "replay_level": "state_and_score",
    }
    values.update(changes)
    return EvaluationReceipt(**values)


def test_receipt_seals_all_primary_identity_measurement_and_evidence_roots() -> None:
    receipt = seal_evaluation_receipt(_receipt())

    assert receipt.receipt_sha256 is not None
    assert len(receipt.receipt_sha256) == 64
    assert receipt.evidence.event_root_sha256 == "e" * 64
    assert receipt.scores[0].primary == MetricValue(7.0, "utility_points")
    verify_evaluation_receipt(receipt)


def test_receipt_hash_is_canonical_and_detects_tampering() -> None:
    first = seal_evaluation_receipt(_receipt())
    second = seal_evaluation_receipt(_receipt(paired_fields={"world_seed": 11}))
    assert first.receipt_sha256 == second.receipt_sha256

    tampered = dataclasses.replace(first, replicate_index=1)
    with pytest.raises(MeasurementContractError, match="receipt_sha256"):
        verify_evaluation_receipt(tampered)


def test_receipt_rejects_evidence_from_another_episode_identity() -> None:
    wrong_seal = dataclasses.replace(_seal(), episode_id="episode_999")
    with pytest.raises(MeasurementContractError, match="evidence identity"):
        _receipt(evidence=wrong_seal)


def test_invalid_primary_measurement_is_a_typed_exclusion_not_economic_zero() -> None:
    invalid_score = _score(valid=False)
    excluded = _receipt(
        status="invalid_measurement",
        inclusion_status="excluded",
        implementation_refs=(
            invalid_score.leaf.estimand.validity_domain.predicate,
            invalid_score.leaf.verifier.reference.implementation,
            invalid_score.leaf.scorer,
        ),
        primary_leaf_id=invalid_score.leaf.leaf_id,
        scores=(invalid_score,),
        failure=EvaluationFailure(
            failure_class="oracle_or_scorer_failure",
            condition="invalid_bound",
            message="oracle bound is below observed welfare",
        ),
        replay_level="score_only",
    )
    receipt = seal_evaluation_receipt(excluded)
    assert receipt.scores[0].primary is None
    verify_evaluation_receipt(receipt)

    with pytest.raises(MeasurementContractError, match="invalid primary"):
        _receipt(scores=(invalid_score,), primary_leaf_id=invalid_score.leaf.leaf_id)


def test_invalid_diagnostic_leaf_does_not_erase_a_valid_primary_measurement() -> None:
    primary = _score()
    diagnostic = _score(valid=False, identifier="housing_capture_diagnostic")
    receipt = seal_evaluation_receipt(
        _receipt(
            scores=(primary, diagnostic),
            implementation_refs=(
                primary.leaf.estimand.validity_domain.predicate,
                primary.leaf.verifier.reference.implementation,
                primary.leaf.scorer,
                diagnostic.leaf.estimand.validity_domain.predicate,
                diagnostic.leaf.verifier.reference.implementation,
                diagnostic.leaf.scorer,
            ),
        )
    )
    assert receipt.inclusion_status == "included"
    assert receipt.scores[1].status == "invalid_measurement"


def test_receipt_requires_every_measurement_implementation_pin() -> None:
    score = _score()
    with pytest.raises(MeasurementContractError, match="implementation_refs"):
        _receipt(implementation_refs=(score.leaf.scorer,))


def test_receipt_requires_measurement_code_to_match_the_resolved_run_plan() -> None:
    score = _score()
    mismatched = tuple(
        dataclasses.replace(pin, sha256="9" * 64)
        if pin.component_id == score.leaf.scorer.implementation_id
        else pin
        for pin in _plan_pins(score)
    )

    with pytest.raises(MeasurementContractError, match="plan_implementation_pins"):
        _receipt(plan_implementation_pins=mismatched)


def test_durable_receipt_round_trip_is_canonical_and_tamper_evident(tmp_path) -> None:
    receipt = seal_evaluation_receipt(_receipt())
    destination = tmp_path / "evaluation_receipt.json"

    write_evaluation_receipt(receipt, destination)
    loaded = read_evaluation_receipt(destination)

    assert loaded["receipt_sha256"] == receipt.receipt_sha256
    write_evaluation_receipt(receipt, destination)
    destination.write_text(
        destination.read_text(encoding="utf-8").replace(
            '"replay_level":"state_and_score"', '"replay_level":"none"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(MeasurementContractError, match="receipt_sha256"):
        read_evaluation_receipt(destination)


def test_receipt_inapplicable_leaf_ids_defaults_to_empty_and_is_sorted() -> None:
    receipt = _receipt(inapplicable_leaf_ids=("housing_capture_diagnostic", "housing_social_welfare_leaf_diagnostic"))
    assert receipt.inapplicable_leaf_ids == (
        "housing_capture_diagnostic",
        "housing_social_welfare_leaf_diagnostic",
    )
    assert _receipt().inapplicable_leaf_ids == ()


def test_receipt_rejects_duplicate_inapplicable_leaf_ids() -> None:
    with pytest.raises(MeasurementContractError, match="inapplicable_leaf_ids"):
        _receipt(
            inapplicable_leaf_ids=("some_leaf_v1", "some_leaf_v1"),
        )


def test_receipt_rejects_an_inapplicable_leaf_id_that_overlaps_a_produced_score() -> None:
    score = _score()
    with pytest.raises(MeasurementContractError, match="inapplicable_leaf_ids"):
        _receipt(inapplicable_leaf_ids=(score.leaf.leaf_id,))


def test_receipt_rejects_an_inapplicable_leaf_id_that_overlaps_deferred_leaf_ids() -> None:
    """Ruling R13 rule 4: every declared leaf has exactly one disposition on
    every receipt -- returned, deferred, or inapplicable -- so the two
    fields the kernel is not itself sealing here (this is a direct
    construction, not a finalize call) must still be mutually exclusive.
    """
    with pytest.raises(MeasurementContractError, match="inapplicable_leaf_ids"):
        _receipt(
            deferred_leaf_ids=("some_other_leaf_v1",),
            inapplicable_leaf_ids=("some_other_leaf_v1",),
        )


# Ruling R13 (kernel_scoring_contract_spec.md): a golden digest computed
# against the PRE-R13 kernel (commit cda0a736 -- this branch's own fork
# point, before EvaluationReceipt carried inapplicable_leaf_ids at all),
# pinned so this test cannot pass merely because both sides of a same-code
# comparison happen to agree with each other -- see
# test_leaf_policy_declaration_without_seat_scope_is_digest_neutral's own
# docstring in test_shared_runner_schemas.py for why that distinction
# matters. Produced by:
#
#   git archive cda0a736 src | tar -x -C /tmp/pre_r13/src/
#   git show cda0a736:tests/test_shared_runner_receipts.py \
#       > /tmp/pre_r13/receipts_test_pre_r13.py
#   <this repo's venv python> -c '
#       import sys, hashlib
#       sys.path.insert(0, "/tmp/pre_r13/src/src")
#       sys.path.insert(0, "/tmp/pre_r13")
#       import aeread.shared_runner as sr
#       import receipts_test_pre_r13 as t
#       sealed = t.seal_evaluation_receipt(t._receipt())
#       print(hashlib.sha256(sr.canonical_json_bytes(sealed)).hexdigest())
#   '
_PRE_R13_RECEIPT_WITHOUT_INAPPLICABLE_LEAF_IDS_SHA256 = (
    "4a8c8e334387725cf6a393addb95600c8061de554c757313e96aa9a362352269"
)


def test_receipt_without_inapplicable_leaf_ids_is_digest_neutral() -> None:
    """Ruling R13: ``inapplicable_leaf_ids`` is added to ``EvaluationReceipt``
    after receipts with an empty (or absent) leaf policy were already being
    sealed, written, and replayed. A receipt that never uses it (every
    receipt sealed by every family today, since none declares a
    case_conditional leaf) must hash byte-for-byte as it did before this
    field existed -- both the canonical JSON bytes AND the ``receipt_sha256``
    digest computed over them (``_receipt_content_sha256``), since those two
    must stay mutually consistent for ``write_evaluation_receipt`` +
    ``read_evaluation_receipt`` to round-trip at all (see
    ``test_durable_receipt_round_trip_is_canonical_and_tamper_evident``,
    which exercises exactly that round trip and would itself start failing
    for every receipt if this omission were ever inconsistent between the
    two).
    """
    sealed = seal_evaluation_receipt(_receipt())
    assert (
        hashlib.sha256(canonical_json_bytes(sealed)).hexdigest()
        == _PRE_R13_RECEIPT_WITHOUT_INAPPLICABLE_LEAF_IDS_SHA256
    )
    assert '"inapplicable_leaf_ids"' not in canonical_json_bytes(sealed).decode("utf-8")

    # Setting inapplicable_leaf_ids to a non-empty, disjoint value must
    # change the digest -- proving the field is not silently dropped the
    # way an unguarded _CANONICAL_OMIT_IF_DEFAULT regression (or a
    # _receipt_content_sha256 that forgot to honour it) would drop it.
    with_inapplicable = seal_evaluation_receipt(
        _receipt(inapplicable_leaf_ids=("some_other_leaf_v1",))
    )
    assert canonical_json_bytes(with_inapplicable) != canonical_json_bytes(sealed)
    verify_evaluation_receipt(with_inapplicable)


def test_durable_receipt_round_trip_preserves_a_non_default_inapplicable_leaf_ids(
    tmp_path,
) -> None:
    """The write/verify/read triad must stay consistent for a receipt that
    actually uses the new field, not only for the digest-neutral default
    case above -- a regression in ``_receipt_content_sha256``'s
    omit-if-default handling could plausibly break one case and not the
    other (the default case incorrectly omitting when it should not, or
    the non-default case incorrectly omitting when it must not), so both
    are exercised end to end through durable JSON.
    """
    receipt = seal_evaluation_receipt(
        _receipt(inapplicable_leaf_ids=("some_other_leaf_v1",))
    )
    destination = tmp_path / "evaluation_receipt.json"
    write_evaluation_receipt(receipt, destination)
    loaded = read_evaluation_receipt(destination)
    assert loaded["inapplicable_leaf_ids"] == ["some_other_leaf_v1"]
    assert loaded["receipt_sha256"] == receipt.receipt_sha256
