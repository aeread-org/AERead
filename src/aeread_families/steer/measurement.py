"""Measurement declarations for the ``steer`` adapter (spec section 2).

STEER's pinned commit deleted its own evaluation submodule (Governing
facts: "Remove STEER evaluation submodule") -- there is no upstream scoring
code to delegate to or achieve parity against, unlike
``aeread_families.tau3_retail``. ``canonical_point`` equality is therefore
entirely AERead-authored here.

One leaf per case, identical shape for all 8 declared elements:

* **``steer_answer_key`` (deterministic).** Does the submitted
  ``option_id`` equal the gold ``correct_option_id`` recorded in upstream's
  own ``Answers`` frame (already flattened into the cached row's
  ``correct_option_id`` by ``steer_bridge_driver.py``)? ``reference
  .source_sha256`` pins THIS question's own content digest --
  ``row["source_sha256"]`` -- never a corpus-wide or element-wide hash, so
  two different questions never share one reference identity.

There is no second, judge-dependent leaf: STEER's MCQA answer key is a
deterministic equality check end to end, so "judge-dependent components
stay separately labelled" has no second component to label here.

An illegal action (option_id out of this question's own range) or a
malformed one (unparseable prose) is never scored as an economic 0.0.
``environment.py``'s ``legal``/``parse_action`` already reject those before
``step`` ever runs (spec section 4, goldens 3-4); this module's
:func:`score_answer_key` reports them as ``invalid_measurement``
(``verifier_taxonomy.md`` section 9) whenever the terminal outcome it is
handed carries a ``failure_code`` -- it never re-derives legality itself.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.measurement import (
    EstimandSpec,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)

from .cases import CORPUS_ID, FAMILY_VERSION

LEAF_VERSION = "0.1.0"
ESTIMAND_VERSION = "0.1.0"
REFERENCE_VERSION = "0.1.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = CORPUS_ID
DOMAIN_VERSION = FAMILY_VERSION

ANSWER_KEY_ESTIMAND_ID = "steer_answer_key"
ANSWER_KEY_LEAF_ID = "steer_answer_key"
GOLD_OPTION_REFERENCE_ID = "steer_gold_option"
# Matches `environment.py`'s `SCORER_ID`/`family_manifest().scoring.scorer_id`
# exactly (never re-derived from it -- `environment.py` imports from this
# module, so the reverse import would be circular). `finalize_family_execution`
# (the production finalization path) seals a receipt whose
# `implementation_refs` -- this leaf's `estimand.validity_domain.predicate`
# and `scorer` -- must each resolve against a pin in the sealed RunPlan
# (`aeread.shared_runner.receipts.EvaluationReceipt
# ._validate_and_freeze_plan_pins`); a RunPlan may only carry the pins
# `family.scoring.scorer_id`/`oracle_id`/`reference_provider_ids` declare
# (`resolver._check_pins` rejects any other pin as "unreferenced"), so the
# predicate and scorer share this one id -- mirroring
# `aeread.shared_runner.housing._housing_measurement_leaf`'s identical
# `predicate`/`scorer` id-sharing convention exactly, rather than inventing a
# pin bucket the family manifest's 3-slot scoring taxonomy has no room for.
ANSWER_KEY_SCORER_ID = "steer_scorer"
# The oracle: pinned separately (spec section 1's own note that STEER's own
# evaluation submodule was deleted upstream -- `steer_bridge_driver.py`'s
# flattening IS the ground truth this family answers against), and declared
# as `family_manifest().scoring.oracle_id` so its own "reference" pin is
# required rather than "unreferenced" (mirrors housing's `oracle_id`
# convention exactly).
ANSWER_KEY_REFERENCE_IMPLEMENTATION_ID = "steer_bridge.flatten_answer_key"


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``tau3_retail.measurement``'s identical convention of hashing a
    sibling source file rather than inventing an opaque marker: the pin
    changes exactly when the code it names changes.
    """
    return ImplementationRef(
        implementation_id=implementation_id,
        version=IMPLEMENTATION_VERSION,
        content_sha256=_file_sha256(filename),
    )


def _predicate_and_scorer_sha256() -> str:
    """The one combined digest shared by the predicate and the scorer.

    Mirrors ``housing._housing_source_digests``'s ``combined_digest`` exactly
    (``environment.py``'s ``validate_payload`` backs the predicate,
    ``measurement.py``'s ``score_answer_key`` backs the scorer -- both named
    by the one id, ``ANSWER_KEY_SCORER_ID``, so both pin changes exactly when
    either file changes, never when an unrelated file does).
    """
    environment_bytes = Path(__file__).with_name("environment.py").read_bytes()
    measurement_bytes = Path(__file__).read_bytes()
    return hashlib.sha256(environment_bytes + measurement_bytes).hexdigest()


def _validity_domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id=DOMAIN_ID,
        domain_version=DOMAIN_VERSION,
        schema_ref=f"{CORPUS_ID}/case_payload",
        predicate=ImplementationRef(
            implementation_id=ANSWER_KEY_SCORER_ID,
            version=IMPLEMENTATION_VERSION,
            content_sha256=_predicate_and_scorer_sha256(),
        ),
    )


def build_answer_key_leaf(row: Mapping[str, Any]) -> MeasurementLeafSpec:
    """The one verifier leaf declared for every case (spec section 2).

    ``row`` is the same cached, flattened record ``SteerPlugin
    .initial_state``/``_load_cached_row`` already reads -- it carries
    ``source_sha256`` (this question's own content digest) and
    ``correct_option_id`` (the gold answer, recovered by
    :func:`build_scorer` below, never by this function itself).

    Direction is ``"maximize"`` explicitly: all 8 declared elements are
    accuracy-against-answer-key, not a violation count (spec section 2's
    note distinguishing this from ``problem_bound_case_audit.md`` P09's
    lower-is-better GARP scoring).
    """
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=ANSWER_KEY_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="answer",
        direction="maximize",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=GOLD_OPTION_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="canonical_point",
        input_scope="answer",
        units="pass",
        source_sha256=row["source_sha256"],
        implementation=_implementation(
            ANSWER_KEY_REFERENCE_IMPLEMENTATION_ID, "steer_bridge_driver.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="canonical_reference",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=ANSWER_KEY_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=ImplementationRef(
            implementation_id=ANSWER_KEY_SCORER_ID,
            version=IMPLEMENTATION_VERSION,
            content_sha256=_predicate_and_scorer_sha256(),
        ),
    )


# ---------------------------------------------------------------------------
# Scorer.
# ---------------------------------------------------------------------------


def score_answer_key(
    leaf: MeasurementLeafSpec,
    *,
    correct_option_id: int,
    selected_option_id: int | None,
    valid: bool,
    failure_code: str | None,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score the declared leaf from one terminal outcome (spec section 2/4).

    Golden 1/2 (``valid`` True -- the phase's own ``legal()`` already
    admitted the submission): the primary measurement is exactly 1.0 or 0.0
    by index equality against ``correct_option_id``, never any softer
    match. Golden 3/4 (``valid`` False -- an out-of-range index or
    unparseable prose already rejected by ``legal()``/``parse_action``):
    reported as ``invalid_measurement`` with ``failure_code`` as the
    recorded reason -- never coerced into an economic 0.0
    (``verifier_taxonomy.md`` section 9). This function never re-derives
    legality itself; it only reports what the phase already decided.
    """
    if not valid:
        reason = failure_code or "invalid_submission"
        return ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=ValidityReport("invalid", reasons=(reason,)),
            evidence_refs=evidence_refs,
        )
    score = 1.0 if selected_option_id == correct_option_id else 0.0
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(score, "pass"),
        metrics={},
        reference_values={"gold_option_id": MetricValue(float(correct_option_id), "pass")},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True, slots=True)
class SteerScorer:
    """One case's single declared leaf, plus the scorer for it.

    Mirrors ``tau3_retail.measurement.Tau3RetailScorer``'s convention:
    ``environment.py``'s ``build_scorer`` hook returns one of these. The one
    real production finalization path,
    ``aeread.shared_runner.family_evaluation.finalize_family_execution``,
    calls whatever ``build_scorer`` returns AS A CALLABLE
    (``plugin.build_scorer(family_case)(outcome, evidence_refs=...)``),
    mirroring ``housing.py``'s ``build_scorer`` closure and
    ``smoke.py``'s ``lambda outcome: outcome`` -- so :meth:`__call__` below
    is not a convenience alias, it is the shape production finalization
    requires. :meth:`score` remains the named entry point tests call
    directly.
    """

    question_id: str
    correct_option_id: int
    leaf: MeasurementLeafSpec

    @property
    def leaves(self) -> tuple[MeasurementLeafSpec, ...]:
        return (self.leaf,)

    def score(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        """Score one terminal ``SteerPlugin.outcome()`` mapping.

        ``outcome["failure_code"] is None`` iff the phase's own
        ``legal()``/``parse_action`` admitted the submission (equivalently,
        ``outcome["termination_reason"] == "answered"``) -- read straight
        from the outcome the phase already produced rather than re-derived,
        so this scorer can never disagree with the phase about what counts
        as a valid submission.
        """
        return score_answer_key(
            self.leaf,
            correct_option_id=self.correct_option_id,
            selected_option_id=outcome["selected_option_id"],
            valid=outcome["failure_code"] is None,
            failure_code=outcome["failure_code"],
            evidence_refs=evidence_refs,
        )

    def __call__(
        self, outcome: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()
    ) -> ScoreEnvelope:
        """Identical to :meth:`score` -- the shape
        ``finalize_family_execution`` actually calls (spec section 2's own
        finding: production scoring invokes ``build_scorer(...)`` as a bare
        callable, never ``.score(...)``)."""
        return self.score(outcome, evidence_refs=evidence_refs)


def build_scorer(row: Mapping[str, Any]) -> SteerScorer:
    """Build the one ``SteerScorer`` for a case's cached, flattened row."""
    return SteerScorer(
        question_id=row["question_id"],
        correct_option_id=row["correct_option_id"],
        leaf=build_answer_key_leaf(row),
    )


__all__ = [
    "ANSWER_KEY_ESTIMAND_ID",
    "ANSWER_KEY_LEAF_ID",
    "GOLD_OPTION_REFERENCE_ID",
    "SteerScorer",
    "build_answer_key_leaf",
    "build_scorer",
    "score_answer_key",
]
