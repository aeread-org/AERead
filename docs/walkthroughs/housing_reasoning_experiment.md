# Walkthrough: Housing reasoning-condition experiment

**Entry point**: The measurement-layer paper needs a statistically valid comparison of
Housing action trajectories with reasoning disabled versus low reasoning.

**Action**: Run 100 independently generated Housing worlds, paired across two
DeepSeek reasoning conditions, with three nested model replicates per world: 600 total
trajectories.

**Current status (2026-08-27)**: complete. A fresh six-trajectory route admission passed,
all 600 predeclared sample cells terminated, and all 606 admission and sample receipts were
verified on a zero-provider-call resume. The primary result is conditional on the pinned
synthetic generator, DeepSeek revision, Parasail FP8 route, and controlled landlord; earlier
pilots and the historical R4 smoke remain excluded.

**Files involved**: `src/aeread/shared_runner/housing.py`,
`src/aeread/shared_runner/housing_experiment.py`,
`src/aeread/shared_runner/execution.py`, the resulting sealed plans, per-cell evidence,
and the final cluster-level analysis artifact.

## Confirmatory result (2026-08-27)

The three-world admission completed in both arms, paired inference seeds exactly, returned
zero control reasoning tokens, and resolved every call to
`deepseek/deepseek-v4-flash-20260731` on Parasail FP8 without fallback. The full sample then
terminated all 600 planned trajectories. Of those, 580 produced included
`state_and_score` receipts and 20 reasoning-low trajectories produced excluded
`invalid_measurement` receipts. No control trajectory failed.

The predeclared complete-pair analysis retained 83 worlds with all three valid replicates in
both arms:

| primary quantity | result |
|---|---:|
| reasoning-none mean score | 0.6671 |
| reasoning-low mean score | 0.8256 |
| mean paired difference, low minus none | **+0.1585** |
| 10,000-draw world-cluster bootstrap 95% interval | **[0.1294, 0.1882]** |
| paired-t diagnostic 95% interval | [0.1284, 0.1885] |
| paired-difference SD / standardized effect | 0.1378 / 1.1498 |
| exact-support missingness bounds over all 100 worlds | **[0.0992, 0.1787]** |

The exact-support sensitivity result keeps every observed replicate and assigns only missing
replicates their worst legal arm-specific outcomes. Its positive lower bound means the
direction does not depend on complete-pair exclusion under that declared support. However,
83 complete clusters is below the original 90-cluster retention target used to plan power
for `d=0.3`; the observed effect is much larger, but that does not erase the reliability
shortfall.

| operational quantity | reasoning none | reasoning low |
|---|---:|---:|
| completed / planned trajectories | 300 / 300 | 280 / 300 |
| pass-all-three worlds | 100 | 83 |
| reasoning tokens | 0 | 5,845,217 |
| cells with a length retry | 0 | 141 |
| total length retries | 0 | 178 |
| known recorded cost | $0.4262 | $1.8465 |

The 20 low-arm failures were 9 length exhaustions, 8 cost-budget exceedances, and 3
timeouts. Total known recorded admission-plus-sample cost was `$2.2912410906`; the actual
provider charge may be higher because the three timeout calls have unknown billing.

On the 83-world matched panel, the naive baseline mean was 0.8326. Reasoning-low nearly
matched it at 0.8256 (difference -0.0070) and reached or exceeded it on 59.8% of
trajectories, versus 16.9% for reasoning-none. It also reduced trajectories with an
individual-rationality violation from 120/249 to 12/249. The tradeoff was distributional:
tenant capture fell from 83.1% to 70.3%, landlord capture rose from 16.9% to 29.7%, and mean
wasted contacts rose from 5.76 to 6.20. These decompositions are descriptive, not additional
confirmatory tests.

The first analysis attempt exposed a contract bug rather than an invalid trajectory: two
completed control runs produced legal negative welfare and therefore negative scores. `L=0`
is a feasible lower bound on the *optimum*, not a floor on every realized outcome. Tests were
written to fail first, then the analyzer was corrected to accept finite scores at or below
one, derive exact per-world legal lower support, and bound only missing replicates. The
corrected analysis reused the sealed receipts without rerunning or replacing any cell.

The compact, hash-bound result is
[`housing_reasoning_parasail_v12_summary_2026-08-27.json`](../evidence/housing_reasoning_parasail_v12_summary_2026-08-27.json).
Raw prompts, responses, events, artifacts, and receipts remain in the gitignored local archive
named there; they are not committed because it contains 103,207 files and is 582 MB.

---

## Step 1: Data source

The experimental population is explicitly conditional on `housing_generator_v1/1.0.0`
with six tenants, four listings, four rounds, bid-world values, and common weight `0.6`.
It is not a sample of real housing markets. The panel contains 100 unique world seeds
selected before outcomes by SHA-256 counter derivation from master seed `20260826`.

The P0 scripted policies were regenerated on 300 seeds. Their within-arm efficiency
standard deviations were approximately `0.096` and `0.100`, but those values are only
planning proxies: the relevant power input is the standard deviation of paired live-model
world differences. The completed panel measured it as `0.137805`, but that post-outcome value
was not used to alter the design. All route and robustness admissions are
instrumentation evidence and contribute no outcome observations to this study.

Power planning uses a two-sided paired comparison at alpha `0.05`, 80% power, and one
primary contrast. Exact paired-t planning requires 90 clusters for standardized effect
`d=0.3`, 52 for `d=0.4`, and 34 for `d=0.5`; 100 clusters therefore targets modest-to-
moderate paired effects without treating the 600 trajectories as independent.

### DANGER ZONE D1: trajectories are nested, not independent

**CRITICAL — biases toward false precision and significance.** The independent sampling
unit is the generated world seed. The three stochastic runs and every phase, seat, call,
offer, and hold within a world are nested observations. Primary uncertainty must resample
100 world clusters, never 600 trajectories or thousands of decisions.

### DANGER ZONE D2: synthetic-population scope

**HIGH — biases toward overgeneralizing capability.** Random seed selection supports an
estimand over the pinned generator only. It does not justify claims about real housing,
other market sizes, other mechanisms, or housing reasoning universally.

## Step 2: Assumptions

| Input | Value | Provenance |
|---|---:|---|
| World clusters | 100 | power-planning judgment, fixed before outcomes |
| Admission clusters | 3 disjoint worlds | out-of-panel robustness gate |
| Conditions | `reasoning_none_v1`, `reasoning_low_v1` | experimental contrast |
| Replicates per world and condition | 3 | robustness judgment; nested, not added to cluster N |
| Tenants / listings / rounds | 6 / 4 / 4 | pinned P0 Housing configuration |
| Model | `deepseek/deepseek-v4-flash-0731` | fixed model listing |
| Canonical endpoint | `deepseek/deepseek-v4-flash-20260731` | pinned Parasail route |
| Quantization | `fp8` | live OpenRouter endpoint metadata captured 2026-08-26 |
| Temperature / top-p | 0 / 1 | fixed controls |
| Inference seeds | paired SHA-256 derivation from world and replicate | deterministic design |
| Primary estimand | mean world-level difference in within-case score, low minus none | analyst declaration |
| Primary resampling | paired world-cluster bootstrap, 10,000 draws, seed `20260826` | analysis declaration |
| Global spend stop | `$6.00` recorded cost | safety boundary |

The reasoning-disabled arm sends `reasoning.effort: "none"`; the low arm sends
`reasoning.effort: "low"`. OpenRouter's 2026-08-26 model metadata marks reasoning as
non-mandatory for this listing, and its documentation defines `none` as disabled. A live
admission pair must additionally show zero reasoning tokens and no reasoning text for the
disabled arm before the 600-cell run is released.

### DANGER ZONE D3: a nominal off switch may not disable provider reasoning

**CRITICAL — biases the contrast toward an undefined treatment.** Gateway acceptance is
not enough. If the admission response for `none` reports reasoning tokens or reasoning
content, the batch stops. Excluding returned reasoning text is not equivalent to disabling
reasoning and must not be used as the control.

### DANGER ZONE D4: model and route drift

**HIGH — bias direction unknown.** A marketplace alias, provider fallback, quantization
change, or price change could alter one part of the run. Every confirmatory call must resolve
to the pinned Parasail FP8 endpoint at routing attempt one, with no fallback; drift
blocks new cells. Earlier DeepInfra FP8 pilot cells are a separate infrastructure condition
and cannot be pooled with the Parasail panel.

## Step 3: model and analysis

For world `w`, condition `c`, and replicate `r`, the runner records within-case score
`S[w,c,r] = (R-L)/(U-L)` when `U>L`, plus native welfare, tenant and landlord payoffs,
IR violations, wasted contacts, actions, retries, usage, and cost. The primary world value
is the mean of all three valid replicates:

```text
M[w,c] = mean_r S[w,c,r]
D[w]   = M[w,reasoning_low_v1] - M[w,reasoning_none_v1]
Delta  = mean_w D[w]
```

The primary analysis includes only worlds with all three operationally complete, valid
replicates in both conditions. Agent actions that are malformed after declared action retries
remain family-typed passes and are valid economic outcomes. Provider, harness, or evidence
failures are operational missingness, are never silently replaced, and are reported by arm.
No world is replaced after outcomes are observed.

Every completed trajectory must carry an `included` `EvaluationReceipt` whose replay level is
`state_and_score`. Every reconciled operational failure must carry an `excluded`
`invalid_measurement` receipt with no economic score. Analysis reads validated receipts rather
than trusting the compatibility result rows.

The 95% primary interval is the percentile interval from 10,000 paired resamples of world
differences. A paired t interval is reported as a diagnostic. Sensitivity bounds assign the
worst feasible score to missing results in one arm and the best feasible score in the other.
Secondary outcomes and reasoning diagnostics are descriptive; there is no unreported family
of hypothesis tests.

### DANGER ZONE D5: informative operational missingness

**HIGH — can bias toward the more reliable arm.** Reasoning-low may hit token ceilings more
often, while disabled reasoning may produce different schema failures. Complete-pair analysis
alone can select easier worlds. Arm-specific missingness, retry rates, worst-case bounds, and
pass-all-three rates are mandatory alongside the complete-pair estimate.

### DANGER ZONE D6: output limits are part of the realized treatment

**MEDIUM — may bias against reasoning-low through truncation.** Both arms receive the same
initial 4,096-token output limit and one declared length retry at 8,192. Earlier live probes
showed that reasoning-low could exhaust 512, 1,024, 2,048, and 4,096 ceilings before emitting
an action, while reasoning-none completed. Those failed probes remain preserved as
operational evidence and are not part of the analysis sample. Different truncation rates are
a real consequence of the revised configured condition and must be reported, not hidden by
unbounded post hoc retries.

The same admission sequence also showed that a 30-second provider deadline could expire in
the reasoning-low arm. Both arms therefore use a symmetric 120-second per-call deadline.
Phases declared simultaneous dispatch their already-frozen actor observations concurrently;
results remain ordered by the sealed actor order before the family transition is applied.

A subsequent infrastructure pilot established that OpenRouter's shared DeepInfra pool can
return transient upstream 429/5xx failures under sustained load. The final RunPlan therefore
allows four total action attempts, but still permits at most one length retry. Zero-result
`rate_limit` and `provider_5xx` failures receive evidenced exponential backoff with
deterministic jitter; timeout and transport failures remain non-retryable because their
billing/outcome may be unknown. These reliability retries are identical across arms.

The pre-backoff v3 run is an infrastructure pilot, not part of the confirmatory panel. It
sealed 91 sample trajectories before the capacity gate stopped: 70 completed and 21 were
operational failures (16 reasoning-low, 5 reasoning-none). Its economic outcomes must not be
pooled with or used to select the final RunPlan. This classification was made from typed
operational failures before a complete six-trajectory world cluster—and therefore before any
paired economic estimate—was available.

On 2026-08-26, live OpenRouter endpoint metadata identified several routes for the same
canonical DeepSeek revision with `reasoning_effort`, `seed`, `response_format`, and
structured-output support. Fresh full-dimension gates rejected OpenInference because five of
six simultaneous low-arm calls timed out, then rejected AkashML and Inceptron because at
least one low-arm action exhausted both the 2,048-token ceiling and its single 4,096-token
length retry. Each control arm completed with zero reasoning tokens; none of these gates
released sample cells.

Parasail then passed the same gate with both trajectories complete, identical paired seeds,
zero control reasoning tokens, 19,273 low-arm reasoning tokens, the exact canonical model,
and no fallback. The confirmatory RunPlan is therefore pinned to Parasail FP8 with price
ceilings of $0.14/M prompt tokens and $0.28/M completion tokens. This is a new route, not a
recovery of any earlier RunPlan, and only its post-admission sample cells may enter the
confirmatory panel.

That one-world gate was not sufficiently predictive. The first post-gate Parasail attempt was
paused and classified as an infrastructure pilot before any complete six-trajectory world or
paired economic estimate existed. It sealed 13 trajectories: 8 completed and 5 operational
failures, all five in the low arm; 587 cells were never started. The sample portion cost
$0.0505768032. The failure pattern showed that successful controls could reset the original
global consecutive-failure circuit and mask repeated low-arm length exhaustion.

The eventual confirmatory panel therefore required pass-all completion
on three fixed worlds drawn from a seed panel disjoint from the 100 analysis worlds. Both arms
received 4,096 tokens initially and one 8,192-token length retry, and the operational
failure circuit counts consecutive failures separately within each arm. These changes are
declared from typed operational evidence only; no complete world-level economic contrast was
available or inspected.

### DANGER ZONE D7: controlled counterpart limits the estimand

**MEDIUM — biases toward cleaner, less interactive behavior.** The landlord is deterministic
and local in both arms. This isolates tenant reasoning but does not establish performance with
strategic or stochastic counterparties.

## Step 4: result and decomposition contract

The experiment had no result until all released cells terminated or the declared spend/safety
boundary stopped new work. All 600 released cells terminated, with no outcome-based early
stopping. The report decomposes:

1. primary mean paired score difference and cluster interval;
2. world-level distribution and per-condition means;
3. pass-all-three, operational missingness, schema failure, and length-retry rates;
4. welfare, each side's payoff capture, IR violations, and wasted contacts;
5. action divergence by phase and seat on matched observations;
6. reasoning tokens and diagnostic failure taxonomy, never raw reasoning quality as a primary
   score;
7. recorded versus pinned-price cost reconciliation and route coverage.

### DANGER ZONE D8: a clean aggregate can hide mechanism failures

**HIGH — biases toward a single flattering score.** Equal welfare can coexist with different
rent capture, IR failures, wasted contacts, or fragile pass-all behavior. The decomposition is
part of the result rather than an optional appendix.

---

## Danger zones summary

| # | Step | Risk | Severity | Bias direction |
|---|---|---|---|---|
| D1 | Data | Treating nested trajectories as independent | CRITICAL | Toward false precision |
| D2 | Data | Synthetic generator overgeneralization | HIGH | Toward universal claims |
| D3 | Assumptions | Provider does not honor reasoning off | CRITICAL | Toward undefined contrast |
| D4 | Assumptions | Route/model drift | HIGH | Unknown |
| D5 | Analysis | Informative missingness | HIGH | Toward reliable/easier arm |
| D6 | Analysis | Shared output ceiling truncates arms differently | MEDIUM | Potentially against reasoning-low |
| D7 | Analysis | Deterministic landlord | MEDIUM | Toward cleaner interaction |
| D8 | Results | Aggregate hides distribution and failures | HIGH | Toward flattering summary |

## Load-bearing assumptions

1. `reasoning.effort: "none"` is demonstrated, not merely documented, to disable reasoning
   on the pinned endpoint, and all three out-of-panel admission pairs complete.
2. One hundred preselected world seeds are independent draws from the pinned generator, and
   the paired world-difference variance is small enough for the intended effect size.
3. Operational missingness is low and sufficiently balanced that complete-pair and worst-case
   sensitivity conclusions do not conflict.

## Invariants

1. The exact same world and inference seeds, prompt, output schemas, landlord policy, limits,
   model revision, and route are used in both conditions.
2. Exactly three planned replicates are retained per world and condition; no outcome-based
   replacement or optional stopping is allowed.
3. Every external call has canonical evidence, explicit attempt ownership, usage, cost, and
   route verification; unverified cells are not scored.
4. Primary uncertainty resamples world clusters and the report states `N=100` clusters and
   `600` nested trajectories separately.
5. Conclusions are limited to the pinned Housing generator and controlled-landlord condition.

## Honest one-sentence version

On the pinned generated Housing worlds with a controlled landlord and Parasail-hosted
DeepSeek V4 Flash, low reasoning increased the average within-case score by 0.1585; this does
not establish a universal benefit of reasoning, real-market performance, saturation, or a
universal measure of housing competence.
