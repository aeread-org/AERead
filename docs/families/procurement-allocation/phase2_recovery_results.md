# Phase 2 recovery: incomplete pilot, no confirmation

The approved action-format recovery stopped at its operational gate after two
HTTP 429 responses, separated by the declared 60-second retry. Of 16 planned
pilot episodes, eight completed and replayed, one has an independently audited
score-free failure receipt, and seven are explicitly unattempted. All 48
confirmation episodes remain undispatched; there is no confirmation plan
digest and no treatment-effect estimate.

The exact execution contract is
`5f7978315aabebc74dba9c6397200a8c65fcfd56c93c7abc0c970880b08fbcec`.
The user's `yes` approved contribution
`2aad8f21431d39fc18b5c6fd18418d43244e3399192714eefcb2dd08f6f821aa`
before dispatch. The original failed pilot remains separate.

## Observed behavior, limited to completed pilot episodes

| World | Category | Control | Treatment |
|---|---|---|---|
| 01 | Split | One-supplier award exceeds capacity; regret $63.45 | Feasible two-supplier award; regret $0.10 |
| 02 | Split | One-supplier award exceeds capacity; regret $64.45 | Feasible two-supplier award; regret $0.10 |
| 03 | Quality | Feasible award; regret $0.00 | Feasible award; regret $0.10 |
| 04 | Quality | Feasible award; regret $0.65 | Feasible award; regret $0.65 |

All eight completed episodes have zero malformed actions. Four of four
treatment awards and two of four control awards satisfy the economic
constraints. Those are descriptive counts over an incomplete, single-seed
pilot, not a confirmatory comparison or a general model ranking.

Both arms used one sample in world 03 (22 good units out of 24 inspected).
Both arms continued to a second supplier after the first world 04 sample
returned 12/24 good units; the alternative returned 24/24. These actions are
consistent with evidence-dependent continuation in these examples. They do
not establish optimal stopping or an advantage for treatment on that behavior.

The recovery never reached its deadline or trap outcomes. The original
campaign's four trap deferrals are preserved as original-campaign evidence,
not imported into the recovery's failed gate.

## Cost and failure attribution

| Item | USD |
|---|---:|
| Original Phase 2 settled spend | 0.0099593505 |
| Recovery settled spend, including two unscored canaries | 0.0160592850 |
| Reserved for the recovery's two unknown 429 charges | 0.0051345000 |
| Combined accounted total | 0.0311531355 |
| Remaining under the original $0.45 ceiling | 0.4188468645 |

The recovery contains 37 provider requests: 35 settled and two unknown-charge
rejections. The two rejected calls have the same request digest and the
recorded retry interval is exactly 60 seconds. Their raw row cost remains
null. The runner's zero-cost failure telemetry is not evidence of zero provider
billing, so the full reservations remain charged against the campaign ceiling.

The wrapper preserved HTTP status, request identity and retry timing but
replaced the original exception detail. The provider-specific reason and
actual charges cannot be recovered from those logs. A subsequent read-only
key-metadata request succeeded; it neither explains the past 429s nor settles
them. Account-level fields remain private. No further inference
requests were used for diagnosis.

## Verification and inspection

1. [Execution status](../../../evidence/procurement_allocation/procurement_allocation_phase2_action_format_recovery_v1/reports/execution_status.json): verify 8 completed, 1 operational failure, 7 unattempted and 0 confirmation rows; costs include the original attempt and unresolved reservations.
2. [Provider failure events](../../../evidence/procurement_allocation/procurement_allocation_phase2_action_format_recovery_v1/qc/provider_failure_events.json): verify two HTTP 429 events and their 60-second retry; original error-body detail is unavailable.
3. [Pilot rows](../../../evidence/procurement_allocation/procurement_allocation_phase2_action_format_recovery_v1/reports/pilot.json) and [canonical actions](../../../evidence/procurement_allocation/procurement_allocation_phase2_action_format_recovery_v1/qc/canonical_actions.json): inspect the over-capacity control awards, treatment splits and quality-sample continuation. No internal-reasoning claim is made.

`tools/publish_procurement_phase2_recovery.py` independently re-audits the
receipts, event payload digests, per-row billing, gates and total ledger before
export. A second export reproduced identical bytes. Full prompts, observations,
provider reasoning and account metadata remain in ignored local storage.

The clean Python 3.12 dev installation passed 42 focused tests and the full
provider-free suite (3,797 passed, 266 skipped, 2 expected failures). The
previous local environment passed 3,798 with 265 skips and 2 expected failures;
the differing skip coverage is retained, not called upstream certification.

Next execution requires resolving the provider stop within a reviewed
operational contract. The failed attempt stays sealed; no missing episode may
be silently replaced, and the remaining budget is not a fresh spending ceiling.
