# Phase 2 completed: lower regret, validity guard failed

The approved timeout-recovery V2 completed **16/16 pilot and 48/48 confirmation
episodes**, all independently replayed. Treatment reduced mean confirmation
regret from **$16.8771 to $2.9104**: treatment minus control **-$13.9667**, with
the frozen 95% paired-world bootstrap interval **[-$31.8271, -$0.6854]**.
The predeclared conclusion is nevertheless **`support=false`**. One treatment
episode queried an unknown supplier, failing the zero-constraint-violation guard.
The interval alone does not satisfy the experiment's decision rule.

This completes the planned execution and audit, not a general demonstration of
economic epistemics. The strongest descriptive improvement is order splitting.
Both arms already respond to the quality evidence and recognize the public trap
certificates. The next design question is whether these behaviors survive less
predictable markets and traps requiring information acquisition; that would
require a separate preregistered campaign, not changes to these results.

## Identity and coverage

| Item | Value |
|---|---|
| Campaign | `procurement_phase2_timeout_recovery_v2` |
| Approval | User's `continue`, bound to the exact V2 review after all seven source-head CI checks passed |
| Contribution | `1ae5c78733b420bcd6ad8e50cd5dc9ab2fc0365c40b087d0215256a69a00c511` |
| Execution contract | `8424c1e9d3ac49290eaa82e149c60a045c7eb0ea6778b68274d95f1ff57e6ad7` |
| Frozen confirmation plan | `768755bfa3863a0c46e3c565ed4dc2e9cdb1f77ca691e84acc02ad7d98aa33c3` |
| Executed source | `036df425a91418ef4cad692dda5a7c24561c38ff` |
| Configured model / provider | `z-ai/glm-5.3-flash`, Parasail through OpenRouter; configured alias, not an immutable model revision |
| Pilot | 16 completed and replayed; 3 invalid economic awards; 0 malformed actions |
| Confirmation | 48 completed and replayed; 7 violation rows; 0 malformed actions |
| Operational failures / unattempted rows | 0 / 0 in this attempt |
| Provider requests | 226 settled, including 2 unscored canaries; no timeout or 429 retry needed |

Both pilot gates passed before the confirmation plan was sealed. Pilot outcomes
and all previous attempts are excluded from the confirmation estimate. The
unexecuted timeout V1 remains superseded offline evidence, not a paid attempt.
The new timeout retry is validated by fixtures; this live attempt did not exercise
it and cannot establish its reliability under another upstream timeout.

## Confirmation findings

| Target behavior | Treatment | Control | Interpretation |
|---|---:|---:|---|
| First quote matches public reference, nontrap rows | 17/18 | 14/18 | Agreement with a public heuristic, not proof of optimal search order. |
| Quality world 03: one sample, then award | 3/3 | 3/3 | All six episodes have zero regret; first observed yields are 91.7%, 95.8%, 100%. |
| Quality world 04: sample a second supplier | 3/3 | 3/3 | First yields are 75.0%, 62.5%, 79.2%; second yields are 95.8%, 100%, 95.8%. Both arms adapt. |
| Missing/expired quote, wrong variant or unverified-sample violations | 0/24 | 0/24 | Evidence eligibility holds, while other constraints still fail. |
| Valid two-supplier awards in split worlds | 5/6 | 0/6 | Treatment's remaining row uses an unknown supplier ID. Control has five over-capacity awards and one unknown-supplier action. |
| Valid deadline-world awards | 6/6 | 6/6 | Both meet delivery constraints; treatment has lower regret in world 06. |
| Certificate-supported trap deferrals | 6/6 | 6/6 | Treatment has six zero-regret deferrals; control has five, plus one $0.10 quote before deferring. |

There are **zero invalid treatment awards**, but **one invalid treatment action**;
reporting only the award count would hide the failed validity guard. World 02,
seed 53001, samples `vendor_5913e9d07b`, then requests a quote from
`vendor_5913e9d07f`. The verifier terminates with `unknown_supplier`, retains
$1.40 of research expense, and assigns $65.10 regret against the $63.70 bound.
Control makes the same supplier-ID error in that cell, before the second sample,
with $0.75 research expense and $64.45 regret. Both are scored model failures,
not missing provider responses, and neither was retried or replaced.

A valid contrast is treatment world 01, seed 53002: two formal quotes and two
verified samples precede an award of 12 units from each of two suppliers. The
allocation respects both capacities, completes the 20-kit target and has zero
regret. Control's same-seed award exceeds a supplier's capacity and has $63.45
regret. Inspect the canonical actions alongside the row's feasibility result;
the raw completed-kit field alone is not evidence of a valid award.

| Slice | Mean treatment-minus-control regret, USD |
|---|---:|
| Split worlds | -52.9917 |
| Quality worlds | +0.0500 |
| Deadline worlds | -2.9083 |
| Deadline trap | 0.0000 |
| Budget trap | -0.0333 |
| All six nontrap worlds | -18.6167 |

The primary estimate averages three paired seeds within each world, then weights
the eight worlds equally; 50,000 bootstrap draws use seed 20260919. Slice values
are descriptive diagnostics without separate significance claims. Treatment
spends $22.65 on simulated research across its 24 confirmation episodes versus
$16.85 for control; this expense is already included in regret and is separate
from API charges. More search is not automatically better.

The eight worlds are fixed and curated, not a population sample. The paired
seeds control sample noise, but a configured inference seed does not guarantee
identical provider generation. The stopping traces do not reveal internal
reasoning or identify a Bayesian-optimal rule. Trap certificates establish public
infeasibility without inspecting all eight suppliers. The original power claim
was corrected in the [design contract](phase2_plan.md#statistical-limits-and-phase-1-corrections);
three seeds do not create 48 independent experimental units. Five continuous
classifier rejections remain reported alongside the separate six-world headroom
and two-trap admission tests; they were not relabeled as passes.

## Cost reconciliation

| Paid attempt | Settled USD | Unknown-charge reservation USD |
|---|---:|---:|
| Original Phase 2 pilot | 0.0099593505 | 0.0000000000 |
| Action-format recovery | 0.0160592850 | 0.0051345000 |
| Provider recovery, incomplete confirmation | 0.0688965255 | 0.0028759500 |
| Timeout-recovery V2, complete panel | 0.1049674725 | 0.0000000000 |
| **Combined** | **0.1998826335** | **0.0080104500** |

Combined accounted cost is **$0.2078930835**, leaving **$0.2421069165** under the
original $0.45 ceiling. V2 comprises $0.0007916040 for two canaries,
$0.0261197145 for the 56-request pilot and $0.0780561540 for the 168-request
confirmation. Across all four paid attempts there were 437 requests: 434 settled
and three with unknown charges. Prior reservations remain allocated; successful
recovery does not resolve those bills. No further model calls followed completion.

## Verification and inspection

The exporter independently audited all 64 scored receipts, replay, sealed events,
approval/source bindings, billing and aggregate gates, then recomputed the frozen
comparison. Repeating the export produced identical bytes. All 11 publication
artifacts, 92 source/test pins, manifest completeness and credential/prohibited-field
checks pass. The live publication manifest is
`0eff6f465437137e3bbcd42cfd0f485eb57653e52cac4614457840899be2f04f`.
Raw prompts, observations, provider reasoning and account metadata remain ignored.

The executed source passed all seven CI checks before launch. Offline validation
includes 55 focused tests on each of Python 3.10 and 3.12, a fresh full Python 3.12
suite with 3,894 passes, 266 skips and two expected failures, the 64-episode fixture,
and three deliberate mutation failures. Skips are not certification.
Post-publication checks pass all 15 exporter, failure-register and source-layout
tests; the generated register reproduces exactly. Global
`aeread errata` is unavailable at this revision; verification is scoped to the
published bundles and generated family register.

Inspect in this order:

1. [Comparison](../../../evidence/procurement_allocation/procurement_allocation_phase2_timeout_recovery_v2/reports/comparison.json): check `fully_replayed=true`, the eight world means, `treatment_validity_guard=false` and `support=false`. The reduction is observed on this panel; generalization remains unverified.
2. [Confirmation rows](../../../evidence/procurement_allocation/procurement_allocation_phase2_timeout_recovery_v2/reports/confirmatory.json) and [canonical actions](../../../evidence/procurement_allocation/procurement_allocation_phase2_timeout_recovery_v2/qc/canonical_actions.json): compare `world_02_53001_treatment` with `world_01_53002_treatment`. The former's fourth action references the wrong supplier; the latter's fifth action is a valid 12+12 split. Both replay exactly; internal causes remain unobserved.
3. [Execution status](../../../evidence/procurement_allocation/procurement_allocation_phase2_timeout_recovery_v2/reports/execution_status.json), [plan](../../../evidence/procurement_allocation/procurement_allocation_phase2_timeout_recovery_v2/tables/confirmatory_plan.json) and [approval](../../../evidence/procurement_allocation/procurement_allocation_phase2_timeout_recovery_v2/qc/human_qc_approval.json): verify separate 16/48 coverage, exact review identity and cumulative settled/reserved accounting. Prior unknown charges remain unresolved.
4. [Failure-register snapshot](../../../evidence/procurement_allocation/procurement_allocation_failure_register/qc/2026-09-20-phase2-timeout-recovery-v2/reports/failure_register.json): regeneration gives 881 planned records, 826 executed, 55 unattempted, four operational failures and 319 measured violation rows across preserved procurement campaigns. These are historical totals, not V2 rates.

Presentation handoff: the objective was five observable buyer behaviors under
scarce actions. The method is a paired, frozen synthetic panel with strict evidence
gates and separate operational/economic outcomes. All 48 confirmation observations
replay; mean regret falls $13.97, mainly through valid splitting, but one treatment
supplier-ID error prevents the declared success claim. Show the valid 12+12 split
beside the unknown-supplier trace, then explain that public certificates and eight
curated worlds limit what this experiment establishes.
