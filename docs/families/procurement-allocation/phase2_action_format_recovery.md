# Phase 2 action-format recovery

This is a separate, not-yet-executed campaign:
`procurement_phase2_action_format_recovery_v1`. The original pilot remains
failed and is not pooled, replaced or selectively retried.

The first pilot completed and replayed 16 receipts but contained 11 invalid
actions: nine null messages, one null proposal, and one null inquiry fields
array. Its nullable superset provider schema admitted those objects while
the selected action parser correctly rejected them. The common prompt did
not enumerate the required fields. Two successful one-action canaries did
not establish complete action-format reliability.

The repair gives both arms the same explicit action-format contract in
their common prompt and matching schema descriptions. It lists all six
actions and their required values. It does not fill in missing fields,
weaken validation, remove failures, or add economic strategy to the control.
Schema validation still permits action-dependent nulls, so parser checks
remain necessary. Live compliance with the clearer instructions is untested.

The eight worlds, environment, scorer, evidence eligibility, sample noise,
reference policies, model route, 10-action limit, seeds and statistical rules
are unchanged. The pilot again contains all 16 declared cells, followed by
48 confirmation cells only if the original operational and behavior gates
pass. Both prompts and the implementation are frozen before the new pilot.
No outcome-based retuning is permitted within this recovery identity.

The new ledger begins with the original attempt's $0.0099593505 settled cost,
bound to its published digest. The combined ceiling remains $0.45, leaving
$0.4400406495. It is not a new $0.45 allocation. Confirmation retains its
cost-projection gate and each request requires a pre-dispatch reservation.

Validation includes all eleven captured failures: each still fails the
unchanged parser, and changing only its identified missing field produces
a parseable diagnostic example. These are offline parser counterfactuals,
not revised buyer decisions or model outcomes. A byte check protects the
unchanged economic and verifier implementations. The full 64-row fixture
campaign verifies orchestration without provider calls.

Before live execution, the recovery requires an actual human approval
matching its newly sealed contribution digest. The original approval binds
the original contribution only. No recovery approval is synthesized.

Original live evidence:
`evidence/procurement_allocation/procurement_allocation_phase2_pilot_v1/`.
Original source and independent raw audit remain available on
`codex/procurement-phase2` at `cb27b3b8`; run its existing verifier there.
The old offline review bundle is historical and its source-pin check is
expected to reject the repaired source tree.
