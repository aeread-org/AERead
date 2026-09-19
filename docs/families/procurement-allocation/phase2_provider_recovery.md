# Phase 2 provider recovery: proposed operational attempt

Campaign: `procurement_phase2_provider_recovery_v1`. This is an unexecuted
full-panel attempt following the [stopped recovery](phase2_recovery_results.md).
No source or evidence from that attempt is overwritten. It remains auditable at
`7ca7cbf38989d49930d99ac893b80bd18dcf375f` in the preserved action-format worktree.

The prior run completed eight pilot rows before two HTTP 429 responses stopped
dispatch. The wrapper discarded the original exception message. A successful
read-only key-metadata request did not establish the cause, settle the charges,
or prove that the pinned provider had recovered.

## Scoped change

The new contract retains both prior campaigns by publication and status-file
digest. It counts each attempt's own settled spend once and preserves its
unresolved reservations. The per-request budget starts at their combined
accounted total. Status and publication distinguish current and prior costs.

The budget wrapper saves the original provider exception message and typed
fields in ignored local billing evidence before applying the existing retry
rule. It forwards the original message to the private runner receipt and emits
only a verified message digest and allowlisted metadata in public evidence.
This preserves what the adapter supplies; it does not promise an original HTTP
body when the adapter does not expose one.

The exporter also counts confirmation rows actually attempted, excluding
explicitly unattempted cells from its executed count. No existing published
confirmation count changes: both previous attempts executed zero such rows.

## Unchanged measurement and stop rules

The new attempt starts from both canaries and the entire 16-row pilot. It does
not replace a failed row, append missing rows to the old pilot, or pool previous
outcomes. The 48-row confirmation can begin only after the declared pilot gates
pass and its plan digest is sealed.

Prompts, model/provider route, action schema/parser, eight worlds, seeds, sample
noise, economics, evidence gates, action and trajectory limits, analysis and
retry policy are unchanged. The route is the existing pinned
`z-ai/glm-5.3-flash` on Parasail via OpenRouter. No new scheduling policy or
inferred rate limit is introduced. Only an explicit retryable HTTP 429 permits
one retry of the identical request, with a 60-second floor and 180-second
maximum accepted Retry-After. A second 429 or another provider failure stops
dispatch. Failed unknown-charge requests remain reserved.

This attempt might encounter the same provider failure. Its next discriminating
evidence would be the retained provider message, not an assumed recovery based
on elapsed time. There are no extra inference probes or helper-model calls.

## Combined budget

| Component | USD |
|---|---:|
| Original pilot settled | 0.0099593505 |
| Action-format recovery settled | 0.0160592850 |
| Prior unknown-charge reservations | 0.0051345000 |
| New campaign starting accounted total | 0.0311531355 |
| Combined hard ceiling | 0.4500000000 |
| Remaining allocation, including all future reservations | 0.4188468645 |

There is no new $0.45 allocation. Per-request reservation and confirmation
projection checks continue to enforce the combined ceiling.

## Review and validation

The [offline review package](../../../evidence/procurement_allocation/procurement_phase2_provider_recovery_v1/qc/README.md)
binds the exact contribution and execution contract to observed tests and source
hashes. It includes the full 64-episode fixture execution and repeated publication
audit, preserved-message/privacy regressions, cumulative budget assertions and
deliberate counterexamples. These are software checks, not model observations.

Before live dispatch, `phase2_admission.load_contribution` requires a real human
approval matching the new contribution digest. Prior approvals remain attached
to their original contributions. No approval is copied or synthesized.

Inspect in order:

1. `phase2_campaign.prior_campaign_accounting` and the execution contract: verify
   both prior attempt identities, no double counting and positive carried reserves.
2. `phase2_budget.Phase2BudgetedProvider.complete` and
   `tests/test_procurement_phase2_provider_recovery.py`: verify the original
   message survives two rejected attempts, dispatch stops, and publication omits it.
3. The review package's test logs and verifier: verify the complete fixture panel,
   prior evidence/source digests and unchanged experimental controls. Provider
   availability and live success remain unverified.
