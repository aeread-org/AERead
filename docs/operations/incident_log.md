# Incident log

**Status:** the single register of things that went wrong, across design,
operations, tooling, and judgment. One place, so an auditor can ask "what failed
and was it addressed" without reading five documents.

The QC standard requires preserving failed attempts as evidence and forbids
deleting history after a later fix. This is where that evidence is indexed. Detail
lives in the linked documents; this file is the index and the disposition.

## How to use it

- Add a row when something fails, not when it is fixed.
- `Detection` is the honest answer to "what caught it", including "a person read
  the output" and "nothing, it was found later".
- `Cost` is what the failure consumed: provider spend, a wasted run, a broken
  main branch, an incorrect claim published.
- A row is never deleted. `Disposition` changes.

Classes: **D** design, **O** operational, **T** tooling and process, **J**
judgment.

---

## The register standard

Four sessions independently built failure records in four shapes during
2026-09-05/06. They are consolidated here. The shapes were not arbitrary --
they answer two different questions -- so the standard keeps both and says
which is which.

**Tier 1, the machine register.** One row per failed cell, call or attempt,
**derived only from published evidence**, so every row traces to a committed
artifact by digest. It is regenerated, never hand-edited, and it answers "what
failed, how often, and where is the proof". Required layout, matching the
housing register:

```
evidence/<family>_failure_register/
  tables/failures.csv     # one row per incident
  reports/summary.json    # counts by campaign / stage / condition, + digests
```

Required row fields: `campaign_id`, `stage`, `failure_condition`,
`source_artifact`, `source_artifact_sha256`. Recommended where meaningful:
`failure_status_code`, `cost_usd`, `world_seed`, `condition_id`, `model_id`,
`attribution`. `summary.json` must carry `register_id`, `schema_version`,
`failure_count`, `artifact_sha256` and `rows_sha256`.

**Attribution is required when a family can distinguish blame.** The
data-center register's taxonomy is the standard one -- `budget`,
`environment`, `model`, `negotiation`, `provider` -- under its own rule:
*anything a model can trigger is the model's, never the provider's*. When a
row is reclassified, the original condition is kept beside the correction
rather than overwritten.

**Tier 2, this log.** One row per *judgment-bearing* incident: design defects,
operational policy failures, tooling accidents, and mistakes of reasoning.
These cannot be derived from evidence because they are about what the evidence
means. Classes: **D** design, **O** operational, **T** tooling and process,
**J** judgment. Per-family narrative detail lives in that family's own
document; this file is the index and the disposition.

### Rules for later additions

1. Add a row when something fails, not when it is fixed.
2. A row is never deleted. Only `disposition` changes.
3. `Detection` is the honest answer to "what caught it", including "a person
   read the output" and "nothing, it was found later".
4. `Cost` is what the failure consumed: provider spend, a wasted run, a broken
   main branch, an incorrect claim published.
5. A failed attempt root is evidence. It stays sealed and is never reused,
   and the Tier 1 register is rebuilt from it.
6. A fix that changes a frozen plan does not retro-publish the run it broke.
   Re-run instead, and record both the run and the reason in Tier 2.
7. New families add a Tier 1 register at the path above and one Tier 2
   section here. Do not start a fifth shape.

### Consolidated index

| Family | Tier 1 register | Incidents | Tier 2 detail |
|---|---|---:|---|
| housing | `evidence/housing/failure_register/` | 56 typed failures over 10 campaigns (45 `rate_limit`, 9 `timeout`, 1 `transport`, 1 `execution_error`; 48 trajectory, 8 profile-admission) | the Housing section below (34 rows); narrative in `docs/families/housing/qc.md` |
| datacenter | `evidence/datacenter_failure_register.{json,md}` -- **to be moved** to the layout above | 541 incidents over 573 cells in 10 runs; attribution after correction: model 298, negotiation 170, provider 47, budget 16, environment 10; 17 rows reclassified | its own register `.md` |
| procurement allocation | not yet built -- **owed** | 39 of 222 provider calls failed across the confirmatory work (17.6%) | `docs/families/procurement-allocation/design_review.md`, and the D/O/T/J sections below |
| econevals | `evidence/econevals_failure_register/` | 19 typed failures over 13 attempt roots (10 `rate_limit`, 3 `malformed_structured_output`, 2 `provider_rejected`, 2 `provider_contract`, 2 `invalid_measurement`); 176 retried provider-call failures beneath them; attribution provider 12, model 5, environment 2 | `docs/families/econevals/incidents.md` |
| termsbench | `evidence/termsbench_failure_register/` | 1 typed failure over 2 attempt roots (v1 aborted at 8/30 on `malformed_structured_output`, a decoding degeneration; v2 30/30 with no typed failure); 13 of 30 v2 episodes carry a measured individual-rationality violation, which is a score, not a failure row | the TERMS-Bench section below (TB-D-01..03, TB-O-01); `docs/families/termsbench/campaign_scoping.md` |
| govsim | not yet built -- **owed** | 3 live campaigns (`first_light_v1`, `dialogue_v2`, `dialogue_v3`) with 0 typed execution failures; the family's incidents are judgment-bearing (a fabricated-utterance near miss, an identity collision, a pre-fix source pin, an arm mismatch) rather than machine-derivable | [the govsim ledger](../families/govsim/incidents.md) (G-D-01..03, G-J-01..02) |
| tau3 retail | not yet built -- **owed** (PR #97) | 5 campaign identities in one day (v14-v18); v18 excluded 3 cases on the per-case cap and 1 on a malformed response | PR #97; no Tier 2 section yet |

Four registers exist in the required shape (housing, econevals, termsbench,
and the data-center one pending its move to the standard layout); procurement
still owes one, and tau3 and the seven #132 adapter families owe theirs. The gap is
recorded rather than quietly closed.

A note the econevals register makes concrete: a checkpoint records
`execution_failure` whenever the exception carries no `condition`, which is
true of every `SchedulerContractError`, so a register built from checkpoints
alone cannot tell a 429 from a 404 from a contract error. The typed
conditions must be recovered from the sealed event ledger. Any family
building a Tier 1 register should do the same rather than trusting the
checkpoint's label.


---

## 2026-09-05 / 06 — Housing delivery and confirmatory push

Opened while taking the Housing family from a partial variance pilot toward
the confirmatory comparison it was designed for. Tier 1 rows for this period
are in `evidence/housing/failure_register/`.

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
| D-9 | The scripted anchor present in `housing_population_crossplay_v0` was dropped from the model-sensitivity line, so environment or scorer drift cannot be distinguished from a model regression across versions. Two corrections to how this row was first argued, both mine. The live matrix is **not** missing a common yardstick: each subject already faces the same opponent panel, so the comparison is valid conditional on that panel, and an external reference adds robustness when the subject roster changes rather than rescuing a broken design. And the scripted anchor should be **retained**, not replaced: it is weak evidence of negotiation skill, since a policy that never rejects measures exploitation of a predictable counterparty, but it is a deterministic provider-free regression control, which is a different job from a live reference opponent. Keep both. | open |
| D-10 | The analysis contract declares `minimum_confirmatory_worlds: 30` while the sealed sweep provided 16 holdout seeds. No confirmatory campaign could satisfy both, and no variance however small changes it because the floor dominates the powered estimate. The two numbers live in different artifacts and had never been compared. | fixed — `housing_case_config_sweep_v2` extends the holdout to 36 seeds, 35 usable |
| D-11 | The sealed holdout contains a structurally unusable world: the severe configuration at seed `114691332` has a zero assignment upper bound, so it carries no normalized score. Found the first time the holdout was ever generated. | fixed — excluded before any outcome, exclusion re-derived from the generator at load |
| D-12 | `_critical_failure` decides whether a campaign halts by matching substrings in exception messages. Rewording an error silently changes stopping behaviour. | open |
| D-14 | A 404 meaning "no endpoint currently matches the pinned route" is typed `provider_rejected` and is not retryable, so a transient derank kills a cell outright. That is the same conflation of availability with identity as D-5, in the retry policy rather than the preflight. Whether it should be retryable is a measurement decision, not an obvious bug: retrying indefinitely against a genuinely absent route would hide a real pin failure. | open |
| D-13 | The primary estimand averages self-play into the live-opponent aggregate, which QC §5 says to keep separate. Changing it after the pilot would invalidate the variance the sample size derives from. | mitigated — cross-play and self-play published as predeclared slices |
| D-15 | A live reference opponent cannot be called "pinned" in the sense of fixed. A route and configuration digest identify the requested setup; they do not freeze a remotely hosted model's weights or serving behaviour, and inference varies even when weights do not. The correct term is a **version-pinned reference profile**, and trusting it needs repeated trials, interleaved subject conditions, and monitoring of the reference's own behaviour. A real model is also not automatically a realistic landlord: its incentives, information, willingness to reject and commitment behaviour each need validating before its scores mean anything. | open |
| D-16 | The primary outcome is invariant to price. `economics()` computes welfare as `sum(value - rent) + sum(rent - cost)`, in which every transfer cancels, so `social_welfare` and the `within_case_score` derived from it move only through which tenant is matched to which listing. Rent enters the recorded outcome in exactly one place, the IR check on a negative payoff. A landlord that negotiates a better price therefore scores identically to one that concedes, and the reference-landlord probe showed this concretely: the GLM live-reference and scripted arms returned byte-identical welfare and score from assignments whose signed rents differed. This bounds what any landlord opponent, scripted or live, can contribute to the headline metric. | open |
| D-17 | The live reference landlord made an economically incoherent decision on the first development world it ever saw. Listing 2's landlord held a private cost of 2117.37 with two offers in its inbox, 2150.00 and 2100.00, and accepted the 2100.00 offer: below its own cost and dominated by the alternative in the same inbox. The harness typed it `ir_violations: ["landlord:2"]`, so the accounting caught it, but it is direct evidence for D-15's warning that a real model is not automatically a realistic landlord. The scripted control cannot produce this failure by construction, since it filters to offers at or above cost. | open |
| D-18 | The score's normalizer is not bounded away from zero, only away from exactly zero. D-11 excluded the one holdout world-config whose assignment upper bound was 0, but `holdout_severe_unseen` at seed `1207545696` has a bound of 56.18 against a median of 1828 and a next-smallest of 782, a fourteenfold gap. Dividing by it amplifies that cell's eight trajectories to a standard deviation of 1.27 against 0.116 for the other 709, and all four negative scores in the campaign come from it. The frozen primary is unaffected, moving from 0.0046 to 0.0043 when the world is dropped, but both predeclared slices are: each is inconclusive as frozen and both fall entirely inside the minimum meaningful effect once it is removed. So the slice imprecision is one degenerate normalizer, not model variability. The exclusion rule should test the bound against a floor, and the floor belongs in the sweep contract. | fixed in code, opt-in per contract — `confirmatory_panel.minimum_upper_bound` adds the typed exclusion `below_upper_bound_floor`, re-derived from the generator like the zero rule and refused if declared but unapplied; the sealed v2 panel declares no floor and verifies unchanged; the next sweep must choose the value |
| D-20 | A sealed receipt's digest covers the receipt dataclass's whole field set, so adding a kernel field retroactively invalidates every receipt sealed before it. `EvaluationReceipt` gained `deferred_leaf_ids`, that change reached this branch in the mid-run merge at `4474b7ff` on 2026-09-07, and all 720 receipts of the confirmatory campaign now fail `verify_evaluation_receipt` with `receipt_sha256 does not match receipt content`. The published bundle is unaffected and still verifies: its four self-hashed artifacts recompute, its 36 fact tables match their manifests, and the failure register reproduces byte for byte. What is lost is regeneration. My first diagnosis, recorded here and wrong, was an un-incremented `spec_version`. The actual cause: the repository already rules on additive fields (R1, `_CANONICAL_OMIT_IF_DEFAULT`, used by `MeasurementDeclaration.leaves`) and the new field did not opt in; worse, the dataclass digest built its field dict by hand and bypassed that rule for every field, while `read_evaluation_receipt` hashed the durable bytes as stored. Two verification paths, one faithful and one not. Republishing at the sealing commit `6ff6b0b5` was confirmed to work in a scratch worktree and rejected as a workaround. | fix in PR #151, rebased on main at `2e533384` after review — field opts into R1, one accepted-digest computation shared by the dataclass and bytes paths (canonical plus the four-day transitional preimage), overwrite compares verified content, `receipt_preimage_kind` makes the compatibility path visible to an audit; the reviewer's write-side blocker reproduced and is closed by regression tests; 3170 local receipts verify byte-exact; awaiting re-review |
| D-19 | The published interpretation prose contradicted the machine fields it sits beside. `claim_status`, `ranking_allowed` and `leaderboard_eligible` all recorded a confirmatory model comparison while the prose told the reader this was exploratory pilot evidence and not a ranking. Every machine field learned the confirmatory distinction when the publisher was made confirmatory-aware; the prose branch still keyed only on whether the full-trajectory gate had passed. A reviewer reads the prose, so the artifact told a human not to analyse a result its own fields licensed. | fixed in code, not yet in the artifact — the interpretation now branches on `is_confirmatory`, but the published bundle still carries the pilot wording because it cannot be regenerated while D-20 stands |
| D-21 | The live landlord seat has no stated objective. `HOUSING_LANDLORD_PROMPT` in `src/aeread_families/housing/runner.py` is three lines: it names the model "a deterministic controlled landlord", tells it to respond only to its inbox and create at most one hold, and asks for one JSON object. Nothing says the landlord should not accept below its private cost, or what it is trying to do; the wording is the scripted controlled landlord's self-description reused for a model seat. This is verifiable from the repository. What is not: in the local run root, which is not committed and whose reasoning the publication policy excludes, GLM's reasoning on the below-cost accepts reads as having adopted an accept-the-best-offer rule from that framing; 22 such accepts were counted there against 2 for DeepSeek. Treat those counts as an unverified local observation. The prompt sits inside the implementation digest, so changing it is a new campaign identity. Related: D-17. | fixed in code, opt-in per contract — `controls.prompt_version: housing_prompts/2.0` selects `housing_landlord_v2` and `housing_tenant_v2`, which state each seat's payoff and the never-below-cost / never-above-value rule; version 1 stays verbatim inside every sealed digest |
| D-22 | GLM as landlord signs leases at zero rent; the primary outcome cannot see it. Verifiable from the committed `trajectories/attempted.json` (artifact `da01cba93ade…`) by summing `signed_rents` and `ir_violation_count` per opponent seat: 264 of the 1601 leases signed under a GLM landlord carry `rent: 0.0`, against 0 of 1565 under DeepSeek, and IR violations occur in 213 of 358 GLM-landlord cells against 17 of 359. The primary outcome is blind to this because rent cancels in welfare (D-16) and a zero-rent lease to the same tenant is the same assignment an accept would have produced; it surfaced only on the thin-market world where the match itself destroys value (D-18). Both fields were recorded per trajectory and never aggregated into the published analysis or the QC write-up. Not verifiable from the repository, observed only in the uncommitted local run root: the leases originate as `decision: counter, counter_rent: 0.0` actions, 275 of them, always against a real offer id, and the model's reasoning on sampled cases reads as an intent to accept the best offer rather than to give the unit away. The mechanism is unproven; both models emit `counter_rent` before `decision`, and once a number is written there the schema's `oneOf` admits only "counter". | mitigated — cause still unproven; the consequence is now closed by D-23's floor, and `evidence/housing/landlord_seat_accounting/` aggregates zero-rent leases and IR cells per landlord seat from committed rows, which shows the same pattern in every multi-world campaign that carried the fields (V23 34 of 284, V26 41 of 284, confirmatory 264 of 1601), never once under DeepSeek |
| D-23 | A rent of zero is legal at every layer, verifiable from the repository: the respond schema `HOUSING_RESPOND_OUTPUT_SCHEMA_V2` declares `counter_rent` with `minimum: 0`, `_valid_rent` in `environment.py` accepts any finite rent at or above zero, and `_validate_admission_action` checks the field set, types and offer ids only. Nothing in the pipeline compares a landlord's action with its own cost, so the zero-rent leases in D-22 passed schema, admission and legality without a mark. | fixed in code, opt-in per contract — `controls.minimum_rent` is enforced in three places that now agree: `housing_actions/2.1` raises every schema rent minimum to it, the market refuses a counter or offer below it as a typed invalid response with no hold, and admission validates against it; a contract that declares no floor behaves exactly as before, so sealed receipts replay |
| D-24 | The design treats a validity constraint as a metric. A market outcome has three properties, efficiency, individual rationality and distribution; welfare covers the first, and individual rationality was recorded per cell and then averaged away. An agent that signs a lease at zero rent or accepts below its own cost has not negotiated badly, it has failed to understand its own payoff, a capability failure of the same kind as an unparseable action, and the register already treats those correctly: type it, count it, gate on it, never average it into the score. Under that rule GLM as landlord would have failed 213 of 358 confirmatory cells outright. See the QC document, section 32. | fixed in code, opt-in per contract — `subject_ir_violation_policy: typed_failure` with `maximum_subject_ir_failure_fraction`, `secondary_estimand: subject_surplus_share`, and `winner_claim_rule: primary_and_secondary_consistent`; rows carry the seat split; opponent-seat violations are reported and never exclude the subject; new campaign identity to use |
| D-26 | The difficulty knob does not move what the design needs it to move. The three holdout configurations span listings 6/5/4 and `common_weight` 0.45/0.70/0.95, so the idiosyncratic share of tenant value runs from 55% to 5%, nearly the whole range of how much sorting can matter. The model-minus-baseline gap across them is -0.041, -0.042, -0.042 and the win rate 40.6%, 41.2%, 39.6%: flat to three decimals. Tuning this knob for discrimination cannot work, and neither branch of the usual dilemma holds — at the hardest configuration the models score highest (0.854), so nothing collapses. Meanwhile the opponent seat moves the score by 0.033 (0.811 under a GLM landlord against 0.844 under DeepSeek), as large as the whole baseline gap, which is the same confound as D-16 and D-22 seen from the design side. | open — discriminate by controlling the opponent seat and by reporting a like-for-like baseline, not by re-tuning market tightness |
| D-27 | The primary metric does not measure the seat under test. Full argument in `docs/families/housing/estimand_review.md`. Decomposing all 717 completed confirmatory cells: the case (world x configuration) explains 42.8% of score variance, and the **subject explains 0.000258**, less than half the 0.144 a meaningless label captures by chance in the same design (D-28). Within a fixed case the opponent explains 56.4% of what remains and the subject 6.7%. Across the 90 cases, what a one-line heuristic scores predicts the models' score at r=0.81. The primary contrast by configuration is +0.024, -0.015, +0.011: it changes sign, so the confirmatory null was a null because the estimand carries almost no agent signal, not because two models happen to be equal. This is D-16 seen from the design side: the tenant seat's main lever is price, welfare cancels price, so the seat under test was placed in the channel the metric is blind to. The environment is not at fault. Recomputing the same cells against tenant surplus share, the subject's share of within-case variance rises from 6.7% to 26.7% and the contrast becomes monotone in difficulty, +0.141, +0.296, +0.867 as `common_weight` goes 0.45, 0.70, 0.95, which is the dose-response a capability measure should show. Caveat: tenant surplus exceeds 1.0 on average, because landlords signing below cost subsidise tenants, so without D-23's rent floor and D-24's IR gate that metric scores exploitation of a broken counterparty rather than negotiation. | mechanism isolated, fix landed opt-in, one claim of mine corrected — the provider-free control settles the ordering question decisively: welfare rates a truthful bidder capturing exactly zero surplus at 0.964 against a shrewd bidder's 0.870, so it does not blur the distribution ranking, it inverts it, and the paired naive-minus-truthful contrast is -0.094 on welfare against +0.746 on surplus. **What the variance decomposition does not establish, and what I first claimed it did, is that surplus detects these two models where welfare cannot.** Against a permutation null that preserves the design, the confirmatory subject share is p=0.746 on welfare and p=0.390 on surplus: neither is detectable, and the point estimates 0.067 and 0.267 both sit inside a null whose 95th percentile is near 0.30. Both metrics do detect the opponent, at p=0.003 and p=0.001. So the decomposition licenses `the estimand does not measure the subject on this panel`, and the control licenses `welfare mis-orders the distribution`; it takes both, and the clean-landlord slice, to reach the recommendation |
| D-28 | The variance pilot and the confirmatory comparison ran on different environments, so the pilot's variance never transferred and could not have revealed the estimand failure. The pilot panel is 6 tenants over 5, 4 and 3 listings at common weights 0.85, 0.85 and 0.30 over 2 rounds; the holdout panel is 8 tenants over 6, 5 and 4 listings at 0.45, 0.70 and 0.95 over 3 rounds. Judged against chance, which for two subjects and eight cells per case is 0.144 of within-case variance, the subject's share of the welfare score is 2.00 and 2.33 times chance on the two pilot campaigns and 0.47 times chance on the holdout; the surplus estimand runs the other way, 0.79 and 0.51 on the pilots against 1.86 on the holdout. So neither metric's ability to see the subject survives the panel change, in either direction. The world count the confirmatory used was derived from between-world variance measured where welfare still carried signal, and spent where it did not. This is independent of D-27: even a metric that responds to the subject would have been sized on the wrong environment. | open, and now the better-evidenced of the two — under a permutation null the subject's welfare share is detectable on the pilot panel at p=0.004 and p=0.001 and undetectable on the holdout at p=0.746. The pilot therefore did see subject signal in the metric it sized the campaign with, and the panel change removed it. The Gate 3 diagnostic must run on the frozen panel, and a pilot must share the confirmatory generator parameters or declare why a different one is admissible |
| D-25 | The confirmatory report never placed the models against the declared comparison baseline. `comparison_baseline` is in every scored receipt and `comparison_baseline_gap` is a declared metric, yet neither appears in the confirmatory analysis or the QC write-up. The naive scripted market scores 0.869 against the models' 0.827. **Correction to my first statement of this row, which called that a like-for-like loss to a one-line heuristic: it is not like-for-like.** `run_scripted_market` pairs the naive tenant with the *scripted* landlord, which never rejects outright; the models faced *model* landlords rejecting 6.2% (DeepSeek) and 35.5% (GLM) of responses. The gap tracks that exactly: -0.025 against a DeepSeek landlord, -0.058 against a GLM landlord, and models beat the baseline on their own world in 40.4% of cells, so this is a mean deficit with wide spread, not a uniform loss. Roughly half the gap is the counterparty, not the tenant. | open — the next contract needs a like-for-like baseline: the naive tenant policy against the same model landlord, reported beside the primary |

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
| O-11 | A merge landed in the working tree while the confirmatory campaign was still executing. The run started 2026-09-06 18:17 and finished 2026-09-08 06:28; the merge landed 2026-09-07 20:38, so 216 of the 720 receipts were written after the source under the run had changed. The campaign was unaffected at the time, because the running process kept the already-imported module, which is precisely why nothing looked wrong for another ten hours. Long campaigns need a checkout that cannot move under them. | open |
| O-12 | Gemini 3.7 Flash on the Google AI Studio route, placed in the landlord seat under action schema 2.0 in a development probe, returned the JSON literal `null` for 12 of 12 landlord actions in each of two thin-market cells. The harness typed each `malformed_action`, which is not a retryable condition, so no hold was ever created and both cells scored zero. A `oneOf` of `const`-discriminated branches is not something this route honours. Probe evidence is in the uncommitted run root only. | fixed in code, opt-in per contract — replay showed the route refuses any top-level union of branch objects and honours the flat shape with a rent minimum; `housing_actions/2.2` carries that shape with the floor, a `null` reply is typed `structured_output_unsupported` in the parser and at admission, and a campaign declares one schema version for every seat; live verification under 2.2 recorded in the QC document, section 32 |
| O-10 | The reference route `openai/gpt-oss-120b` on CoreWeave fp4 returned three `malformed_response` actions in each of the two live-reference probe cells, and one 429 on the shared upstream pool. Retries recovered every one and all four probe cells completed, so this is a cost and latency finding rather than a loss, but a reference opponent that needs retries on roughly a tenth of its actions has to be sized for that before it carries any campaign. | open |

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
| T-10 | The additive-receipt-field drift is recurring, not a one-off. While PR #151 was under review, 37 receipts sealed on 2026-09-08 by a TERMS-Bench pilot on this machine turned up carrying `scripted_seats`, a field from the unmerged scripted-seats kernel (#150) that neither `main` nor #151 has on the receipt. They pass the bytes path and fail the dataclass path identically on both, because the deserializer drops the unknown key. That is the third field in five days to arrive without digest-neutral treatment; each one strands every receipt sealed before it. #151's shared accepted-digest computation is the mechanism, but the rule has to be: a new receipt field opts into `_CANONICAL_OMIT_IF_DEFAULT` with a literal default in the same commit that adds it. | open — noted on #151 for #150 |

### judgment

| id | what happened | disposition |
|---|---|---|
| J-1 | Launched a variance pilot without the serial wall-time projection the campaign SOP requires beforehand. The projection, once run, said not to launch. | fixed — pilot stopped, projection published under `evidence/housing_operational_feasibility_2026-09-06/` |
| J-2 | Stated a holdout decision rule as fact — that a standard deviation at or below `0.0668` would let the sealed holdout carry the comparison — having ignored the declared `minimum_confirmatory_worlds`. The conclusion it implied was wrong. | fixed — corrected in QC §30 with the reasoning |
| J-3 | Selected a provider route from five spaced calls over about 75 seconds. It ran clean for four hours and then collapsed for two. The replacement, a 100-call hour-long probe, was still the wrong instrument for a ten-hour run. | mitigated — the durable fix was designing for bursts via retries, not hunting for a quiet route |
| J-4 | Treated a model-specific supply constraint as a series of unrelated provider incidents across six campaigns, changing route each time. Only the cross-campaign register made the pattern visible. | fixed — Tier 1 register built; see O-7 |
| J-5 | A commit was pushed with two failing tests. The command chained `pytest ... | tail` before `git commit`, so the pipe reported tail's exit status and the chain proceeded past a red suite; the two failures were layout tests that the same commit had made stale. Caught on reading the output, fixed in the next commit, but for one push `main`-bound history carried a red test. Rule: never gate a commit on a piped test run; capture pytest's exit status directly. | fixed — `b9842a6b` |
| J-6 | Edited `runner.py` while the Gemini probe was executing. The probe builds each cell's plan lazily, so the first cell's plan carried the old implementation digest and its receipt failed `plan_implementation_pins do not match measurement implementations` at finalize; later cells were built from the new source and sealed fine. The same class of error as O-11, on the same day it was written down. Rule: do not touch the family's source while any run that imports it is in flight. | fixed — the cell's events and outcome survive without a receipt |

---

## 2026-09-05 to 2026-09-06, procurement allocation

### D — Design defects

Fifteen defects with recomputed evidence are enumerated in the
[procurement design review](../families/procurement-allocation/design_review.md),
with a per-defect status table at its end. They are not duplicated here. Summary
as of 2026-09-06: seven fixed, one reopened, seven open. The two most consequential:

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| D-05 | `outcome["feasible"]` is true for a deferral, and every campaign guardrail used it | reading the deferral analysis by hand | a supported development claim rested on a guardrail a defer-heavy treatment could satisfy | fixed: `feasible_award` published per row and guarded; adversarial test added, mutation-verified |
| D-14 | nothing checks that a holdout leaves the control room to fail | a completed 144-row run producing a near-zero effect | $0.45 and the entire confirmatory result | fixed in the standard as a Gate 1 measured-headroom requirement; a $0.015 screen now precedes any panel |

### O — Operational failures

Route: GLM 5.3 Flash on Parasail. Aggregate over the confirmatory work,
**39 of 222 provider calls failed, a 17.6% failure rate.**

| date | campaign | outcome | cost |
|---|---|---|---|
| 09-03 | risk-gate factorial V1 attempt 001 | 77 rows then a typed 429; sealed with 66 unattempted | $0.2067 |
| 09-03 | risk-gate V1 attempts 002-005 | four fresh attempts, canary rejections and early seals | ~0 |
| 09-03 | risk-gate V3 attempt 001 | 135 of 144 rows then a 429 | $0.400 |
| 09-03 | risk-gate V4 attempt 001 | 13 rows then four consecutive 429s | $0.0417 |
| 09-04 | worksheet V1 attempts 001-003 | timeout at row 2; operator interruption; 429 after 7 rows | $0.0235 |
| 09-04 | worksheet V1 attempt 004 | **qualified**, 72/72 | $0.1993 |
| 09-04 | worksheet V2 attempt 001 | **qualified**, 72/72 | $0.2065 |
| 09-05 | pre-award check attempt 001 | **qualified**, 72/72 | $0.2672 |
| 09-05 | pre-award confirmatory v1-v3, seven attempt roots | 24 rows total; two died on a canary 429 before any row | $0.0636 |
| 09-06 | pre-award confirmatory v4 attempt 001 | 144/144 attempted, 12 typed missing, **ineligible** on the per-arm ceiling | $0.4512 |

Two operational findings promoted to design defects: a transient 429 on the
unscored, zero-cost canary permanently seals an attempt root (D-10), and
abort-on-first-failure makes completion probability decay exponentially in panel
size (D-11, fixed).

### T — Tooling and process failures

All mine, all during this session.

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| T-01 | a merge-chain script's `cd` fell through to the operator's live checkout and created two merge commits on their working branch | noticed while inspecting an unrelated failure | two unwanted commits on a branch in use | reverted with `git reset --keep`; the branch matched origin afterwards; script now guards `cd $wt \|\| exit` and asserts the branch |
| T-02 | a `pkill` pattern intended for a campaign also matched the regression run's own test filename and killed it silently | the log stopped advancing | a 25-minute test run lost | rerun; noted that process-name patterns collide with test filenames |
| T-03 | a conftest merge resolution dropped a function definition line, leaving an `IndentationError` that broke collection repository-wide | a full-suite run, 36 minutes | main red for ~10 minutes | hotfix PR #85; an AST-parse test and an import smoke now catch it in seconds |
| T-04 | the consolidated conftest used dict entries where two adapters unpack three-tuples, and renamed a summary title a third asserts | a full-suite run | main red; 2 of 1547 tests failing | hotfix PR #88; all seven gated families' own tests now run in the QC layer |
| T-05 | a run driver started without `--resume` against an existing attempt root, so the campaign raised `FileExistsError` and the driver reported "no rows" | reading the driver log | one restart | driver now resumes when the root exists |
| T-06 | the driver's no-progress guard fired on a *completed* panel and reported it as stopped | reconciling the log against the run root | a moment's confusion about whether the panel finished | benign; the guard needs a completion check before a progress check |
| T-07 | campaign exit codes still treated any typed missingness as an abort after the policy changed to tolerate it, so a resuming driver stopped at 24 of 144 rows | the run stalled at a checkpoint | one restart | exit codes now return the abort code only when the declared ceiling is breached |
| T-08 | a scripted port of the missingness policy into a sibling campaign module failed midway on a text-block extraction | the module failed to build its plan | reverted, no lasting effect | the screen was run through the qualification engine directly instead, which needed 35 lines rather than a 1,100-line campaign clone |

T-08 is worth reading twice: it is the cost of design defect D-12 made concrete.
A fix applied to one campaign module does not reach its four near-identical
siblings, and the siblings exist because the plan digest conflates scientific and
operational parameters.

### J — Judgment failures

Also mine. These are the ones no test would have caught.

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| J-01 | built a confirmatory holdout by matching the failure *themes* of the development panel rather than its *difficulty*; the control saturated 7 of 12 worlds | the completed run's near-zero effect, then a per-world control-rate check | $0.45 and the confirmatory result | D-14 raised; Gate 1 now requires measured headroom; the bad panel is retained as the detector's regression fixture |
| J-02 | reported that panel as showing the treatment "does not replicate" | re-examining the control rate after being asked why it failed | an overstated claim, live for about twenty minutes in conversation and one commit | corrected in the campaign document, the QC profile, and PR #98; the correct reading is that the panel is uninformative in either direction |
| J-03 | fixed "verbal claims are always true" by biasing the verbal reply, without checking that any evaluated policy reads verbal replies; a screen recorded zero `inquire` actions across a whole panel | a $0.0153 control screen | would have wasted a $0.30 run; caught before spending | D-01 reopened, D-15 raised; the bias must sit on the listing |
| J-04 | recommended cutting working capital because it is "arithmetic over facts already held" | the operator asked whether it models a reselling process | an incorrect rationale in a design document, corrected the same day | the real objection is scale: $50 lines against ~70% margins make the term worth ~$0.72 at honest parameters, and the six cases where it matters use 150-200% annual financing |

J-01 and J-03 share a cause: a panel was authored against an intuition about what
would be hard, and neither intuition was measured before the panel was frozen.
The $0.015 control screen now exists precisely because it is three orders of
magnitude cheaper than discovering the same thing from a completed run.

---

## Standing lessons

1. **Measure the panel before you spend on it.** A control screen at one seed
   costs about $0.015 and has now caught two unusable panels.
2. **Check that a channel is read before you put information in it.** Zero
   `inquire` actions made a correct, tested mechanism inert.
3. **A guardrail that nothing fails is not a guardrail.** Prove it with a
   synthetic arm that games the metric.
4. **A check that has never failed may be true by construction.** Kill it by
   mutation, and record when a mutation survives.
5. **Scripted git belongs in a scratch worktree**, with `cd ... || exit` and a
   branch assertion, never in a checkout someone is using.

---

## 2026-09-05 to 2026-09-06, econevals first light

Building the first live path for an adapter that had corpus, environment,
measurement and replay but had never resolved a run plan or sealed a receipt.
Thirteen attempt roots, twelve of which failed. Per-attempt detail, recovered
from the sealed roots rather than from notes, is in
[the econevals incident ledger](../families/econevals/incidents.md).

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| E-D-01 | the kernel called `plugin.initial_state(family_case, run=None)` in the replay path but positionally in the scheduler; nine of eleven external adapters name that parameter `cell`, so **no external adapter could produce a replayed receipt** | building the first live path for one of the nine | every external adapter's receipts, silently, since the reorg; blocks #91, #92, #93 alike | fixed by calling it positionally; a signature test now covers all 18 plugins |
| E-D-02 | the frozen plan hashed `campaign.py`, which carries the publisher as well as the executor, so a publisher bug is unfixable for a completed run: publish and it crashes, fix it and the freeze rejects its own run | a complete six-case panel that could not be published | $0.0925 and a full panel | freeze now covers execution sources only; publisher digest moved to the publication manifest; run repeated rather than retro-published |
| E-D-03 | neither the observation nor the submit tool's schema stated the submit argument's required shape | a 100-period run in which the model submitted `[]` every period | one panel; scoring it would have measured our omission, not the model | shape declared per track on both surfaces |
| E-D-04 | the family manifest declared no `scoring.reference_provider_ids` while its leaves cite seven implementations; the resolver rejects an unreferenced pin, the receipt rejects an unpinned citation | first plan resolution | none, caught pre-spend | union computed from the leaf builders so manifest and pins cannot drift |
| E-D-05 | the scorer had per-attempt methods but no once-per-episode finalizer, so the kernel could not call it at all | first finalize attempt | none, caught pre-spend | `FamilyScoreSet` finalizer added, surfacing both leaves (closes #74) |

### O — Operational failures

Route: GLM 5.3 Flash on Parasail, the same shared upstream pool procurement
uses.

| date | attempt | outcome | cost |
|---|---|---|---|
| 09-06 | 001, 002 | canary rejected: route seal shape, then a transient 429 that sealed the root | $0 |
| 09-06 | 003-006 | four contract errors, each dying on the first action: undeclared seed, invented tool name, truncation at 900 tokens, an unretried 429 | $0.00015 |
| 09-06 | 007 | 100 periods, receipt excluded on a malformed submission; campaign wrongly aborted on a measurement verdict | $0.00004 |
| 09-06 | 008 | case 00 scored `included`, then a spurious Parasail **404** | $0.0255 |
| 09-06 | 009 | two procurement cases scored, then an empty turn exhausted the harness's corrective rounds | $0.0228 |
| 09-06 | 010 | ten attempts against a 429 burst exhausted in two minutes: backoff is opt-in and none was declared | $0.00004 |
| 09-06 | 011 | **6/6 cases `ok/included`**, 100 periods each -- unpublishable, see E-D-02 | $0.0925 |
| 09-06 | 012 | spurious Parasail **404** again, on the first action | $0.00003 |
| 09-06 | 013 | two procurement cases scored, then a sustained 429 exhausted ten attempts **with** backoff (~3 min of spread) | $0.0689 |

Disposition: a route-availability block, not a campaign defect. Attempt 011
ran the identical panel to completion, so the frozen plan is re-run in a
later window rather than adjusted.

Two operational findings promoted: the write-once canary (D-10 in the
procurement section) sealed two roots here before the fix and then saved two
more, and retry policy inherited from a 12-round chat family is wrong for one
making 600 sequential calls.

### J — Judgment failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| E-J-01 | sized the panel's retry policy by copying tau3's profile instead of multiplying out this family's call count | a 429 killing a run at case 00 | one attempt | attempts raised to 10 with declared backoff, and the arithmetic written into the profile |
| E-J-03 | reported per-attempt costs from checkpoints that omit a failed case's spend, understating what the failures consumed by 44% | the operator asked whether a 429 costs anything | an understated incident ledger, corrected the same day | failure checkpoints now recover sealed spend; ledger figures restated |

**E-J-03 is not econevals-only.** A survey of every family's failure path:

| family | failed-case spend recorded? |
|---|---|
| housing | yes -- `cost_usd` plus a `billing_status` field on the failure row |
| procurement allocation | yes -- `_sealed_failure_telemetry` recovers incurred usage from the sealed event ledger and flags `telemetry_complete` |
| econevals | **was no**, fixed here |
| tau3 retail (PR #97) | **no** -- the failure checkpoint records `failure_type` and `failure_condition` only, so a case killed after successful turns reports no spend |

econevals inherited the omission by copying tau3's checkpoint shape, which
is the same way it inherited tau3's retry and backoff policies (E-J-01).
Procurement's `_sealed_failure_telemetry` is the better pattern of the two
implementations -- it reads the event ledger rather than walking artifacts,
and it says when telemetry is incomplete rather than silently summing what
it found. Raised for tau3's owner rather than changed here.
| E-J-02 | planned to truncate periods through the agent budget to fit the cost ceiling | a dry run showing it raises `SchedulerContractError` rather than terminating cleanly | none, caught pre-spend | cases run at their own pinned `max_steps`; it would have manufactured failed receipts |

## Standing lessons, added

6. **A first live campaign is a defect detector.** econevals had four
   milestones of tests and thirteen defects survived to the first live run,
   four of which would have produced misleading evidence rather than a clean
   failure.
7. **Do not put the publisher inside the execution freeze.** Evidence
   projection describes how a run was reported, not what it did.
8. **Copying an execution profile copies its assumptions.** tau3's retry,
   backoff and round policies are correct for 12-round chat episodes and
   wrong for 100 sequential calls per case.
9. **A verifier rejecting the model is not a broken pipeline.** Conflating
   the two makes a panel unable to report the thing it measures.
10. **Decompose the variance of your metric before you trust a result, and do
    it before the campaign, not after.** The full procedure for auditing a
    result after execution, and the two provider-free steps that identify
    causes rather than symptoms, are in Gate 3 of
    [the benchmark QC standard](benchmark_qc.md); the worked instance is the
    [Housing estimand review](../families/housing/estimand_review.md). Housing ran ten campaigns, a variance
    pilot, a sealed freeze and a 720-cell confirmatory comparison for $6.90,
    and reported a precise null. Decomposing the 717 completed cells
    afterwards showed the case explained 42.8% of score variance and the
    subject under test explained 0.000; the opponent explained 56.4% of what
    remained, and a one-line heuristic predicted the models' score at
    `r = 0.81`. The interval was correct. It was a correct measurement of
    almost no agent signal, and no amount of sample size, sealing or
    replication would have revealed that, because every one of those
    protections assumes the estimand responds to the thing being compared.
    The cheap check is a provider-free control arm: score two deliberately
    different scripted policies and one random policy on the frozen panel and
    confirm the metric separates them. Had that run, it would have cost
    nothing and stopped the line before the pilot.
11. **A metric that cancels a seat's only lever cannot measure that seat.**
    Housing welfare sums value minus rent plus rent minus cost, so every
    transfer cancels and the score moves only through the assignment. The
    tenant seat's lever is what it agrees to pay. The design therefore put the
    model under test in the one channel its own metric is blind to, while the
    landlord seat, which gates whether a lease exists at all, carried the agent
    variance the score did register. Recomputing the same cells against tenant
    surplus raised the subject's within-case share from 6.7% to 26.7% and
    turned a sign-flipping contrast into a monotone one, `+0.141`, `+0.296`,
    `+0.867`, as the case got harder. Before freezing an estimand, name each
    seat's lever and check the metric is a function of it.
12. **A flat result across a difficulty sweep is a design signal, not a
    finding about models.** The Housing model-minus-baseline gap was `-0.041`,
    `-0.042`, `-0.042` across configurations spanning `common_weight` 0.45 to
    0.95, nearly the whole range over which sorting skill can matter. A
    quantity invariant to the parameter it should depend on is not the
    quantity it is named. Read it as evidence about the instrument first, and
    only then about the subjects.
13. **Diagnose the estimand before prescribing hygiene.** Faced with the flat
    sweep, the first prescription written here was a like-for-like baseline, a
    controlled opponent seat and fuller reporting. All three are worth doing
    and none of them was the cure; controlling the opponent would have removed
    variance from the only agent channel the metric responded to, producing a
    cleaner measurement of nothing. The user's reading, that a result which
    does not vary with difficulty means the benchmark is not measuring
    capability, was the correct one.


---

## 2026-09-06, pull-request discipline and stack verification

Adopting the PR lanes (#121), reviewing the fourteen-PR migration stack, and
building its combined tree on a scratch branch. Rules that came out of it are
in `CLAUDE.md` ("Merging is a step that can fail").

### T — Tooling and process failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-T-01 | while waiting for #121's CI, a chained command attempted the merge (correctly refused by branch protection) and then PATCHed `kernel-review` into the required status checks unconditionally -- before the workflow existed on `main`, the ordering the PR itself warns against | noticed in the command's own output | ~3 minutes in which every open PR would have blocked on a check it could not receive; no PR merged or blocked | reverted at once; the re-run checks `state == MERGED` before touching repository settings; rule recorded in `CLAUDE.md` |
| P-T-02 | the first combined-tree chain ran `for spec in $ORDER` under zsh, which does not word-split an unquoted variable: it merged one branch and logged "all 14 merged" six seconds later, then started a full suite on the wrong tree | the log claimed completion in six seconds | one aborted suite run | killed and rerun as a bash script with an array; noted that chain scripts must not rely on zsh word-splitting |
| P-T-03 | git's `merge=union` driver, tried as an automation of the stack's "every conflict is a union" rule, concatenated both sides of the two set literals every family edits and left the protocol-test module unparsable (`IndentationError`); the bound-names check could not run because the file no longer parsed | `ast.parse` failing in the checker | none, scratch branch only | "the file parses" added as step zero of the recipe; the structural fix (per-family enrolment modules) proposed on #103 |

### J — Judgment failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-J-01 | a docstring fix pointed at a historical design document with a blank commit hash, then with a commit that did not contain the file, before the third attempt verified the path with `git cat-file -e` | a verification step added after the second wrong hint | two force-pushes to an unreviewed branch | fixed; verify a `git show <sha>:<path>` hint before writing it |

---

## 2026-09-07, trajectory grain backfill

Publishing the kernel trajectory grain (#136, #138) into the already-published
procurement bundles (#139).

### T — Tooling and process failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-T-04 | the local full-suite gate was `pytest ... \| tail -4` and the exit code read was `tail`'s; the first push of #139 was described as "full suite green locally" while five confirmatory tests were red | CI failed 20 tests on the same tree | one CI cycle; a wrong claim on a PR | suite commands now `set -o pipefail` and read pytest's summary line; #136–#138 had been independently green on CI |
| P-T-05 | the P-T-02 zsh trap recurred: `for p in $PINNED` did not split, so seven paths became one, and `mv`/`git checkout` failed on a too-long filename | the commands' own errors | none; nothing was moved | redone in Python; shell loops over lists stay in bash arrays or Python |

### J — Judgment failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-J-02 | ten bundles were re-sealed with the grain as a "mechanical correction" without checking whether anything froze their manifests; seven are pinned as parent controls (`PARENT_EVIDENCE_FILE_SHA256`) by later campaign modules, and a changed frozen control requires a new campaign identity | CI: `parent ... evidence manifest changed` | one CI cycle | parents restored byte-for-byte; their rows published as a derived bundle bound to the parents' digests; the leaf-only rule and the pin check are now in `reviewing_trajectories.md` §5 |

## 2026-09-08 — judgment: a frozen control edited in place under a published campaign

`#98` added `feasible_award` to the `primary_outcomes` list in
`procurement_allocation/model_campaign.py`. That list is frozen into every
plan `planned_model_qualification` builds, and one of those plans --
`procurement_allocation_glm53_flash_parasail_qwen_holdout_transfer_v1`,
published in #62 -- had already been sealed under the old list. After #98,
rebuilding that plan from source no longer reproduced its sealed digest
(`3fbba58a…` became `8dc6d893…`), and #62 went red on a test that exists
precisely to notice this.

Campaign discipline says a changed frozen control takes a new identity. #98
changed it in place. The consequence was contained -- the sealed bundle is
untouched and correct, and no published evidence carried the parent digest --
but "the test was wrong" would have been the easy reading, and updating the
recorded digest would have deleted the only record that a frozen plan had
stopped matching its source.

Disposition: `primary_outcomes` is now a parameter threaded from each
campaign's spec, defaulting to today's list; the sealed campaign declares the
list it sealed with. Its digest reproduces again, and no other campaign's
digest moved (42 procurement digest tests). The rule that should have caught
this at review time, not test time, is the one #143 adds.
## 2026-09-08 — tooling: main went red on a test neither PR had seen fail

#125 added a two-way coverage ratchet over `TRUSTED_BUILTIN_PLUGIN_KEYS`.
#147 enrolled seven datacenter keys as trusted, merging at 05:15Z -- after
#125's last CI run and before its merge at 17:26Z. Each PR was green on its
own; `main` at `b728736d` fails
`test_every_trusted_key_is_checked_or_named_as_uncovered`, and #107's CI hit
the same wall first.

Not a defect in either PR. It is the gap branch protection leaves open: a
required check is evaluated on the PR head against the base *at trigger
time*, not at merge time, so two green PRs can compose into a red main.
Disposition: the keys are named in the allowlist with their reason (campaign-
registered, not a package hook), and the ratchet will demand their removal
the day they resolve. Worth a rule: re-run a PR's checks if `main` has moved
under it since they last ran, before merging.

## 2026-09-08, TERMS-Bench first live pilot (#92)

The first live path for a family whose counterpart is not a model. The
kernel gained a scripted-seat capability for it (#150,
`docs/kernel_scripted_seats_design.md`); the family's live setup, campaign
and publisher were built against it offline, every corpus case run through
the real kernel with a fake route, before any provider call.

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| TB-D-01 | a receipt with a scripted seat could be sealed and replayed but not read back: the research layer's `_deserialize_receipt` did not know `scripted_seats`, rebuilt the receipt with the empty default, and `verify_evaluation_receipt` rejected the digest; the same gap sat in `_deserialize_run_plan` for cells, and the research report's permitted-seat check named only model seats | the family publisher's test, on the first genuine receipt it projected -- offline, before any spend | none; found before the canary | fixed in #150 (`fe8cdd6d`): the research layer reads `scripted_seats` on receipts and cells, defaulting when absent so older receipts read unchanged; `receipt_projection` publishes which seats were not models; round-trip test added |
| TB-D-02 | the live harness typed a model answer that was not a JSON object as a non-retryable `malformed_structured_output` route fault, which the kernel wraps as `SchedulerContractError` and the campaign as an operational abort. The kernel's OpenRouter client deliberately keeps a completed, billable non-JSON answer on the normal response path "so the family parser can classify malformed model output as agent behavior", and this family defines a malformed move as a measured `agreement_violation` (`malformed_action_schema`, receipt `invalid_measurement`, spec golden 4). The harness pre-empted both -- the same mistake its own docstring warned against, one level up | attempt_001 of the v1 pilot aborting at case 8/30 | $0.0052 on the case, 22 cases never run, a campaign identity | fixed in v2 (`live.py` harness 1.1): the text reaches the family unchanged; `campaign.py` seals a failed cell as a typed exclusion (`finalize_family_failure`) and continues, aborting only outside a cell |
| TB-D-03 | the kernel's two chat clients type a truncated structured response differently: the Arena client raises `length` (retryable, budget growth) when `finish_reason == "length"` and the JSON does not parse; the OpenRouter client returns the truncated text as a completed answer, and `ModelTurn` carries no `finish_reason`, so a harness cannot tell truncation from a finished malformed answer. On this route the difference decides whether a degenerate answer is retried or measured | reading the sealed provider result of TB-O-01 (`finish_reason: length`, 4000 output tokens) | none beyond TB-O-01 | open; filed as #152 rather than changed under the scripted-seat PR (one concern per kernel PR) |

### O — Operational failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| TB-O-01 | `termsbench_glm53_flash_parasail_pilot_v1`, attempt_001: canary admitted (358 in / 29 out, $0.00007), cases 0–6 complete and replayed (1.1–8.4 s each, ≤ $0.0005), then case 7 (`termsbench.candid.nodeal.1010055`, buyer r=56.66 against a seller opening at 151.65) aborted the campaign: on its fifth agent turn GLM 5.3 Flash at temperature 0 wrote `{"decision": "offer", "price": 56.5993352745860345659335…` and repeated the digits of the price until the 4,000-token output ceiling (`finish_reason: length`, 26 reasoning tokens, $0.0021 for the call); the harness typed it `malformed_structured_output` (TB-D-02). First hypothesis on reading the checkpoint -- "the route returned prose" -- was wrong: it was a decoding degeneration inside a number. The checkpoint records `execution_failure`, as every `SchedulerContractError` does; the typed condition is in the sealed ledger | the campaign's own abort; the cause from the sealed provider result | $0.0074 total across the attempt; 22 of 30 cases never run; the v1 identity | the attempt root stays sealed as evidence (Tier 1 row 1); v2 identity with the TB-D-02 fix ran 30/30 complete, $0.029, 5.6 min, and on the same case at temperature 0 the degeneration did not recur (`counterpart_walk_away`, 5 rounds) -- the route is not deterministic at temperature 0, so a v1 rerun would have been evidence of nothing; the model's degeneration is a measured outcome in v2's design, not an abort |

### T — Tooling and process failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| TB-T-01 | #150 pushed as ready with "full suite green locally" (2,477 passed) and CI failed at collection on Python 3.10: `mutable default <class 'mappingproxy'> for field scripted_seats is not allowed: use default_factory`. The local venv is 3.13, where `mappingproxy` is hashable and `dataclasses` accepts it as a plain default; on 3.10/3.11 it is unhashable and rejected. The plain default was chosen deliberately, because the omit-if-default rule compared against `field.default` and a factory field has none. First reading of the red check -- "kernel-review, no approval yet" -- was right for one job and hid the other | CI (`agenticpay-fidelity`, then `test (3.10)`) | two red checks on a PR just marked ready; one CI cycle | factory defaults on `RunSpec`, `PlanCell` and `EvaluationReceipt`, and a `field_default` helper the omit rule (both digest paths) looks through; reproduced and re-run under a 3.10 venv before the next push. Rule: a local gate on one interpreter is not the CI matrix; run the touched tests under 3.10 too when a dataclass default changes |
| TB-T-02 | `gh pr edit 150 --body-file … && gh pr ready 150` exited non-zero on a GraphQL warning (`Projects (classic) is being deprecated … projectCards`) after applying only the title, so the chained `gh pr ready` never ran and the reviewer request failed the same way; the PR sat as a draft with the stale "implementation is not written yet" body while the push comment said it was ready. Noticed only because the follow-up `gh pr view` was read | a person read `gh pr view` output | none beyond confusion on the PR | `gh api -X PATCH repos/…/pulls/N` and `gh api … /requested_reviewers` for edits; never chain state changes behind a `gh pr edit` without checking its exit |
| TB-T-03 | in zsh, `git show $B:src/aeread_families/tau3_retail/campaign.py` expanded `$B:s…` as a history modifier and produced `origin/codex/tau3-first-live-campaignetail/campaign.py` -- twice in one session, the second time on `$T:src/…` after the first was diagnosed | the commands' own errors | two wasted reads | `"${B}:path"` always; the P-T-02/P-T-05 zsh rows now have a third sibling |
| TB-T-04 | the Tier 1 register built from the family worktree emitted `source_artifact` as absolute paths (the sealed runs live under the live checkout, not the worktree), and the prohibited-text scan refused the table on `/users/` | `assert_public_payload` at publish | one failed build | `failure_register.py --repository-root`; the scan doing its job is why this row exists rather than an absolute path in a committed register |
| TB-T-05 | merging `main` (#109, #112) into #150: `git checkout --theirs` on the two conflicting kernel files, then re-applying this branch's hunks by script, silently dropped three statement-level hunks (the research report's permitted-seat union, the cell deserializer's `scripted_seats`, and the receipt's `__post_init__` validation of scripted seats) while a weaker re-typed `__post_init__` took the original's place. The bound-names superset check passed on both files -- it sees module-level names, not statements -- and 471 tests passed, because no test covered the permitted-seat union | reading every removed line of `git diff <parent>` for each parent before committing the merge | none; caught before the merge commit | the three hunks restored from the pre-merge head byte-for-byte; the rule gains a step: after the bound-names check, read the removed lines of the resolved file against *each* parent, and treat any removed non-comment line the other parent did not remove as a dropped hunk |

## 2026-09-09 — tooling: a rebase raced a merge by two minutes

#132 rebased onto `main` at 04:21Z and reported "rebased onto the current
main after its kernel contract updates"; #112 had merged at 04:19Z as
`2318d748`. The rebase base was `b37c3d0d`, one commit behind, so the
branch carried #112's R13 code as it stood on #112's branch, not as merged:
`git merge-tree` against `main` shows a single-line conflict in
`task/evaluation.py` (`_reject_undeclared_inapplicable_ids(registration.manifest, …)`
on `main`, the pre-merge `(family, …)` on the branch) and the usual union
in `tests/test_shared_runner_scoring_contract.py`. GitHub runs no workflow on
a conflicting PR, so the Python 3.12 fix pushed in the same rebase has not
been exercised by CI either.

Not a design defect in either PR, and a kernel-file conflict is a stop rather
than a hand-resolve, so it was reported on #132 with the target commit. It is
the same gap the 2026-09-08 row above names from the other side: a check, or
a rebase, is evaluated against `main` *at that moment*. Rule to add to the
one there: read `main`'s head from `git ls-remote` immediately before the
rebase, and put that commit in the rebase comment, so "current main" is a
digest and not a claim.

## 2026-09-10 — design: two declared reasoning conditions that both turn reasoning off

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| R-D-01 | every live panel this repository has published on GLM 5.3 Flash/Parasail declared a reasoning condition that suppresses reasoning, and none of them says so. One call per condition on the same prompt (2026-09-10): `reasoning.max_tokens: 1500` → 13 reasoning tokens; `reasoning.max_tokens: 8000` → 13; `reasoning.effort: "low"` → 13; **no reasoning block at all → 259**. The cap is a switch, not a budget, and the two settings we use (`reasoning_capped_1500_v1` for econevals and TERMS-Bench, `reasoning_low_v1` for govsim) are the same behaviour under different names. `docs/research/reasoning_condition_and_diagnostics.md` already requires the condition to be declared and versioned; what it could not require is that the declared name describe what the route does with it | asking why TERMS-Bench pilot v2's 43% critical-violation rate sat twenty times above the paper's 0–2.06% band for thirteen deliberating agents | no run invalidated -- every panel measured a real, declared configuration -- but `econevals_glm53_flash_parasail_panel_v10`, `govsim_glm53_flash_parasail_first_light_v1` and `govsim_glm53_flash_parasail_dialogue_v3` all measure a **non-deliberating** GLM 5.3 Flash and must be read that way, and no published number of ours is a like-for-like against a paper table until the deliberating arm is run | `termsbench/live.py` names both measured conditions (`reasoning_capped_1500_v1`, `reasoning_unconstrained_v1`) and puts the condition in the profile id, so a panel cannot silently change which agent it measured; TERMS-Bench pilot v3 runs the deliberating arm as its own identity. The same arm is owed for econevals and govsim. Open |

## 2026-09-10 — design: receipt compatibility accepted altered JSON and unreadable writes (#151)

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| PR151-D-01 | the transitional digest candidate coerced five falsy JSON values to `[]`; the idempotent writer accepted pretty-printed bytes that its reader rejected | independent review, then seven failing regression cases before the production fix | no provider spend; digest verification accepted altered field bytes and publication could report success over unreadable receipts | exact absent-or-empty-list compatibility and shared read-back validation implemented; 188 focused checks pass |
