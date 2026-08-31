# Receipt-derived research harness

**Status:** draft implementation for review

**Stack:** this work sits above the shared-runner portability contracts. It does not replace
`RunPlan`, canonical events, `EvaluationReceipt`, or any family verifier.

## Research question

The execution kernel already records auditable evidence, but paper analysis also needs a
complete and queryable experimental ledger. In particular, a score table must not silently
drop planned cells that never ran, merge harness identity with runner build identity, or call
two executions replicates when their pinned treatment differs.

The research harness therefore provides **derived views and preflight checks**. Canonical
plans, events, artifacts, and receipts remain the only sources of truth.

```mermaid
flowchart TD
    P[Sealed RunPlan] --> G[Complete planned-cell grid]
    E[Canonical event chains] --> EP[Operational + domain phase projection]
    R[Verified EvaluationReceipts] --> A[Attempt rows]
    G --> C[Cell rows: included / excluded / not_started]
    A --> C
    C --> L[Campaign coverage ledger]
    P --> D[Design observations]
    D --> Q[Overlap, alias and cluster preflight]
    L --> T[Derived campaigns / cells / attempts tables]
```

## Implemented contracts

### 1. Complete planned-cell ledger

`build_research_ledger(plan, receipts)` starts from every `PlanCell`, not from successful
outputs. Each cell receives exactly one research disposition:

- `included`: one receipt is admitted for measurement;
- `excluded`: at least one typed receipt exists, but none is admitted;
- `not_started`: no receipt exists for the planned cell.

Every receipt attempt remains in the attempt table. A failed attempt followed by one admitted
attempt therefore stays observable without double-counting the cell. More than one included
receipt for a cell is rejected as ambiguous.

The campaign row reports expected, receipted, included, excluded, and not-started cell counts,
plus coverage. Performance is intentionally not aggregated here; each family's typed
`ScoreEnvelope` retains its own units and meaning.

### 2. Repeat-equivalence identity

Each cell row carries `repeat_equivalence_sha256`. The digest includes the case/world,
treatment block, cluster and pairing identity, resolved profiles by seat, execution mode,
budgets, harness/runtime configuration, and implementation pins. It excludes repetition and
sampling-replicate ordinals.

Thus two attempts may be treated as replicates only when their scientifically relevant setup
matches. The digest is stricter than a hand-authored `repeat_group_id` and can be compared
across run plans.

### 3. Two independent phase axes

`project_evidence_events(evidence)` adds a runner-operational phase:

- `planning`: the runner opens a declared family phase;
- `execution`: model actions, provider calls, parsing, legality, and tools;
- `recovery`: attempts explicitly caused by a recorded retry reason;
- `finalization`: state transition, phase close, episode termination, and family outcome.

This is **not** a claim about a model's cognitive process. The domain axis remains separate:
Housing may report `contact`, `respond`, and `commit`; refund may report a stateful service
workflow. Reasoning text remains diagnostic evidence rather than the primary outcome.

An unknown canonical event type has no guessed phase. Projection fails until its mapping is
reviewed, making event-schema drift visible.

### 4. Experimental-design preflight

`audit_experimental_design(...)` operates on explicit `DesignObservation` records. Before a
paid campaign, it rejects:

- a focal factor with only one observed level;
- factor levels with fewer than the predeclared independent-cluster minimum;
- a focal factor that never varies within a common nuisance stratum;
- individual levels with no within-stratum comparison; and
- two focal factors that are perfectly aliased.

This is a structural identification screen, not a power calculation and not a causal proof.
Its purpose is to stop layouts such as “planner harness always receives the high budget” before
post-hoc regression is asked to repair an unidentifiable comparison.

## Research-table mapping

| Derived table | Unit | Important fields |
|---|---|---|
| `campaigns` | one sealed run plan | suite, harness by profile, runtime by profile, pricing identity, complete coverage counts |
| `cells` | one planned cell | case, family, treatment block, cluster/pair, replicate index, disposition, receipt count, repeat-equivalence digest |
| `attempts` | one verified receipt | inclusion/failure, replay level, primary native-unit measurement, event/artifact roots |
| event projection | one canonical event | operational phase, domain phase/instance, action/call/tool identities, visibility, payload hash |

These are in-memory deterministic projections. A future Parquet/SQL writer should consume
these rows and bind its own schema/version hash; it must not become an alternate mutable truth
store.

## Deliberate non-goals of this draft

- No automatic `EvaluationReceipt` finalizer or interrupted-run resume.
- No CSV, Parquet, database, or remote trajectory storage backend.
- No cost aggregation or repricing; the campaign view only exposes declared price-catalog
  identities already present in harness configuration.
- No statistical power calculation, effect model, leaderboard, or universal cross-family
  score.
- No Housing, Tau3/refund, or supply-chain semantics in the shared module.

## Reviewer decisions requested

1. Should price catalogs become first-class `RunPlan.implementation_pins` rather than profile
   harness configuration before the first paper campaign?
2. Is “opening a family phase” the right operational meaning for `planning`, or should the
   operational taxonomy use a less model-like label in the next schema version?
3. Should one included receipt per planned cell remain a hard invariant, with all prior retries
   preserved only as excluded attempt rows?

## Code and tests

- Implementation: `src/aeread/shared_runner/research.py`
- Contract tests: `tests/test_shared_runner_research.py`

The implementation was developed red/green: the new tests first failed at import, then passed
after the contracts were added.
