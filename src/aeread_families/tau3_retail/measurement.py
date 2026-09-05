"""Measurement declarations for the tau3.retail adapter (spec section 7).

Upstream scores a retail task from several components multiplied together
into one ``RewardInfo.reward``. This module never folds them back into one
kernel score. It declares two separate, explicitly labelled
``MeasurementLeafSpec`` claims and computes each independently:

* **Leaf 1 -- ``tau3_retail_db_state`` (deterministic).** The paper-primary
  claim: does the predicted database end state match upstream's own gold
  replay? Declared for every task. Scored by delegating to upstream's own
  ``tau2.evaluator.evaluator_env.EnvironmentEvaluator`` through
  :class:`~aeread_families.tau3_retail.tau2_bridge.Tau2Bridge` -- this module
  never recomputes or re-derives DB equality itself (adapter rule 2).
* **Leaf 2 -- ``tau3_retail_nl_assertions`` (judge-dependent).** Declared
  *only* for the 40/114 tasks whose ``evaluation_criteria.nl_assertions`` is
  a non-empty list -- the only tasks for which upstream's NL judge actually
  fires. The other 72 tasks list ``NL_ASSERTION`` in ``reward_basis`` but
  carry an empty (or, per the raw corpus, ``null``) assertion list; upstream
  short-circuits those to a deterministic 1.0 with no LLM call, so declaring
  a judged claim for them would misreport the majority of the corpus (spec
  section 7 / UNRESOLVED Q8). Scored from already-recorded judge verdicts
  ``{nl_assertion, met, justification}`` -- produced once, out of band, by
  the pinned judge model and sealed as evidence -- never by re-invoking a
  judge here. That keeps this module provider-free: it makes no model call
  and no network call, ever (adapter rule 1).

Descriptive diagnostics (tool errors, redundant tool calls, turns, and --
when available -- token counts) are attached to leaf 1's ``ScoreEnvelope``
``metrics`` mapping, never to its ``primary`` measurement: ``metrics`` has no
pass/fail meaning in the kernel's own schema
(``aeread.shared_runner.measurement.ScoreEnvelope``), so recording them there
cannot change what counts as a correct answer.

One documented deviation from the literal spec text: section 7 writes
``input_scope="transcript"`` for leaf 2. The kernel's real
``EstimandSpec``/``ReferenceSpec`` only accept
``{"answer", "terminal_state", "trajectory", "distribution"}`` -- "transcript"
is not a legal value and construction raises ``MeasurementContractError`` for
it. This module uses ``"trajectory"`` (the kernel's own name for exactly
that: the full sequence of visible messages) instead.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.measurement import (
    EstimandSpec,
    FamilyScoreSet,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.evaluation import FamilyScoringInput

from .tau2_bridge import Tau2Bridge

LEAF_VERSION = "1.0.0"
ESTIMAND_VERSION = "1.0.0"
REFERENCE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "0.1.0"

DOMAIN_ID = "tau3_retail_base_v1"
DOMAIN_VERSION = "1.0.0"

DB_STATE_ESTIMAND_ID = "tau3_retail_db_state"
DB_STATE_LEAF_ID = "tau3_retail_db_state_leaf"
GOLD_DATABASE_REFERENCE_ID = "tau3_gold_database"
DB_STATE_SCORER_ID = "tau3_retail_scorer"

NL_ASSERTIONS_ESTIMAND_ID = "tau3_retail_nl_assertions"
NL_ASSERTIONS_LEAF_ID = "tau3_retail_nl_assertions_leaf"
NL_ASSERTIONS_REFERENCE_ID = "tau3_retail_nl_assertions_rubric"
NL_ASSERTIONS_SCORER_ID = "tau3_retail_nl_assertions_scorer"

# Upstream forces reward 0 for any termination other than agent/user stop
# (evaluator.py:119-129, evaluate_simulation's dispatch level -- one layer
# above EnvironmentEvaluator itself). Mirrored here rather than left to the
# delegated call, since EnvironmentEvaluator.calculate_reward alone has no
# opinion on termination reason.
NON_FORCING_TERMINATION_REASONS = frozenset({"agent_stop", "user_stop"})


def _file_sha256(name: str) -> str:
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def _implementation(implementation_id: str, filename: str) -> ImplementationRef:
    """Pin one adapter source file as the concrete code behind a claim.

    Mirrors ``smoke.py``'s convention of hashing a sibling source file
    rather than inventing an opaque marker: ``filename`` is the actual
    adapter module that performs the referenced step (e.g.
    ``tau2_bridge.py`` for "the code that delegates to upstream's
    evaluator"), so the pin changes exactly when that code changes.
    """
    return ImplementationRef(
        implementation_id=implementation_id,
        version=IMPLEMENTATION_VERSION,
        content_sha256=_file_sha256(filename),
    )


def _validity_domain() -> ValidityDomainSpec:
    return ValidityDomainSpec(
        domain_id=DOMAIN_ID,
        domain_version=DOMAIN_VERSION,
        schema_ref="tau3_retail_base_v1/case_payload",
        predicate=_implementation(
            "tau3_retail_base_domain_predicate", "environment.py"
        ),
    )


def build_db_state_leaf(pins: Mapping[str, Any]) -> MeasurementLeafSpec:
    """Leaf 1: the deterministic, paper-primary DB-equality claim.

    Declared for all 114 tasks (governing fact: DB always gates reward_basis
    for retail/base). ``reference.source_sha256`` pins the gold database
    source itself -- the same ``db.json`` sha256 every case's
    ``payload.pins.db_sha256`` already carries -- not any code.
    """
    domain = _validity_domain()
    estimand = EstimandSpec(
        estimand_id=DB_STATE_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        input_scope="terminal_state",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=GOLD_DATABASE_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="terminal_state_equivalence",
        input_scope="terminal_state",
        units="pass",
        source_sha256=pins["db_sha256"],
        implementation=_implementation(
            "tau3_retail_environment_evaluator_bridge", "tau2_bridge.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="canonical_reference",
        evaluation_class="deterministic",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=DB_STATE_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(DB_STATE_SCORER_ID, "measurement.py"),
    )


def nl_assertions_present(task: Mapping[str, Any]) -> bool:
    """Whether upstream's NL judge actually fires for this task.

    True only for tasks whose ``evaluation_criteria.nl_assertions`` is a
    *non-empty list*. In the raw corpus this field is ``null`` for 72
    tasks and ``[]`` for 2 (the DB-only tasks, ids "33"/"34") -- both must
    return False here, and both do: ``isinstance(None, list)`` and
    ``isinstance([], list) and len([]) > 0`` are both false.
    """
    criteria = task.get("evaluation_criteria")
    if not isinstance(criteria, Mapping):
        return False
    nl_assertions = criteria.get("nl_assertions")
    return isinstance(nl_assertions, list) and len(nl_assertions) > 0


def build_nl_assertions_leaf(task: Mapping[str, Any]) -> MeasurementLeafSpec | None:
    """Leaf 2: the judge-dependent NL-assertions claim, or ``None``.

    Returns ``None`` -- meaning "declare no judged claim for this task" --
    whenever :func:`nl_assertions_present` is false, per spec section 7 /
    UNRESOLVED Q8. ``reference.source_sha256`` pins the task's own rubric
    text (its ``nl_assertions`` list), so two tasks with different
    assertions never collide.
    """
    if not nl_assertions_present(task):
        return None
    domain = _validity_domain()
    nl_assertions = list(task["evaluation_criteria"]["nl_assertions"])
    rubric_sha256 = hashlib.sha256(canonical_json_bytes(nl_assertions)).hexdigest()
    estimand = EstimandSpec(
        estimand_id=NL_ASSERTIONS_ESTIMAND_ID,
        estimand_version=ESTIMAND_VERSION,
        # Spec section 7 literally writes input_scope="transcript"; the
        # kernel's real EstimandSpec/ReferenceSpec only accept "trajectory"
        # for this meaning -- see this module's docstring.
        input_scope="trajectory",
        direction="none",
        units="pass",
        validity_domain=domain,
    )
    reference = ReferenceSpec(
        reference_id=NL_ASSERTIONS_REFERENCE_ID,
        reference_version=REFERENCE_VERSION,
        reference_kind="rubric_score",
        input_scope="trajectory",
        units="pass",
        source_sha256=rubric_sha256,
        implementation=_implementation(
            "tau3_retail_nl_assertions_recorded_verdicts", "measurement.py"
        ),
    )
    verifier = VerifierSpec(
        verifier_family="rater_judge",
        evaluation_class="judge_dependent",
        reference=reference,
    )
    return MeasurementLeafSpec(
        leaf_id=NL_ASSERTIONS_LEAF_ID,
        leaf_version=LEAF_VERSION,
        estimand=estimand,
        verifier=verifier,
        scorer=_implementation(NL_ASSERTIONS_SCORER_ID, "measurement.py"),
    )


def build_leaves(
    task: Mapping[str, Any], pins: Mapping[str, Any]
) -> tuple[MeasurementLeafSpec, ...]:
    """The measurement leaves declared for one task: always 1, sometimes 2.

    Exactly ``(db_state_leaf,)`` when the task carries no non-empty
    ``nl_assertions`` list; exactly ``(db_state_leaf, nl_assertions_leaf)``,
    separately labelled (``evaluation_class`` ``"deterministic"`` vs
    ``"judge_dependent"``), when it does. There is no third, composed leaf:
    ``MeasurementLeafSpec.composition_kind`` is fixed to ``"leaf"`` by the
    kernel itself, and upstream's product of the two components is computed
    only in a parity report, never sealed here (spec section 7).
    """
    leaves: list[MeasurementLeafSpec] = [build_db_state_leaf(pins)]
    nl_leaf = build_nl_assertions_leaf(task)
    if nl_leaf is not None:
        leaves.append(nl_leaf)
    return tuple(leaves)


# ---------------------------------------------------------------------------
# Diagnostics -- descriptive only, never part of a leaf's primary measurement.
# ---------------------------------------------------------------------------


def build_diagnostics(
    *,
    messages: Sequence[Mapping[str, Any]],
    num_tool_errors: int,
    upstream_step_count: int,
    token_usage: Mapping[str, int] | None = None,
) -> dict[str, MetricValue]:
    """Descriptive-only counters: tool errors, redundant calls, turns, tokens.

    None of these change what counts as a correct answer -- they belong in
    a ``ScoreEnvelope.metrics`` mapping, never in ``primary``. A "redundant"
    tool call is one whose ``(name, arguments)`` pair was already issued
    earlier in the same episode (by either seat); this is a simple
    transcript-level count, not an upstream concept, so it is computed
    locally rather than delegated. ``token_usage`` is accepted, not
    computed: real per-episode token counts belong to the provider/harness
    layer (``ProviderResult``/cost tracking in ``execution.py``), which this
    provider-free scripted harness does not populate -- passing ``None``
    (the default) simply omits the ``token_*`` entries rather than
    fabricating zeros.
    """
    seen: set[tuple[str, bytes]] = set()
    redundant = 0
    for message in messages:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            key = (
                str(call.get("name")),
                canonical_json_bytes(call.get("arguments", {})),
            )
            if key in seen:
                redundant += 1
            else:
                seen.add(key)
    diagnostics: dict[str, MetricValue] = {
        "tool_error_count": MetricValue(float(num_tool_errors), "count"),
        "redundant_tool_call_count": MetricValue(float(redundant), "count"),
        "turn_count": MetricValue(float(upstream_step_count), "count"),
    }
    if token_usage:
        for key, value in token_usage.items():
            diagnostics[f"token_{key}"] = MetricValue(float(value), "count")
    return diagnostics


# ---------------------------------------------------------------------------
# Scorers.
# ---------------------------------------------------------------------------


def score_db_state(
    leaf: MeasurementLeafSpec,
    *,
    bridge: Tau2Bridge,
    task: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
    termination_reason: str,
    diagnostics: Mapping[str, MetricValue] | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 1 by delegating DB comparison to upstream's own evaluator.

    Never recomputes DB equality itself: :meth:`Tau2Bridge.evaluate_env`
    shells out to the pinned upstream checkout and calls
    ``tau2.evaluator.evaluator_env.EnvironmentEvaluator.calculate_reward``,
    which replays the task's gold actions and the recorded trajectory
    through upstream's own tool layer and compares upstream's own db
    hashes; this function only reads the ``RewardType.DB`` component of the
    result it returns. Termination-reason forcing (any termination other
    than agent/user stop forces reward 0, mirroring
    ``evaluator.py:119-129``) is applied here, one layer above
    ``EnvironmentEvaluator`` itself, exactly where upstream applies it.
    """
    if termination_reason not in NON_FORCING_TERMINATION_REASONS:
        return ScoreEnvelope(
            status="ok",
            leaf=leaf,
            primary=MetricValue(
                0.0,
                "pass",
                metadata={
                    "forced_by": "termination_reason",
                    "termination_reason": termination_reason,
                },
            ),
            metrics=dict(diagnostics or {}),
            reference_values={},
            validity=ValidityReport("valid"),
            evidence_refs=evidence_refs,
        )
    result = bridge.evaluate_env(task=task, messages=list(messages))
    breakdown = result.get("reward_breakdown") or {}
    if "DB" not in breakdown:
        raise ValueError(
            "upstream EnvironmentEvaluator returned no DB reward component "
            "for a task whose reward_basis is expected to include DB"
        )
    db_reward = float(breakdown["DB"])
    db_check = result.get("db_check") or {}
    metrics: dict[str, MetricValue] = dict(diagnostics or {})
    if "db_match" in db_check:
        metrics["db_match"] = MetricValue(
            1.0 if db_check["db_match"] else 0.0, "pass"
        )
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(db_reward, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


def score_nl_assertions(
    leaf: MeasurementLeafSpec,
    *,
    verdicts: Sequence[Mapping[str, Any]],
    evidence_refs: tuple[str, ...] = (),
) -> ScoreEnvelope:
    """Score leaf 2 from already-recorded judge verdicts.

    Never re-invokes a judge (no model call, no network call): ``verdicts``
    must already have been produced once, out of band, by the pinned judge
    model and sealed as evidence (spec section 7/9 -- "replay reads the
    recorded verdicts and never re-calls the judge"). The reduction itself
    -- reward 1.0 iff every verdict is met, else 0.0 -- is upstream's own
    one-line rule (``NLAssertionsEvaluator.calculate_reward``:
    ``all(check.met for check in checks)``); it is reproduced verbatim here
    rather than delegated because delegating it would require calling
    upstream's ``generate()``, i.e. a live model call. See
    ``tests/test_tau3_retail_measurement.py`` for a bridge-gated
    cross-check that this local reduction agrees with upstream's real code
    (via a monkeypatched, network-free judge call) whenever the bridge is
    available.
    """
    if not verdicts:
        raise ValueError("score_nl_assertions requires at least one recorded verdict")
    all_met = all(bool(verdict["met"]) for verdict in verdicts)
    metrics = {
        f"assertion_{index}_met": MetricValue(
            1.0 if verdict["met"] else 0.0, "pass"
        )
        for index, verdict in enumerate(verdicts)
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=MetricValue(1.0 if all_met else 0.0, "pass"),
        metrics=metrics,
        reference_values={},
        validity=ValidityReport("valid"),
        evidence_refs=evidence_refs,
    )


@dataclass(frozen=True, slots=True)
class Tau3RetailScorer:
    """One case's fixed set of declared leaves, plus the scorers for them.

    ``environment.py``'s ``build_scorer`` hook returns one of these per the
    spec's note that "build_scorer returns the scorer from measurement.py
    (so it becomes live the day the kernel calls it)" -- the current kernel
    does not yet invoke ``build_scorer`` itself (see spec section 7's "the
    current kernel neither invokes scorers nor attaches ScoreEnvelopes to
    CellExecution" and ``smoke.py``'s identical ``lambda outcome: outcome``
    placeholder), so both ``score_db_state``/``score_nl_assertions`` above
    are also exercised directly by tests today.
    """

    task: Mapping[str, Any]
    pins: Mapping[str, Any]
    leaves: tuple[MeasurementLeafSpec, ...]
    bridge: Tau2Bridge | None = None

    @property
    def db_state_leaf(self) -> MeasurementLeafSpec:
        return self.leaves[0]

    @property
    def nl_assertions_leaf(self) -> MeasurementLeafSpec | None:
        return self.leaves[1] if len(self.leaves) > 1 else None

    def score_db_state(
        self,
        *,
        bridge: Tau2Bridge,
        messages: Sequence[Mapping[str, Any]],
        termination_reason: str,
        diagnostics: Mapping[str, MetricValue] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        return score_db_state(
            self.db_state_leaf,
            bridge=bridge,
            task=self.task,
            messages=messages,
            termination_reason=termination_reason,
            diagnostics=diagnostics,
            evidence_refs=evidence_refs,
        )

    def score_nl_assertions(
        self,
        *,
        verdicts: Sequence[Mapping[str, Any]],
        evidence_refs: tuple[str, ...] = (),
    ) -> ScoreEnvelope:
        nl_leaf = self.nl_assertions_leaf
        if nl_leaf is None:
            raise ValueError(
                "this case declares no judge-dependent leaf "
                "(nl_assertions_present(task) is False)"
            )
        return score_nl_assertions(
            nl_leaf, verdicts=verdicts, evidence_refs=evidence_refs
        )

    def __call__(
        self,
        scoring_input: FamilyScoringInput,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> FamilyScoreSet:
        if self.bridge is None:
            raise ValueError("tau3 retail scoring requires the pinned tau2 bridge")
        final_state: Mapping[str, Any] | None = None
        for phase in reversed(scoring_input.phase_instances):
            if phase.transitions:
                candidate = phase.transitions[-1].state
                if isinstance(candidate, Mapping):
                    final_state = candidate
                    break
        if final_state is None:
            raise ValueError("tau3 retail scoring input has no replayed terminal state")
        messages = final_state.get("messages")
        if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
            raise ValueError("tau3 retail terminal state has no message trajectory")
        outcome = scoring_input.outcome
        termination_reason = outcome.get("termination_reason")
        if not isinstance(termination_reason, str):
            raise ValueError("tau3 retail outcome has no termination reason")
        diagnostics = build_diagnostics(
            messages=messages,
            num_tool_errors=int(final_state.get("num_tool_errors", 0)),
            upstream_step_count=int(outcome.get("upstream_step_count", 0)),
        )
        db_score = self.score_db_state(
            bridge=self.bridge,
            messages=json.loads(canonical_json_bytes(messages)),
            termination_reason=termination_reason,
            diagnostics=diagnostics,
            evidence_refs=evidence_refs,
        )
        return FamilyScoreSet(
            primary_leaf_id=DB_STATE_LEAF_ID,
            scores=(db_score,),
            admission_leaf_ids=(DB_STATE_LEAF_ID,),
        )


def build_scorer(
    task: Mapping[str, Any],
    pins: Mapping[str, Any],
    *,
    bridge: Tau2Bridge | None = None,
) -> Tau3RetailScorer:
    """Build the one ``Tau3RetailScorer`` for a case's ``family_case``."""
    return Tau3RetailScorer(
        task=task,
        pins=pins,
        leaves=build_leaves(task, pins),
        bridge=bridge,
    )


__all__ = [
    "DB_STATE_ESTIMAND_ID",
    "DB_STATE_LEAF_ID",
    "GOLD_DATABASE_REFERENCE_ID",
    "NL_ASSERTIONS_ESTIMAND_ID",
    "NL_ASSERTIONS_LEAF_ID",
    "NL_ASSERTIONS_REFERENCE_ID",
    "NON_FORCING_TERMINATION_REASONS",
    "Tau3RetailScorer",
    "build_db_state_leaf",
    "build_diagnostics",
    "build_leaves",
    "build_nl_assertions_leaf",
    "build_scorer",
    "nl_assertions_present",
    "score_db_state",
    "score_nl_assertions",
]
