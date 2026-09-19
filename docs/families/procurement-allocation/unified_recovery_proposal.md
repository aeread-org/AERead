# Approved recovery confirmation

Execution is complete; see the [verified results](unified_recovery_results.md).

The user approved this recovery on 2026-09-19. Implementation and provider-free
validation precede its freeze and paid execution. The original
`procurement_allocation_unified_regret_v1` remains ineligible and immutable.
It cannot be completed by replacing its failed row or pooling its partial panel
with new results.

The approved recovery uses a new identity,
`procurement_allocation_unified_regret_recovery_v2`, with these declared terms:

| Dimension | Approved contract |
|---|---|
| Panel | Same six admitted markets; all 36 confirmation cells run with fresh environment/inference seeds 49001, 49002, 49003, paired across arms |
| Metric and policies | Same guarded regret rule, prompts, sample-noise mechanism, economic bounds, and 50,000-resample paired world-bootstrap analysis |
| Route | Same pinned GLM/Parasail route and revision; no provider/model substitution |
| Planning evidence | Reuse the completed 24-row pilot as explicitly linked calibration evidence; do not count those rows in confirmation |
| Admission | Provider-free tests and source binding, two new unscored prompt canaries, and a frozen recovery plan before confirmation |
| Infrastructure handling | At most one retry of a logical action after an explicit HTTP 429, with a delay of at least 60 seconds and respect for Retry-After up to 180 seconds; a larger value stops dispatch; preserve both request records. No retry for ambiguous transport outcomes or measured task failures |
| Billing | Carry forward $0.1320779295 settled charges plus the original unresolved $0.0023634 reservation; new calls and retry reservations must fit the remaining $0.2155586705 of the combined $0.35 ceiling |
| Stop rule | A second 429, another operational failure, unknown transport outcome, route drift, or insufficient remaining budget stops dispatch and remains typed missingness |
| Inference | Publish the recovery panel separately, with the original failed attempt linked. No pooling, selective replacement, prompt tuning, or outcome-based world selection |

Estimated new spend from the observed pilot is approximately $0.124 for 36
trajectories, plus two canaries and any reserved retry cost. This is a planning
estimate, not a bill or completion guarantee. Conservative reservations remain
charged against the cap until a provider billing audit settles them.

Implementation and provider-free tests for this changed retry contract precede
any new paid call. The original exactly-once campaign remains closed; approval
applies to this separate identity and does not retroactively change its retry policy.

The user subsequently requested Gemini Flash to accelerate coding/review. Two
Gemini 3.8 Flash review requests cost $0.0138647025 combined; they are excluded
from benchmark observations and included in the same $0.35 cap. The first
response was truncated. The focused follow-up flagged retained 429 reservations,
which were reviewed and kept because the contract explicitly preserves unknown
billing. This leaves $0.201693968 for recovery requests, including canaries and
any new unresolved reservations. No benchmark model substitution was made.
