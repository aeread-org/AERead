# Proposed recovery confirmation: decision pending

This is a proposal, not an executed or frozen second campaign. The original
`procurement_allocation_unified_regret_v1` remains ineligible and immutable.
It cannot be completed by replacing its failed row or pooling its partial panel
with new results.

If approved, the recovery would use a new identity,
`procurement_allocation_unified_regret_recovery_v2`, with these declared terms:

| Dimension | Proposed contract |
|---|---|
| Panel | Same six admitted markets; all 36 confirmation cells run with fresh environment/inference seeds 49001, 49002, 49003, paired across arms |
| Metric and policies | Same guarded regret rule, prompts, sample-noise mechanism, economic bounds, and 50,000-resample paired world-bootstrap analysis |
| Route | Same pinned GLM/Parasail route and revision; no provider/model substitution |
| Planning evidence | Reuse the completed 24-row pilot as explicitly linked calibration evidence; do not count those rows in confirmation |
| Admission | Provider-free tests and source binding, two new unscored prompt canaries, and a frozen recovery plan before confirmation |
| Infrastructure handling | At most one retry of a logical action after an explicit HTTP 429, with a delay of at least 60 seconds and respect for a bounded Retry-After; preserve both request records. No retry for ambiguous transport outcomes or measured task failures |
| Billing | Carry forward $0.1320779295 settled charges plus the original unresolved $0.0023634 reservation; new calls and retry reservations must fit the remaining $0.2155586705 of the combined $0.35 ceiling |
| Stop rule | A second 429, another operational failure, unknown transport outcome, route drift, or insufficient remaining budget stops dispatch and remains typed missingness |
| Inference | Publish the recovery panel separately, with the original failed attempt linked. No pooling, selective replacement, prompt tuning, or outcome-based world selection |

Estimated new spend from the observed pilot is approximately $0.124 for 36
trajectories, plus two canaries and any reserved retry cost. This is a planning
estimate, not a bill or completion guarantee. Conservative reservations remain
charged against the cap until a provider billing audit settles them.

Implementation and provider-free tests for this changed retry contract would
precede any new paid call. This requires a decision because the supplied plan
specified exactly one frozen confirmation; the existing run cannot silently
acquire a retry policy after observing the failure.
