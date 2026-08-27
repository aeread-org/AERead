# Walkthrough: Housing reasoning-condition experiment

**Entry point**: The measurement-layer paper needs a statistically valid comparison of
Housing action trajectories with reasoning disabled versus low reasoning.

**Proposed action**: Run 100 independently generated Housing worlds, paired across two
DeepSeek reasoning conditions, with three nested model replicates per world: 600 total
trajectories.

**Files involved**: `src/aeread/shared_runner/housing.py`,
`src/aeread/shared_runner/housing_experiment.py`,
`src/aeread/shared_runner/execution.py`, the resulting sealed plans, per-cell evidence,
and the final cluster-level analysis artifact.

---

## Step 1: Data source

The experimental population is explicitly conditional on `housing_generator_v1/1.0.0`
with six tenants, four listings, four rounds, bid-world values, and common weight `0.6`.
It is not a sample of real housing markets. The panel contains 100 unique world seeds
selected before outcomes by SHA-256 counter derivation from master seed `20260826`.

The P0 scripted policies were regenerated on 300 seeds. Their within-arm efficiency
standard deviations were approximately `0.096` and `0.100`, but those values are only
planning proxies: the relevant power input is the standard deviation of paired live-model
world differences, which has not yet been measured. All route and robustness admissions are
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

Before a new confirmatory panel is released, admission therefore requires pass-all completion
on three fixed worlds drawn from a seed panel disjoint from the 100 analysis worlds. Both arms
now receive 4,096 tokens initially and one 8,192-token length retry, and the operational
failure circuit counts consecutive failures separately within each arm. These changes are
declared from typed operational evidence only; no complete world-level economic contrast was
available or inspected.

### DANGER ZONE D7: controlled counterpart limits the estimand

**MEDIUM — biases toward cleaner, less interactive behavior.** The landlord is deterministic
and local in both arms. This isolates tenant reasoning but does not establish performance with
strategic or stochastic counterparties.

## Step 4: result and decomposition contract

The experiment has no result until all released cells terminate or the declared spend/safety
boundary stops new work. There is no outcome-based early stopping. The report must decompose:

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

This experiment can estimate whether low reasoning changes DeepSeek's average Housing outcome
on the pinned generated worlds; it cannot establish a universal benefit of reasoning or a
universal measure of housing competence.
