# Housing V1 measurement, receipt, and replay contract

Housing V1 is the first native economic family to complete the shared-runner path from a
resolved `RunPlan` through typed measurement, durable admission receipts, and deterministic
state-and-score replay. The implementation lives in
`src/aeread/shared_runner/housing.py`; generic measurement and receipt records live in
`src/aeread/shared_runner/measurement.py` and `src/aeread/shared_runner/receipts.py`.

This is instrumentation readiness, not a paper result. The earlier one-world live admission
predates this receipt layer, and the proposed 100-world reasoning experiment has not been run
with the finalized instrument.

## Measurement semantics

One successful Housing episode emits `housing_social_welfare_leaf` with native unit
`utility_points`:

| field | meaning | valid claim |
|---|---|---|
| `R` / `social_welfare` | realized sum of tenant and landlord payoffs from signed leases | primary episode estimand |
| `L` / `optimum_lower_bound` | value `0` of the feasible do-nothing policy | lower bound on the optimum, **not** a floor on every realized agent outcome |
| `B` / `comparison_baseline` | deterministic naive scripted policy on the same pinned world | executable comparator, not a bound |
| `U` / `optimum_upper_bound` | exact max-weight assignment under full information | allocation relaxation; not a claim that the interactive policy can attain it |
| `R/U` | within-case score when `U > 0` | diagnostic normalization within the declared case only |

The scorer rejects non-finite fields, changed bound semantics, `L > U`, `B > U`, `R > U`,
seat-payoff totals that do not reconcile to welfare, or a mismatched ratio. It does **not**
reject `R < L`: a legal agent can create negative welfare even though doing nothing proves
that the optimum is at least zero.

Every tenant and landlord payoff is also recorded in `utility_by_seat` and
`capture_by_seat`. Disagreement utility is declared as zero, so observed capture equals the
observed payoff. The runner does not manufacture a Nash, Shapley, core, or fairness score;
those require additional family-owned normative objects that Housing does not currently
provide.

## Receipt admission

`EvaluationReceipt` binds:

- run, case, suite, block, sampling, analysis, episode, cluster, pair, and replicate IDs;
- the resolved profile digest for every assigned seat and every implementation pin in the
  `RunPlan`;
- event and artifact roots from `EvidenceSeal`;
- the primary leaf, typed score vector, references, validity, observability limits, and replay
  level;
- either `included` plus a valid primary score, or `excluded` plus a typed failure.

Successful CLI and batch trajectories append `score_recorded`, seal evidence, write canonical
`evaluation_receipt.json`, and publish its content digest. Reconciled provider failures,
retry exhaustion, and recovered completed attempts receive `invalid_measurement` exclusion
receipts with no economic score. They remain in coverage and cost accounting instead of
becoming zero or disappearing.

Receipt readers verify canonical bytes, the receipt digest, summary identity, the event-log
fingerprint, and the durable evidence seal. A changed receipt, result summary, event, or
artifact fails closed.

## Deterministic replay

The `state_and_score` label is earned by replay rather than declared optimistically. For every
sealed phase, `replay_housing_receipt`:

1. reconstructs the family initial state from the pinned case;
2. checks the phase spec, eligible actors, and pre-state hash;
3. reconstructs each `ActionEnvelope` from the sealed parse and legality events;
4. calls the Housing `step` hook again and checks the full transition plus post-state hash;
5. recomputes the terminal record and family outcome;
6. recomputes the typed score and compares it with both `score_recorded` and the receipt.

No provider call occurs during replay. Different model trajectories are therefore comparable
through their canonical actions, state transitions, outcomes, and typed measurements even
when reasoning telemetry differs or is unavailable.

## Validation and remaining scientific boundary

Provider-free Housing, experiment, receipt, evidence, and portability tests pass. The complete
repository suite passes `589` tests with `3` skips and `1` expected failure; the two local
loopback tests that the sandbox blocked also pass when run with loopback permission.

The instrument is ready for a fresh admission run. It does not preserve the withdrawn
pre-P0 model tables, establish performance on real housing markets, supply a price/core
oracle, or prove saturation. A paper result still requires the predeclared paired world-panel
run, receipt coverage reconciliation, cluster-level uncertainty, and the distributional and
operational decompositions in `housing_reasoning_experiment.md`.
