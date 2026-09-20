# Phase 2: pilot passed, confirmation stopped on timeout

The approved provider recovery completed all 16 pilot episodes with zero malformed
actions. All four pilot trap episodes explicitly deferred with zero regret. Both
operational gates passed, and the 48-row confirmation plan was frozen before
dispatch. Confirmation then completed 19 episodes, recorded one score-free timeout,
and left 28 episodes explicitly unattempted. There is **no confirmatory effect
estimate or confidence interval**; the planned eight-world comparison is incomplete.

The pilot and confirmation remain separate. No prior attempt is pooled, no failed
cell is replaced, and no remaining cell was dispatched after the stop.

## Identity and coverage

| Item | Value |
|---|---|
| Campaign | `procurement_phase2_provider_recovery_v1` |
| Contribution approved by the user's `approve` | `9ba4adfd8cdcf9e9a3996830e225136d138179f7618668f76b33ed23263d9191` |
| Execution contract | `9287428d63f30345dd131acccbafef7c71f9cc26cc728f07802f8c295fd932ef` |
| Frozen confirmation plan | `26511f82c1c489b5ef13440fa30b8205623afc231a998fe2b50daf441c66ef2a` |
| Executed source | `f4e8b8f1bba629f0a7b1ad884ec06799eea6ff7e` |
| Configured model / provider | `z-ai/glm-5.3-flash`, Parasail through OpenRouter |
| Pilot coverage | 16/16 completed and independently replayed |
| Confirmation coverage | 19/48 completed and independently replayed; 1 timeout; 28 unattempted |
| Malformed actions among completed episodes | 0/35 |
| Scored receipts / separate failure receipts audited | 35 / 1 |

`comparison.complete_panel=true` means all 48 planned **records** are present,
including typed missingness. It does not mean 48 successful executions.
`fully_replayed=false`, null effect/interval, and `support=false` correctly block
a confirmatory claim. The equal-weight unit is the economic world after averaging
its three paired seeds, not an individual episode.

## Observed economic behavior

These are descriptive counts in this attempt, not estimates over missing rows.

| Target behavior | Observed evidence | Limit |
|---|---|---|
| Search prioritization | In completed confirmation episodes with quotes, the first supplier matched the public reference in 9/9 control and 9/10 treatment rows. | Agreement with one public heuristic does not prove optimal search order; the panel is incomplete. |
| Sample continuation | All six completed world 03 confirmation episodes used one sample. The one completed world 04 confirmation episode, treatment, used two. In the pilot, both arms used one sample in world 03 and two in world 04. | Consistent with different responses to quality evidence; no identified optimal stopping rule or treatment advantage. |
| Evidence discipline | No missing-quote, exact-variant or unverified-sample violation was recorded among the 35 completed episodes. | Economic allocation violations still occurred. Replay verifies the implemented rules, not real supplier validity. |
| Splitting | All 12 split-world confirmation episodes completed. Treatment made 5/6 valid split awards; control made 1/6. | Treatment world 01, seed 53001 duplicated a supplier and failed minimum service: 11 completed kits, regret $63.55. The predeclared zero-treatment-violation guard therefore fails. |
| Walk-away | All four pilot trap episodes deferred with zero regret and a public impossibility certificate. | Confirmation never reached the traps. Certificates test recognition of public infeasibility, not discovery of eight hidden bad suppliers. |

The pilot had three economically invalid awards: two control capacity violations
and one treatment minimum-service violation. The completed confirmation episodes
had six invalid awards: five control capacity violations and one treatment award
with both duplicate-supplier and minimum-service violations. These are measured
economic outcomes, separate from the operational timeout and schema failures.

## Timeout and accounting

World 04 control, seed 53001, completed four provider requests. Its fifth request
exceeded the inherited **180-second harness timeout**. The sealed event records
`provider_call_outcome_unknown`, `failure_condition=timeout`, and no HTTP status.
The budget wrapper retained the underlying cancellation privately. There is no
evidence here of another 429 or of why the upstream completion did not arrive.
The declared policy permitted retries only for explicit 429s, so dispatch stopped.

| Item | USD |
|---|---:|
| Both prior attempts, settled | 0.0260186355 |
| This attempt, settled (146 requests, including two canaries) | 0.0688965255 |
| Combined settled | 0.0949151610 |
| Prior two unresolved 429 reservations | 0.0051345000 |
| New unresolved timeout reservation | 0.0028759500 |
| Combined unresolved reservations | 0.0080104500 |
| Combined accounted total | 0.1029256110 |
| Remaining under original $0.45 ceiling | 0.3470743890 |

This attempt made 147 provider requests; across all three attempts there were
211 requests, 208 settled and three with unknown charges. Reservations are ceiling
allocations, not confirmed charges. The failed episode's total cost remains null;
its known $0.001666962 and reserved $0.002875950 are retained separately. No paid
diagnostic probe or selective retry followed the stop.

## Verification and inspection

1. [Eligibility and results](../../../evidence/procurement_allocation/procurement_allocation_phase2_provider_recovery_v1/reports/confirmatory.json): inspect `world_01_53001_treatment` and `world_02_53002_control` against [canonical actions](../../../evidence/procurement_allocation/procurement_allocation_phase2_provider_recovery_v1/qc/canonical_actions.json). The former is an invalid duplicate allocation; the latter is a valid control split with $0.10 regret. Both replay exactly. General construct validity remains unestablished.
2. [Timeout evidence](../../../evidence/procurement_allocation/procurement_allocation_phase2_provider_recovery_v1/qc/provider_failure_events.json): verify the score-free timeout, null HTTP status and event digest. Upstream cause and actual charge remain unknown.
3. [Execution status](../../../evidence/procurement_allocation/procurement_allocation_phase2_provider_recovery_v1/reports/execution_status.json) and [comparison](../../../evidence/procurement_allocation/procurement_allocation_phase2_provider_recovery_v1/reports/comparison.json): verify 19 completed, one failed, 28 unattempted confirmation records, cumulative costs and null inference. The full panel remains unexecuted.
4. [Pilot rows](../../../evidence/procurement_allocation/procurement_allocation_phase2_provider_recovery_v1/reports/pilot.json): inspect both quality trajectories and all four certificate-supported deferrals. One pilot seed cannot estimate within-world variance.

The exporter independently audited receipts, replay, sealed events, source and
approval bindings, row billing, gates and aggregate accounting. A second export
reproduced identical bytes. A reporting repair includes timeout/outcome-unknown
events in the public allowlist; it changes neither executed code nor scores. The
initial uncommitted export is preserved privately for incident comparison.
Fifteen targeted publication, execution and provider-recovery tests passed.
The executed source had all seven CI checks green; its full clean suite passed
3,811 tests with 266 skips and two expected failures. Skips are not certification.
Global `aeread errata` is unavailable at this revision; verification is scoped.

Presentation handoff: the objective was to test five buyer behaviors under scarce
actions. The method paired two prompts on eight fixed synthetic worlds with strict
evidence gates and a frozen comparison. The pilot passed, but confirmation has
19/48 measured outcomes and an independently failed treatment-validity guard.
The duplicate allocation versus valid control split is a concrete input-to-score
inspection. A new operational contract is needed before another complete attempt;
the incomplete attempt remains evidence and cannot be completed by replacing cells.
