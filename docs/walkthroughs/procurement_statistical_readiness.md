# Walkthrough: Procurement statistical-run readiness

**Date:** 2026-08-27.
**Entry point:** Whether procurement is ready for a minimal statistically defensible run,
and whether Housing's 600-trajectory design should be reused.
**Proposed action:** Do not release a confirmatory batch yet. Repair and validate the
variable-world reference, establish the intended world distribution, and port the current
receipt/batch/analysis contracts before choosing and sealing the comparison.

This initial audit was not an experiment or authorization to spend. No live calls
were made during it. The pre-fix findings below are historical, at `fb60bbc`;
the approved implementation follow-up is described separately.

**Implementation follow-up:** After approval to address the gaps, the reference was
corrected to optimize purchase spend and contact charges jointly, respect the contact
limit, and retain no trade. Four new regression cases failed before the fix; all 15
procurement tests then passed. The findings below preserve the pre-fix audit at `fb60bbc`.
The follow-up at `261a15c` also adds a coupled-world generator, typed objective-reference
scoring, the shared Housing-derived receipt/replay path, shared paired analysis, and a
paired batch with explicit live-admission and spend gates. See
[`procurement_panel_preflight.md`](procurement_panel_preflight.md) for validation and the
remaining live decision. The sections below retain the original pre-fix findings rather
than silently rewriting the audit history.

## Step 1: Data sources

Audited procurement implementation: `fb60bbc`, in this worktree. Audited Housing
implementation: `043cb2c`, in `/private/tmp/aeread-pr7-verifier-map.2JwoTi`.

- Housing's `docs/walkthroughs/housing_reasoning_experiment.md` and committed evidence
  summary define **100 worlds x 2 reasoning conditions x 3 replicates = 600 trajectories**.
  Its admission panel is separate: three additional worlds x two conditions = six episodes.
  Of the sample, 580 episodes were included and 20 were operational exclusions; only
  **83 worlds** had all six valid episodes, below the planned retention target of 90.
- Procurement's `build_procurement_rfq_smoke` loads one curated electronics JSON,
  sets `world_seed=0`, uses one replicate, and declares `uncertainty="none"`.
- The successful Gemini smoke has four live buyer calls and eight local supplier actions.
  Buyer surplus is 590, baseline 728.6, and the fixture-specific upper bound 796. Its
  estimated API cost is $0.01016025. One world does not estimate between-world variance.
- An offline diagnostic of the existing random generator on seeds 0--29 completed all
  30 scripted baselines. None had an off-list vendor, late vendor, or component requiring a
  split because every individual supplier lacked sufficient capacity. The baseline score
  mean was 0.954176, SD 0.036873, and range [0.791262, 0.972965]. These are generator
  diagnostics, not live-model observations or a power calibration.

The generator currently makes every vendor approved, all lead times no greater than the
deadline, and a full-capacity alternative for each component. Its comment about a forced
first-component split is not enforced by those capacities. This defines a narrower,
easier population than the curated fixture's coupled procurement constraints.

### DANGER ZONE D1: repeating one case is not population sampling

**CRITICAL — biases toward false precision and broad capability claims.** Six hundred
repeats of the existing smoke still supply only one world cluster. They can measure
conditional repeatability, not performance across procurement worlds. There is currently
no basis for estimating a procurement-wide standard error from the live smoke.

## Step 2: Assumptions and planning inputs

| Input | Status / provenance |
|---|---|
| Primary contrast | Not yet selected: Gemini versus a fixed scripted baseline, or two live-model conditions |
| Primary endpoint | Must be frozen; normalized buyer surplus is comparable across scales only after its reference is valid |
| 100 independent worlds | Housing-derived planning choice, not a universal statistical minimum |
| Three repeats per world/condition | Housing's robustness choice; not three extra independent worlds |
| Alpha 0.05, power 0.80 | Planning choices for one two-sided paired comparison |
| Target standardized effect d=0.3 | Housing's modest-effect assumption, not estimated for procurement |
| 90% complete-cluster retention | Original Housing planning assumption; observed Housing retention was 83% |
| Gemini low thinking | Only currently implemented procurement condition; a second condition needs explicit selection and admission |
| API price/cost projection | Pinned rates applied to one smoke's usage; not a billing guarantee or calibrated batch estimate |

### DANGER ZONE D2: inherited assumptions are not procurement evidence

**HIGH — can understate required sample size or overstate generalization.** Housing's
effect size, reliability, and generator variance do not transfer automatically. The
offline scripted SD above is not the SD of paired live-model world differences.

## Step 3: Reference and analysis model

For world w, condition c, repeat r, the intended normalized score is S[w,c,r]=R[w,c,r]/U[w]
when U[w]>0. A paired analysis first averages repeats within a world, then forms D[w]
between conditions. Its estimate is the mean of D[w]; its bootstrap resamples whole worlds.
A deterministic baseline supplies one fixed B[w] per world, not another set of paid calls.

The current upper-bound implementation in `src/aeread/procurement_rfq_env.py:236` first
minimizes purchase spend and then subtracts the contact fees of that allocation. Minimizing
purchase spend alone does not maximize buyer surplus when vendor contacts have fixed costs.

### DANGER ZONE D3: confirmed upper-bound counterexample

**CRITICAL — biases normalized performance upward and invalidates the claimed bound.**
An executable local counterexample used one component, demand 100, contract value 2000,
budget 1600, two approved on-time vendors, MOQ 1, and contact cost 5:

| Vendor | Private unit cost | Capacity | Controlled supplier floor |
|---|---:|---:|---:|
| 2 | 10.00 | 50 | 10.50 |
| 3 | 10.01 | 100 | 10.52 |

The present reference selects 50 units from each: spend 1051, two contacts costing 10,
and a reported U=2000-1051-10=939. A legal RFQ, quote, counter, approval, and award using
only vendor 3 spends 1052 with one contact costing 5: realized R=943, no violations,
and a reported score of 1.004260. Thus a feasible realized outcome exceeds the claimed U.

The original electronics smoke was checked separately by enumerating supplier subsets of
size at most five and solving each floor-priced allocation: its best net bound remains
796, using vendors 2, 3, 5, and 7. The new counterexample does not invalidate that smoke's
recorded native economics or its fixture-specific reference.

Before expansion, optimize contact costs jointly with allocation, or use a demonstrably
valid relaxation; account for contact limits and zero/negative headroom. Verify reference
support on generated worlds. Do not assume realized scores lie in [0,1]: walking away
after contacts has negative buyer surplus, even though no action bounds the optimum at zero.

### DANGER ZONE D4: current execution evidence is not Housing's final receipt pipeline

**HIGH — biases toward admitting incomplete or selectively retained measurements.**
The procurement branch predates Housing's typed measurement leaf, state-and-score replay
receipts, no-call resume, atomic per-cell results, orphan recovery, global cost stop,
failure circuit, paired inference seeds, and cluster-level missingness analysis.
It has a useful event-chain audit, but no equivalent procurement batch finalization yet.
Port and test the relevant shared infrastructure; do not overwrite unrelated Housing work.

## Step 4: Sample-size results and sensitivity

Independent paired-t planning was recomputed using `statsmodels.stats.power.TTestPower`,
two-sided alpha 0.05 and power 0.80. The standardized effect is the mean world difference
divided by its SD, after any within-world averaging. These are model-based planning
benchmarks, not a guarantee for a bootstrap test or non-random operational missingness.

| Target d | Complete worlds required | Enroll at 90% retention | Enroll at 83% retention |
|---|---:|---:|---:|
| 0.3 | 90 | 100 | 109 |
| 0.4 | 52 | 58 | 63 |
| 0.5 | 34 | 38 | 41 |

Varying Housing's 100 complete-world target by minus/plus 50% gives detectable effects
approximately 0.404 at 50 worlds, 0.283 at 100, and 0.230 at 150. This confirms that the
load-bearing input is the number of independent worlds and the target effect, not the
raw trajectory total. Increasing repeats can reduce within-world noise but cannot create
new independent worlds. One repeat per world is not inherently statistically invalid;
three is a robustness choice whose value depends on the variance decomposition.

Keeping Housing's 100-world, three-repeat convention gives these conditional designs:

| Comparison | Live procurement episodes | Additional reference work |
|---|---:|---|
| One Gemini condition versus deterministic baseline | 300 | Baseline once per world, locally |
| Two live-model conditions | 600 | Same worlds, three paired repeats per condition |

Admission/variance pilots must use disjoint worlds and stay outside the confirmatory
sample. Choose the endpoint, contrast, generator, inference seeds, missingness rule,
and stopping policy before inspecting confirmatory outcomes. Do not top up an observed
panel until its confidence interval becomes significant.

The one-smoke cost extrapolation is $3.048075 for 300 equally costly episodes and
$6.09615 for 600. This is not an approved spending cap or a reliable estimate for another
reasoning condition: world complexity, thinking usage, retries, and unknown timeout billing
can change costs. The current $0.02 profile check occurs after calls and is not a hard
provider-side spending ceiling. A separate global batch budget is required.

### DANGER ZONE D5: attrition and after-the-fact sample expansion

**HIGH — biases toward easy worlds and false positive conclusions.** Housing retained only
83/100 complete clusters despite 580/600 included episodes. Procurement must report both
counts, distinguish operational missingness from legal poor actions, preserve failed cells,
and include sensitivity analysis using valid case-specific outcome support.

## Danger zones summary

| Risk | Severity | Bias direction |
|---|---|---|
| One fixed world treated as hundreds of independent samples | Critical | False precision and overgeneralization |
| Uncalibrated generator, variance, effect, or retention assumptions | High | Underpowered or overly broad claims |
| Purchase-only optimization mislabeled as net-surplus upper bound | Critical | Inflated normalized scores |
| Missing receipt/replay/resume/batch controls | High | Selective inclusion and unreconciled measurements |
| Informative attrition or significance-driven sample expansion | High | Easier-world selection and false positives |

## Load-bearing assumptions

1. The frozen world generator actually represents the intended procurement decisions.
2. Reference values and outcome support remain valid for every admitted world.
3. The chosen effect/precision target and cluster retention justify the predeclared sample.

## Invariants and next gate

- Preserve the completed smoke and exclude it and generator/admission diagnostics from the
  confirmatory sample; do not retrospectively call them preregistered observations.
- Validate bounds, feasible baselines, privacy, approval binding, and negative outcomes
  before sealing generated cases.
- Keep controlled suppliers identical across model conditions and record native payoffs,
  disclosure, violations, operational exclusions, model identity, usage, and cost.
- Require verified state-and-score receipts, safe no-call resume, a global budget, and a
  declared failure circuit before unattended execution.
- Freeze one primary comparison and infer at the world-cluster level.

**Honest conclusion:** Procurement is ready for further instrumentation and reference
validation, not for releasing a confirmatory 600-episode batch. Housing's design can be
reused after these gates, but 600 is a two-condition design choice, not statistical validity
by itself. Selecting the comparison and implementing the fixes are the next work items.
