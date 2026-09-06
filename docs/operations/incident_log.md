# AERead incident log (Tier 2)

The judgment half of the incident register. Tier 1 is the machine register per
family, derived from published evidence; this file holds what a machine cannot
derive. Rows are never deleted, only their disposition changes.

Categories: `design` (the experiment was specified wrongly), `operational` (a
run failed or stopped), `tooling` (the harness, driver or tests were wrong),
`judgment` (a person or agent decided wrongly).

Dispositions: `open`, `fixed`, `mitigated`, `accepted`, `superseded`.

---

## 2026-09-05 / 06 — Housing delivery and confirmatory push

Opened while taking the Housing family from a partial variance pilot toward
the confirmatory comparison it was designed for. Tier 1 rows for this period
are in `evidence/housing_failure_register/`.

### design

| id | what happened | disposition |
|---|---|---|
| D-1 | The action attempt count was never sized against measured provider reliability. Four attempts against the ~40% per-call rejection rate observed in V19 predicts ~54% cell loss over ~30 sequential actions, which is what V19 delivered. The number was an inherited default. | fixed — 10 attempts in V20, 30 in V24, both spec-driven |
| D-2 | Timeouts were classified as unknown-outcome and never retried. Correct for a side-effecting call, wrong for a stateless chat completion that is safe to re-send. V17 lost two of three cells to single timeouts. | fixed — declared retryable from V20 |
| D-3 | A `$0.01` per-seat cost cap lived only in the runner. It stopped V17 entirely after three cells, and the breach was classified as campaign-critical rather than cell-level missingness. | fixed — `controls.seat_max_cost_usd`, and seat exhaustion is now typed `cost_budget_exceeded` |
| D-4 | The length-retry policy doubles the output budget, quadrupling cost after two escalations, against a seat budget sized for the base case. The two policies were designed independently. | mitigated — budget raised and made visible; the interaction remains undesigned |
| D-5 | Route health was conflated with route identity in two places: the preflight refused any non-zero catalog status, and that status was inside the endpoint identity digest, so a transient derank made an unchanged route look drifted. A direct probe returned 10/10 while flagged degraded. | fixed — `backend.route_status_policy` and `endpoint_snapshot_policy` |
| D-6 | A confirmatory sample size was computed from two paired worlds and emitted as an integer, inviting a precision the estimate does not have. | fixed — `minimum_paired_worlds_for_recommendation` withholds it |
| D-7 | Stochastic replicates were dropped from this line, folding within-world provider noise into the between-world variance that sizes the confirmatory run. QC §5 requires them; the population cross-play design had them. | fixed — restored to 2 from V21 |
| D-8 | Missingness was reported and never gated. V19 lost a third of its cells and still sealed a completed status. The sibling commercial-state family already had the ceiling rule. | fixed — `maximum_operational_failure_fraction` |
| D-9 | The scripted anchor present in `housing_population_crossplay_v0` was dropped from the model-sensitivity line, so environment or scorer drift cannot be distinguished from a model regression across versions. | open |
| D-10 | The analysis contract declares `minimum_confirmatory_worlds: 30` while the sealed sweep provided 16 holdout seeds. No confirmatory campaign could satisfy both, and no variance however small changes it because the floor dominates the powered estimate. The two numbers live in different artifacts and had never been compared. | fixed — `housing_case_config_sweep_v2` extends the holdout to 36 seeds, 35 usable |
| D-11 | The sealed holdout contains a structurally unusable world: the severe configuration at seed `114691332` has a zero assignment upper bound, so it carries no normalized score. Found the first time the holdout was ever generated. | fixed — excluded before any outcome, exclusion re-derived from the generator at load |
| D-12 | `_critical_failure` decides whether a campaign halts by matching substrings in exception messages. Rewording an error silently changes stopping behaviour. | open |
| D-14 | A 404 meaning "no endpoint currently matches the pinned route" is typed `provider_rejected` and is not retryable, so a transient derank kills a cell outright. That is the same conflation of availability with identity as D-5, in the retry policy rather than the preflight. Whether it should be retryable is a measurement decision, not an obvious bug: retrying indefinitely against a genuinely absent route would hide a real pin failure. | open |
| D-13 | The primary estimand averages self-play into the live-opponent aggregate, which QC §5 says to keep separate. Changing it after the pilot would invalidate the variance the sample size derives from. | mitigated — cross-play and self-play published as predeclared slices |

### operational

| id | what happened | disposition |
|---|---|---|
| O-1 | V14 blocked at single-attempt admission on upstream 429s; 0/48 cells. | superseded by V15 |
| O-2 | V15 delivered 43/48 with five GLM-seat losses; no world paired. | superseded by V19 |
| O-3 | V17 stopped after three cells: two DeepSeek timeouts and one hidden seat-budget breach treated as campaign-critical. | fixed via D-3 |
| O-4 | V19 delivered 32/48 with 16 GLM-seat rate-limit losses concentrated in a two-hour burst; two paired worlds. | superseded by V23 |
| O-5 | V23 delivered 186/192 with six losses, but four scattered worlds broke, leaving four paired against a declared six, so the sample size was withheld. | superseded by V26 |
| O-6 | V25 blocked at admission: DeepSeek spent all 4096 completion tokens on reasoning and returned empty content. | fixed via T-2 and T-3 |
| O-8 | V26, mid-run: both replicates of `severe_cw030_r2 / glm_53_flash__vs__glm_53_flash` at world `123194022` failed together with HTTP 404 typed `provider_rejected`, after 12 provider calls each. OpenRouter returns 404 when no endpoint satisfies the pinned provider under `require_parameters` with fallbacks disabled, so the pinned Parasail GLM endpoint briefly stopped matching. Recorded before diagnosis: at the time it was unclear whether this was a route disappearance, a parameter drift, or a content rejection. | open |
| O-7 | Across ten campaigns, 47 of 48 trajectory failures carry a GLM seat, on Morph, DeepInfra, Friendli and Parasail alike. The only condition without a GLM seat failed once. This is a model-specific supply constraint through this gateway, not a sequence of provider incidents. | open |

### tooling

| id | what happened | disposition |
|---|---|---|
| T-1 | The publisher's success path hardcoded the `live` stage, so it had never executed for a `full_trajectory` campaign. | fixed — stage-aware |
| T-2 | The admission raw response was written to one fixed filename per probe, so a retry's differing response hit the immutability guard and raised, and that guard's own message was then classified as an invalid action. Every admission retry that reached the provider was broken. Rate-limit retries appeared to work only because a failed call writes no raw file. | fixed — one raw file per visible attempt |
| T-3 | Admission never inspected `finish_reason`, so a truncated completion was recorded as an invalid action, charging a model with a fault belonging to the output budget. Trajectory execution already handled it. | fixed — typed `length` and the budget escalated on retry |
| T-4 | Admission rows recorded a failure type but not its message, so none of T-2 or T-3 was diagnosable from the sealed evidence. | fixed — message retained |
| T-5 | The pacing ledger returned null for the new client because one `isinstance` check inside the run artifact was not widened alongside the others. | fixed |
| T-6 | A mutation sweep over the newly added guards found 8 of 14 were not actually tested; the missingness-ceiling test reimplemented the rule inside the test file and asserted against its own copy. | fixed — all 18 guards now caught; sweep kept at `tools/housing_guard_mutation_check.py` |
| T-7 | A text splice while staging two campaign specs over-captured its block boundary and duplicated the confirmatory spec twice, silently raising its attempt count. Contract validation caught it. | fixed |
| T-8 | The completion-to-start cooldown held the provider lock for the entire call, so no two calls to a route ever overlapped and, with both models on one provider, the whole campaign serialised. Projected 89 hours for pilot plus confirmatory. | fixed — bounded-concurrency pacing and batched cells |

### judgment

| id | what happened | disposition |
|---|---|---|
| J-1 | Launched a variance pilot without the serial wall-time projection the campaign SOP requires beforehand. The projection, once run, said not to launch. | fixed — pilot stopped, projection published under `evidence/housing_operational_feasibility_2026-09-06/` |
| J-2 | Stated a holdout decision rule as fact — that a standard deviation at or below `0.0668` would let the sealed holdout carry the comparison — having ignored the declared `minimum_confirmatory_worlds`. The conclusion it implied was wrong. | fixed — corrected in QC §30 with the reasoning |
| J-3 | Selected a provider route from five spaced calls over about 75 seconds. It ran clean for four hours and then collapsed for two. The replacement, a 100-call hour-long probe, was still the wrong instrument for a ten-hour run. | mitigated — the durable fix was designing for bursts via retries, not hunting for a quiet route |
| J-4 | Treated a model-specific supply constraint as a series of unrelated provider incidents across six campaigns, changing route each time. Only the cross-campaign register made the pattern visible. | fixed — Tier 1 register built; see O-7 |
