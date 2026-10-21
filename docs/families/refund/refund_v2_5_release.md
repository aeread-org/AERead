# Refund V2.5: four-seat developmental release

## Compatibility verdict

The family environment is compatible with the shared-runner APIs on
the original `main@dec1a40f` target: qualified registration, resolved plans, controlled-seat context,
phase scheduling, typed score leaves, durable receipts and independent replay.
It does not replace the existing Refund V1/V2.1 environments.

The 2026-10-21 refresh also checks the exact shared-runner source snapshot from
GitHub `main@1dd48cf5a443c94eccdd0597144fbf1c0e693525`; see the
[V7.1 port note](refund_v2_5_v71_port.md) for fresh results and their scope.
No kernel source changes are proposed by this PR.

**This release is provider-free.** The historical Arena campaign adapter is not
shipped or silently copied into the kernel. Paid execution through the public
entrypoint is rejected before credentials/client initialization: the current
Arena adapter does not preserve completed invalid JSON for family contract scoring
and does not honor all profile controls. Follow [#267](https://github.com/aeread-org/AERead/issues/267)
and the broader adoption audit [#264](https://github.com/aeread-org/AERead/issues/264).
A future paid campaign needs a separately reviewed adapter, a sealed full-trajectory
gate, declared spend/time/call limits and the kernel operational halt rule.
No paid-equivalence, published model ranking or normative benchmark promotion is
claimed here.

### Publication QC is not satisfied

This is a developmental release, not a publication-qualified benchmark.
[Issue #290](https://github.com/aeread-org/AERead/issues/290) records unresolved
Gate 3 concerns about trivial/legal-path baselines, evidence discrimination,
Customer action-space difficulty, payment-verifier scope and independent human
QC provenance. Scripted full scores and receipt replay do not resolve those
construct-validity concerns. The subsequent Refund V3 redesign is separate,
paused work and is not included in this V2.5 PR. Legacy module names such as
`v2_5_seat_design_v3` are V2.5 component revisions, not Refund V3.

The user separately approved **developmental design QC** for this public release.
Its records live under `cases/refund_v25/qc/`; V2.1's approval is not reused.
Approval does not authorize paid calls. The kernel verifies the contribution and
QC evidence digests. It is not an independent scientific validation of the policy
population.

## Reproduce from a clean checkout

```bash
python -m pip install -e '.[dev]'
# Default: 24 core cases under each of the four controlled seats.
python -m aeread_families.refund.v2_5_release --output /tmp/refund-v25-core-new
# Exactly one active seat; every other seat is deterministic scripted.
python -m aeread_families.refund.v2_5_release \
  --panel v51_payments --active-agents payments --seed 301 \
  --output /tmp/refund-v25-payments-new
# All public developmental cohorts × four seats, no holdout.
python -m aeread_families.refund.v2_5_release \
  --panel all --seed 301 --output /tmp/refund-v25-all-new
python -m pytest tests/test_refund_v25*.py tests/test_refund_v24_policy_interactions.py -q
```

Every output must be new: no overwrite, restart, top-up or best-answer selection.
Provider-free means that all provider responses are deterministic reference
profiles, including the nominal active seat; it tests environment conformance,
**not LLM ability**. Resolving a profile with `provider="arena"` makes no call and
does not qualify that profile for execution.

The output contains `release_contract.json`, the kernel's plan/task/attempt evidence,
sealed evaluation receipts, and `summary.json`. Every successful trajectory is
replayed and independently audited through the current kernel, with all seven
score leaves and all four collaboration metrics checked for full score/coverage.

For a later kernel-publication bundle generated from these public runs:

```bash
export AEREAD_REFUND_V25_RUN_ROOT=/tmp/refund-v25-all-new
aeread verify-replay PATH_TO_PUBLISHED_BUNDLE \
  --run-root "$AEREAD_REFUND_V25_RUN_ROOT" \
  --setup aeread_families.refund.v2_5_release:replay_setup
```

The factory reconstructs only a uniquely bound, provider-free public plan and
rejects foreign/changed identities. This PR does not publish a bundle, so the
above requires an actual kernel publication, not a synthetic manifest.

## Case contract and workflow

Each case binds category (`perishable/electronics/software/apparel`), public claim,
private fact values, requestable fact IDs, complete rendered policy, independent
reference resolution, pair ID and declared changed facts. Public branch JSON
makes conditional requirements, precedence, enum values, money formulae and
terminal routes explicit; the agent never receives the hidden reference answer.

```text
customer claim
  → intake selects requested facts
  → customer discloses only those facts
  → policy requests conditional facts OR submits a resolution
  → customer confirms the current proposal
  → payments executes once OR emits no mutation
```

Customer sees its private facts and current request/proposal but no policy oracle.
Intake sees public work-order rules, IDs and disclosure state, not values.
Policy sees public policy plus disclosed facts, not hidden facts/reference.
Payments sees only confirmed obligations and its execution ledger/contract, not
unconfirmed policy proposals, hidden customer facts or the policy oracle.

The rich resolution distinguishes eligibility, remedy, workflow, amount,
refund method, mutation, liability, policy basis and reason code. Holds, review,
request-evidence, partial remedies and return/inspection routes are not collapsed
into approve/deny.

## Public cohorts, not one undifferentiated case count

| Public panel | Variants per seed | Mechanism |
|---|---:|---|
| core | 24 | V2.4's 12 category × interaction policy pairs |
| policy | 76 | Core + 12 stress + 6 frontier + 8 frontier-hard pairs |
| v3_common | 8 | Four-category shared trajectories |
| v3_intake | 24 | Public scope, priority, batch-capacity and decoy selection |
| v3_payments | 18 | Residuals, allocation and repeated delivery |
| v3_customer | 16 | Disclosure overlap and current-proposal confirmation |
| v4_payments | 8 | Revision reduction, scope, pending settlement and redelivery |
| v4_customer | 4 | Authoritative source and immutable confirmation terms |
| v5_intake | 8 | Prerequisites, authorization, utility/budget and tie-breaks |
| v51_payments | 12 | Multi-tender waterfall/fallback with explicit wire units |
| v5_customer | 6 | Per-fact source authority, revision ceilings and revocations |

The V7.1 port additionally exposes `v71_intake` and `v71_customer`, each with
32 developmental variants per seed. Their synthetic release checkpoints,
multi-round planning and source/proposal binding are documented in
[the V7.1 port note](refund_v2_5_v71_port.md). Reserved templates are not included
in these public default panels.

For seed 301 these are **268 cohort placements, 244 distinct case IDs**; core is
already included in policy. `--panel all` deliberately tests that overlap under
both interfaces: **1,072 trajectories**, not 1,072 distinct cases. The original
reduced four-seat calibration panel (132 seat-case instances and repeated
measurements) is a different, historical selection and is not silently recreated.

Holdout builders remain available to researchers, but public qualification does
not execute holdout or assert held-out model performance. Templates shared across
seeds are not independent mechanisms. World seeds vary declared numerical,
evidence, identity, timing and branch conditions where the builder implements
them, while preserving the pair's minimal declared intervention. Seed variation
must be inspected per cohort; it is not equivalent to sampling new templates.

## Why the difficulties are legitimate

- Policy: independent precedence ladders, evidence authority/reversal,
  identity/payment holds, liability overrides, residual reconciliation and
  piecewise tax/cap boundaries. Difficulty follows the public rules and
  conditional fact graph, not an undisclosed oracle or ambiguous prose.
- Intake: the work order makes source relevance, scope, prerequisites,
  capacity and collection utility observable. Equivalent request order/subsets
  receive consistent legality/quality; hidden fact values cannot select a batch.
- Payments: reduce revisions before scope filtering, ignore unrelated records,
  distinguish pending/settled/reversed events, conserve cents and apply declared
  waterfall/fallback order. Redelivery checks exactly-once behavior against the
  updated ledger, not just string matching an ID.
- Customer: requested disclosure, authorized source revision and exact current
  proposal terms are separately testable; archived/draft terms are decoys.

V5.1 explicitly states that ledger calculations use integer cents, while
`amount` and every allocation are **major currency units** at the output boundary.
The clarification does not alter reducers, policy references or scoring.
The earlier Customer/Intake panels are unchanged; V7.1 is a separately named
extension, not a silent replacement of those panels or historical results.

Admission checks minimal pair changes, meaningful contrasts or explicitly typed
invariance controls, fact-domain completeness, unique branch/precedence paths,
unambiguous ledger revisions, dependency cycles, rendered contracts and scripted
trajectories. Collection budgets derive from the finite fact graph so a legal
single-fact collection path cannot exhaust an arbitrary three-disclosure limit.

## Measurement and interpretation

Seven portable leaves are retained:
`policy_semantic, workflow, payment, evidence, contract, end_to_end, operational`.
Four collaboration diagnostics are carried in end-to-end leaf metadata:
`customer_disclosure_integrity, intake_fact_request_quality,
customer_confirmation_integrity, payment_proposal_binding`, with opportunity
counts and coverage. Missing opportunities are not silently full credit.

`end_to_end` is a strict trajectory composite, **not a universal model utility**.
Partial semantic credit is diagnostic. A canonical alias can preserve policy
meaning while failing contract adherence; changed eligibility/remedy/amount/
liability is a genuine semantic failure. A resolution rejected as premature is
retained, so correct policy content is not conflated with evidence/transition
failure. Execution/format/binding errors have distinct tags and coverage.

All production scores consume the kernel's verified deterministic re-execution
(`FamilyScoringInput`), never a trusted copy of a live episode's score. The
kernel seals actions/state hashes, checks replay agreement and binds the
controlled subject seats from the plan. Diagnostics outside the active seat can
describe a scripted counterpart or missing downstream opportunity; report them
with seat and coverage, not as independent active-seat errors.

## Scientific limits and future work

This is an open developmental environment, not a confirmatory leaderboard.
Historical repeated-model experiments are not included as public evidence.
Existing saturation findings motivate future design work, but customer/intake
cases and frozen historical scoring were deliberately preserved.

Before model comparison: freeze a balanced common panel, profiles, seed/repetition
schedule and statistical plan; qualify every full trajectory and operational
budget; then run identical instances across models. Report case distributions,
missingness, repeated-execution variability, paired differences/95% intervals
and small prespecified Holm-adjusted contrasts, clustering shared mechanisms/
pairs/repetitions appropriately. Use exact replay rather than model judges.
Do not interpret selective infrastructure recovery as successful original primary
inference or mistake developmental calibration for held-out confirmation.

## Verification on the public-release tree

- Latest-main revision rechecked: `dec1a40f8de6fcef1dca950e965df37544d3c3a6`.
- Core/branch/collection/seat tests plus current kernel scoring and duplicate-binding checks: **1,610 passed, 8 bridge-gated skips**.
- Public release/V5.1 unit-contract, replay factory, no-restart, paid-call rejection and QC-version checks: **20 passed**.
- Full public cohort qualification: **816/816**, seven leaves and four collaboration metrics full, no operational exclusions, independent kernel replay/audit for every receipt.
- Built and installed wheel executed outside the checkout: V5.1 payments **12/12**, with packaged V2.5 QC records and no campaign archives.
- Compile checks passed with temporary bytecode output; source checkout unchanged by compilation. No paid model calls.
- Repository-wide local collection additionally encounters the existing checkout-name assumption tracked in [#268](https://github.com/aeread-org/AERead/issues/268); it is not a V2.5 change and no full-suite green claim is made from that invocation.

The broader local run excluding that module was interrupted after 4,086 passes,
267 skips and one expected failure; two Everos HTTP-stub setup errors were caused
by the sandbox denying loopback socket binding, not a Refund assertion. This is
reported as partial repository verification, not a completed full suite.
All 29 Everos tests subsequently passed with explicit local-socket permission.

## Implementation map

- `v2_4_cases/reference/scoring`: preserved interaction baseline and alias taxonomy.
- `v2_5_policy/branches`: complete policy contracts, case builders, branch resolver.
- `v2_5_runner/measurement`: four-seat protocol, guards, diagnostics and kernel bridge.
- `v2_5_collection_budget`: separately pinned finite collection-budget correction.
- `v2_5_seat_cases/seat_design_v3/seat_extension_v4/seat_extension_v5`: public seat cohorts.
- `v2_5_payment_units_v51`: wire-unit clarification.
- `v2_5_release`: portable qualification CLI and independent replay factory.

Historical campaign continuation, budget recovery, private artifact-loading tests,
credentials, run outputs and PDFs are outside this implementation PR.
