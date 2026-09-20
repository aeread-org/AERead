# Phase 2 timeout recovery: proposed operational contract

Campaign `procurement_phase2_timeout_recovery_v1` is a new, unexecuted attempt.
The [previous attempt](phase2_provider_recovery_results.md) passed the pilot but
stopped after 19 completed confirmation rows when a request exceeded 180 seconds.
Its source, approval, plan, receipts and outcome remain preserved at `88023a75`.
The new attempt makes no claim that the previous panel completed or supported
its hypothesis. The previous treatment allocation violation remains a finding.

## What changes

A family-local provider deadline of 175 seconds expires before the explicitly
configured 180-second harness deadline. This lets the provider wrapper produce
a typed `timeout` while the scheduler still owns the action. The scheduler may
retry that identical stateless completion once, using the existing 60-second
minimum delay. The original explicit-429 retry rule remains available; at most
two attempts total are allowed for any logical action, including mixed failures.
A second timeout/429, a changed request, an excessive Retry-After, cancellation
or any other error stops dispatch. SDK retries remain disabled.

Every request reserves its maximum charge before dispatch. A timeout's charge
stays unknown and fully reserved even if the retry succeeds. The completed row
then has null total cost, a known settled component and an unresolved reserved
component. This is a software accounting distinction, not a billing refund.
External cancellation is never converted into timeout retry permission.

The legacy procurement builder retains its old retry allowlist. The separate
Phase 2 profile declares the new condition and its own reservation wrapper
handles unknown costs. No shared-runner or legacy implementation changes.
The 175-second timer cannot guarantee upstream availability; a second slow
request or another operational failure will still stop the attempt.

## What stays fixed

Both canaries and the entire 16-row pilot run afresh. Only a passing pilot allows
a newly frozen 48-row confirmation. There is no selective cell replacement or
pooling of any earlier model outcomes. Prompts, action schema/parser, worlds,
model/provider route, seeds, sample noise, economics, verifier, ten-action budget,
20-call ceiling, output limit, per-episode cost limit and statistical analysis
stay fixed. The route remains GLM 5.3 Flash on Parasail through OpenRouter.

The primary comparison still requires the complete paired eight-world panel,
replay, finite consistent regrets, zero treatment constraint violations and an
upper confidence bound below zero. Software recovery does not relax that guard.
Trap certificates remain a test of public infeasibility recognition, not hidden
market discovery. One pilot seed does not identify within-world model variance.

## Combined budget

The execution contract binds all three previous publications and their status
files by digest, counting each attempt's own spend once.

| Component | USD |
|---|---:|
| Prior known settled spend | 0.0949151610 |
| Prior unknown-charge reservations | 0.0080104500 |
| Starting accounted total | 0.1029256110 |
| Original combined hard ceiling | 0.4500000000 |
| Remaining allocation, including future reservations | 0.3470743890 |

This is not a fresh allocation. Projection and per-request checks enforce the
remaining combined budget. The previous pilot projected $0.08618 for its 48-row
confirmation; that is a reference estimate, not a price guarantee for this
attempt or permission to exceed the ceiling.

## Review and readiness

The [exact review package](../../../evidence/procurement_allocation/procurement_phase2_timeout_recovery_v1/qc/README.md)
binds the contribution and execution contract to provider-free tests, source
pins, all eight cases and offline references. The tests include the real
scheduler's timeout recovery, retained reservations, two-failure stop, external
cancellation, changed-request rejection and the complete 64-episode fixture
campaign with repeated publication audits. Fixtures are not model observations.
Three deliberate mutations must each fail their intended test before sealing.

Inspect in this order:

1. `phase2_budget.py` and `phase2_controls.py`: the inner deadline, cancellation
   distinction and unknown-charge reservation; upstream latency remains unknown.
2. `phase2_runner.py` and `tests/test_procurement_phase2_timeout_recovery.py`: the
   actual scheduler retries once, replays the resulting receipt, and preserves
   unknown cost. No hidden retry owner or weakened economic gate is introduced.
3. `phase2_campaign.prior_campaign_accounting` and the execution contract: all
   three stopped attempts contribute costs once, with unchanged economic controls.
4. The review verifier and full test logs: exact bytes and observed coverage;
   they cannot establish future live reliability or economic performance.

Live dispatch requires a real approval of the sealed contribution under
`phase2_admission.load_contribution`, implementing the repository's benchmark QC
requirement that human approval bind the exact contribution contract. Earlier
approvals remain attached to their earlier retry policies and source pins.
