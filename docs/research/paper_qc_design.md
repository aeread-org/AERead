# Quality control (draft section of the AERead environment paper)

**Status:** working draft, 2026-10-13. It describes the quality-control design as the
[benchmark QC standard](../operations/benchmark_qc.md), the
[campaign SOP](../operations/experiment_campaign_sop.md) and the
[incident log](../operations/incident_log.md) define it, with the newest rule text from
draft PR #288 (sampling plans, reliability, counterpart scope, the A/A arm), and illustrates
each part with what it caught in the three cases of the companion
[case-study section](paper_case_studies.md). Incident row ids (HL-, P-, DC-) refer to the
incident log on the branch of each case.

---

## 6. Quality control

### 6.0 What quality control has to catch

Terminal-Bench 2.0 qualifies a task by asking whether that one task is well specified,
solvable and hard to cheat: an oracle script must pass every test, three reviewers spend
about three hours on it, and an exploit agent tries to pass the tests without doing the work
[TB2]. That is the right check for a fixed instance with a pass-or-fail verdict.

An AERead item is a draw from a generator, scored in dollars against a reference computed
for it, often against a counterpart that adapts. The defects that mattered in our three
cases were properties of the distribution, the information structure, the brief, the
counterpart or the analysis, and every world was individually correct when they were found:

- in Housing's six-tenant market, which tenant signed a sound listing was decided by a
  tie-break on seat number (seat 0 signed one in 59% of cells, seats 1 to 5 in 18% to 35%;
  HL-D-04);
- the rule admitting a Housing world made the favourite listing's quality depend on how
  many tenants shared it (HL-D-03);
- procurement's prompt pointed every subject at the cheapest listing, which was the right
  supplier in half the worlds and the wrong one in the other half, so the pack's two halves
  measured whether an instruction happened to be right (P-D-15);
- in the data-center packs the hidden type moved with public features of the world, so any
  comparison by type across worlds compared the worlds (DC-D-33).

A reviewer reading one world at a time passes all four. AERead's quality control is
therefore built around checks on populations of worlds and on the experiment, and around
recording every failure at the moment it happens.

### 6.1 Two tracks

Quality control runs on two tracks with a deliberate boundary. **Benchmark QC** qualifies
the instrument: the world distribution, the environment and verifier, the construct and the
attribution design, in six gates recorded per family in a QC profile. **Campaign gates**
qualify one experiment on that instrument: `design_contract`, `provider_free_validation`,
`profile_admission`, `full_trajectory`, `variance_pilot`, `confirmatory_freeze`,
`confirmatory_execution` and `publication`, in that order. A green campaign cannot repair a
bad reference, and a qualified family does not make an underpowered or selectively missing
campaign reportable. Each gate ends in one of five typed states (`passed`, `failed`,
`partial`, `not_run`, `not_applicable`), and only `passed` promotes.

**Table 6.1. Benchmark QC gates.**

| Gate | Question | Stops when | In the three cases |
|---|---|---|---|
| 0. Profile | Is there a place to record each gate's verdict? | the family has no QC profile | Procurement's construct check ran and found a public-price rule beating the model by $28.50 a world; with no profile, the verdict was read as a campaign finding and lost |
| 1. Task distribution | Are the worlds valid, distinct, split and informative? | an unverified bound, duplicates across clusters, development and holdout overlap, no measured headroom | Housing v14 admits a seed on the tenant's own structure and reads quality afterwards, holdout from a disjoint seed range; pay-or-test admits on what a buyer can see and draws types afterwards |
| 2. Environment and verifier | Do actions change the intended state, and is every score rebuilt from sealed evidence? | invalid actions mutate state, an oracle disagrees, hidden state leaks, replay differs | 1,800 of 1,800 Housing v14 receipts replay with no provider call; P-D-17 (open): a pre-award check computes kits from true yield, so under sample noise one free action reveals the hidden quality |
| 3. Construct and baselines | Does a better-informed policy do better, and do shortcuts lose? | stronger and weaker policies indistinguishable, a shortcut drives the score | Procurement's shortcut rules give up $45.7 to $146.1 a world against an exact policy that a one-step comparison matches; an earlier data-center baseline was worse than walking away, by $550 (DC profile audit) |
| 4. Attribution and controls | Does the result support the attribution it claims? | an undeclared control changes, the matrix is incomplete, the block cannot carry the claim | the three v14 identities differ only in model and route; data-center claims name their counterparts |
| 5. Confirmatory reliability and publication | Was the comparison sized, frozen and executed without tuning on outcomes? | incomplete pilot, a frozen control changed, selective missingness, a guardrail no behaviour can fail | v14's analysis was declared before any cell; 36 refused cells stayed missing and a fill ran under its own identity |

Changing any bound input reopens the gates downstream of it: a generator change reopens
Gates 1 to 5, a scorer change 2 to 5, a new counterpart 4 and 5, and a change to the
analysis, seeds or sample size after a freeze requires a new campaign identity.

### 6.2 The reference is checked before any model plays

Each case's reference plays the role of Terminal-Bench's oracle script, with one
difference: it also defines the score of every other play, so it must agree with the
environment and not only run. Before a model plays:

- **Procurement.** The best informed policy is tested against the environment's average
  over all 27 ways the newcomers can turn out, and every rule the brief states is checked
  against the environment by a test.
- **Housing.** The offline reference first replays the sealed scripted reference cell for
  cell on the development worlds, 120 of 120 to the cent, before it is used to score anyone.
- **Data center.** A pair of reference players loses nothing on all 58 worlds; a pair that
  signs the draft loses $318k a world over the same 58.

The data-center design adds a check learned from procurement: run the simplest one-step
rule first, and do not run the case if it matches the best policy, because then the case is
arithmetic. Procurement's pay-or-test pack is where it was learned: a one-step comparison
matches that pack's best policy to within $0.06 a world, both frontier agents found the
comparison (§5.3), and the check, had it existed, would have flagged the pack before any model
played.

We also walk one admitted cell by hand, once per family and after any change of mechanism:
the observation the seat received, the text the model returned, the parse, the legality
check, the transition and the sealed score. On an earlier data-center design this found two
design defects in about an hour at no cost, where live panels found defects at $2 to $4 and an hour
each.

### 6.3 Headroom is measured, with a stated miss rate

A pack is informative only if the declared control leaves worlds it can fail. Gate 1
requires running the control itself on every candidate world and rejecting a world on three
grounds tested separately: *trivial* (a deterministic policy reading only public
observations already succeeds), *floored* (the control never succeeds) and *saturated* (it
always does). "The two policies disagree" is not a substitute; it admits a saturated world
whenever a baseline happens to lose there. For a continuous score the grounds become
*degenerate* (the control scores the same at every seed) and *trivial*.

Saturated and floored are claims about a rate, so the number of seeds per world is a
sampling plan with known errors, and the panel manifest states them.

**Table 6.2. How often a screen admits or refuses a world, by seeds per world (control outcome is success or failure).**

| Seeds per world | Rejected when the control succeeds | Admits a world solved 95% of the time | Rejects one solved 50% of the time |
|---:|---|---:|---:|
| 1 | never or always | 0% | 100% |
| 3 | never or always | 14% | 25% |
| 10 | never or always | 40% | 0% |
| 10 | 1 or fewer, or 9 or more | 9% | 2% |

One seed can discard a world but cannot admit one, and under a never-or-always rule more
seeds admit more near-saturated worlds. A shared calculation (`aeread.design.screen_plan`)
produces these rates for any plan; no shared calculation yet covers the dispersion rule for
continuous scores.

### 6.4 Attribution, sizing and reliability

**The unit is the world.** Repeats, seats, turns and calls inside a world are correlated;
uncertainty is computed over worlds, paired across conditions on the same worlds. On the
data-center runs, treating plays as independent made intervals about 1.5 times too narrow,
and more worlds beat more repeats: a $50k gap needs 83 to 91 negotiations an arm at one play
a world against about 160 at three.

**Claims name their counterparts.** When more than one counterpart type is run, the gap is
reported per type and tested for variation before pooling, and a general advantage needs a
positive gap against every declared type. In the data-center case the counterpart accounts
for 25% to 33% of the spread in what a model earns (shuffled labels give 2% or less), and the
gap between the same two agents runs from not distinguishable to $251k (Table 5.5).

**An A/A arm runs through the whole pipeline.** One profile in both arms, through execution,
scoring, analysis and the claim rule; a rule that fires stops the campaign before its freeze.
On the data-center repeat plays, 0 of 48 same-condition comparisons were flagged, and two runs
of one condition on 20 worlds differed by $16k to $25k typically.

**Sizing and reliability are computed and sealed.** The confirmatory number of worlds comes
from the variance pilot's paired world-level spread, a declared minimum meaningful effect, a
target power and an attrition rule, and the calculation is sealed with the freeze. A
comparison also reports its reliability, the expected correlation between the model means of
two independent runs of the same design:

```text
reliability = var_model / (var_model + var_world_model / worlds + var_play / (worlds x plays))
```

A world's own level is not error, because every model meets the same worlds; a counterpart or
seat that the design samples is error, and one it fixes narrows the claim instead.

**Harness settings are tested, not assumed.** Whether a CLI is asked for reasoning summaries
changed nothing detectable in Housing (Opus +17 [−28, +62], Sol +3.5 [−46, +53] on five
selected worlds, 120 episodes, randomised order), a small check whose limits are stated on
its sheet: the worlds were chosen after an earlier result and three plays cannot exclude a
small effect.

### 6.5 Declared tests, and placebo outcomes for looking back

A pattern found by looking back through runs is a hypothesis. To become a result it is
written down first: the claims, measures, exclusions and primary predictions are committed
before the runs, the analysis code before the runs finish, on worlds no model has played,
with the world held fixed and one thing changed, and the primary predictions corrected
together. The data-center signalling test (§5.4) is the worked example: of the two patterns
it declared, one was supported and one was not, and the unsupported one had already been
reported on a result sheet (DC-J-07).

The failed pattern also showed which check catches this kind of error. The look-back
regression had compared hidden types across worlds, and in those packs the hidden type moved
with public features of the world (DC-D-33). A random relabelling of types did not catch it
(0 of 3,000 shuffles reached the observed value), because a permutation null tests
association and a confound is an association. A placebo outcome did: the same regression on
an outcome that cannot depend on the hidden type, the opening price of a scripted integrator
that is never told it, gave 0.38 [0.23, 0.52] where the answer must be 0. Any look-back
analysis by a hidden attribute now runs a placebo outcome first and keeps every reply, not
only those that took a particular action.

### 6.6 A check counts only once it has been seen to fail

A required check is evidence only after it has failed on a counterexample: revert the guard,
confirm the check dies for the intended reason, restore it, confirm it passes, and record the
kill. Three defects fixed on 2026-09-05 had passed every existing suite because the suites
asserted something true by construction. For the same reason a screening loop never catches
an exception: procurement's first two-sided screen called a policy with a positional
argument where the parameter was keyword-only, scored the resulting error as a loss in every
world, and printed a unanimous "admitted 6/6". A unanimous verdict from an instrument is a
reason to check the instrument. Gate 5 applies the same idea to guardrails: for each quantity
a promotion rule guards, a synthetic arm that maximises it through the behaviour the rule
should reject must be rejected. Terminal feasibility failed this test, because an explicit
deferral counted as feasible.

### 6.7 Failures are recorded when they happen

Every failure is written down at the moment it occurs, including the wrong first
hypothesis, in two registers that are not interchangeable.

- **Tier 1, the machine register,** one per family, derived only from published evidence so
  every row traces to a committed artifact by digest; it is regenerated, never edited, and
  regenerating it must reproduce the committed bytes.
- **Tier 2, the judgment log,** for what a machine cannot derive, in four categories:
  design (D), operational (O), tooling (T) and judgment (J), the last including errors by
  whoever writes the entry. Rows are never deleted; only their disposition changes, and
  `open` is a normal resting state.

**Table 6.3. Judgment-log rows by case and category (all branches, 2026-10-13).**

| Case (row prefix) | Design | Operational | Tooling | Judgment | Total |
|---|---:|---:|---:|---:|---:|
| Housing lemons and price line (HL) | 6 | 21 | 8 | 11 | 46 |
| Procurement (P) | 22 | 4 | 13 | 4 | 43 |
| Data center (DC) | 33 | 21 | 20 | 7 | 81 |

The counts cover each family's earlier designs as well as the current one. Operational rows
are where a measurement was lost and not rerun (a provider account out of credit, a CLI
outage, an overloaded route); judgment rows are where a reading was wrong, including two
withdrawn claims of our own (HL-J-08, DC-J-07). A finding that reaches already-published
numbers also gets a sealed erratum selecting the affected evidence by identity; published
bundles are never edited. The errata tooling is in review (PR #117).

**Evidence is reviewed by verification.** A sealed run root is published as a bundle with a
manifest of content digests. Reviewing an evidence bundle means recomputing its digests,
replaying every receipt from its sealed events with no provider call, scanning for prohibited
text, and pasting the output as the review; nobody is asked to read a 100,000-line bundle.
Changes to the shared runner need an approving review from someone other than the author.
Every published run opens in the Examiner, a trajectory viewer that shows each step as the
seat saw it beside the state it could not see, with a QC checklist per run; on 2026-10-13 that
checklist flagged 670 lines across 144 bundles, of which 58 need a reviewer once every
design row was read against its run.

### 6.8 What quality control found in the three cases

**Table 6.4. Defects found by quality control, with the level at which each was visible.**

| Row | What was wrong | Visible in one world? | How it was found | What changed |
|---|---|---|---|---|
| HL-D-04 | A seat-number tie-break and scripted rivals' $1 overbid decided who signed a sound listing | no: a pattern across seats | comparing signing rates by seat | one deciding tenant against declared outside demand |
| HL-D-01 | The scripted landlord's accept-or-counter reply was a free, near-perfect quality test beside a $25 inspection | no: needs the cost distribution | validity audit before a second model ran | pooled landlord; the revealing landlord kept as a declared arm |
| HL-D-03 | Admission made a favourite's lemon rate depend on its popularity (0.29 when six tenants shared it, 0.53 before admission) | no: a property of the admitted set | comparing pre- and post-admission rates | admit on the tenant's structure, read quality afterwards |
| HL-D-05 | The rule the tenant was told sat outside the sealed request | yes, by reading the sealed bytes | known at build, logged before any run | the rules sealed in the prompt, the tenant's history in the observation |
| HL-J-02 | A gap decomposition's "luck" part was not luck: uncontested blind bets were lemons 11 of 15 times, contested 1 of 15 | no: a split by rival behaviour | testing the stated odds by model (p = 0.006) | blind signings scored at their expected value given what the tenant saw |
| P (Gate 0) | A rule reading only the displayed price beat the qualified model by $28.50 a world | no: a baseline comparison | the construct check | construct gate recorded `failed`; Gate 0 made a profile mandatory |
| P-D-15 | The prompt pointed every subject at the cheapest listing, right in half the worlds and wrong in the other half | no: needs the pack's construction | asking whether the hard half was valid or a trick | a neutral prompt and a new pack |
| P-D-19, P-D-21 | The brief did not say a quote is final or that the buyer is judged on its average | no: a pattern in loss by action | listing each loss by the action that caused it | a second brief; loss fell from $12.2 to $1.0 and $19.4 to $5.4 a world |
| P-D-17 | Under sample noise the pre-award check reveals the true yield for one free action | yes, by reading the tool's code | designing a sample-again decision | open; 1 of 260 noisy cells used it, no published number moves |
| DC-D-27 | Walking away came within $11k to $46k of the right contract, and asking for every protection within $26k to $88k | no: a strategy-class simulation | simulating shortcut policies on the pack | before any freeze: each named shortcut must cost $75k more than the best contract, and a deal must beat the better outside option by $150k |
| DC-D-29 | At low effort the case could not separate two models: about 83% of the per-world gap was seed noise | no: needs paired seeds | variance split of the paired gap | one seed per world and more worlds; a redesign of the case |
| DC-D-32 | The scripted style hashed the whole world, including the client's hidden charge | no: needs two copies of a world | a test that the opening is identical for both types failed | the declared test uses a fixed style |
| DC-D-33 | The hidden type was fixed by pack cell and moved with public quantities | no | a placebo outcome (§6.5) | packs that play each world under each type |

Eleven of the thirteen were invisible in any single world. That is the main reason AERead's
quality control is organised around populations of worlds, declared analyses and recorded
failures rather than around reviewing instances.

### 6.9 Relation to Terminal-Bench's quality control

**Table 6.5. Terminal-Bench 2.0 checks and their AERead counterparts.**

| Terminal-Bench 2.0 [TB2] | AERead | What differs |
|---|---|---|
| An oracle script makes every test pass | A reference plays every world at zero loss and is checked against the environment (§6.2) | The reference scores every other play, so its agreement with the environment is itself tested |
| About three reviewer-hours per task, three reviewers | A hand trace of one admitted cell per family and after each mechanism change; a design review per case | Review of instances is cheap here; the defects that mattered were in the distribution (Table 6.4) |
| An adversarial exploit agent tries to pass without doing the task | Enumerated shortcut policies must lose a declared margin; trivial worlds are screened out; prompts are audited | AERead has no model-driven exploit agent; its shortcuts are those the designers thought of |
| 89 of 229 candidate tasks kept on the author's difficulty assessment | The control is run on every candidate world; trivial, floored and saturated are rejected separately under a sampling plan with stated miss rates (§6.3) | Difficulty is a measured rate per world |
| At least five runs per agent and model | Worlds over repeats, sized from pilot variance, with reliability and an A/A arm (§6.4) | Uncertainty is over worlds; repeats inside a world are correlated |
| Self-assessment against the Agentic Benchmark Checklist | The QC standard aligns its task and outcome validity checks with the same checklist [ABC] and adds mutation-verified checks (§6.6) | |

### 6.10 Where quality control falls short today

- **The current designs are not yet in their QC profiles.** Each family has a profile, and
  each profile covers that family's earlier designs: Housing `partial`; Procurement `partial`
  with its V1 construct gate `failed`; Data center `failed` at its 2026-09-19 audit and
  `partial` since. None of the three current designs (Housing's price case, pay-or-test, the
  agreement) has its own section yet, so their results are campaign evidence under the
  family's status, not a qualified construct.
- **Only Housing ran a declared confirmatory campaign.** Procurement and the data-center
  agreement have not passed a variance pilot and a confirmatory freeze; the agreement runs
  were not sized from a declared minimum effect.
- **No practitioner has set or reviewed the numbers.** Every price, fee, odds figure and
  clause cost is the designers' assumption.
- **No model-driven exploit agent and no human baseline.**
- **The checklist is noisy.** 612 of 670 flagged lines needed no reviewer; the rules
  themselves are an open issue (#287).
- **Contributed families cannot yet be admitted on their own.** Trusted execution of
  contributed conformance reports, runtime enforcement of declared resource ceilings, and
  authenticated human approval remain open.
- **Two CLIs expose no seed or temperature,** so their repeat plays are fresh draws and their
  determinism cannot be set.

### References

- [TB2] *Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces.* arXiv:2601.11868, 2026. §2.2–2.3 and Appendix B.
- [ABC] Zhu, Y., et al. *Establishing Best Practices for Building Rigorous Agentic Benchmarks.* arXiv:2507.02825, 2025.

### Sources for the numbers in this section

| Claim | Source |
|---|---|
| Gate definitions, sampling-plan table, reliability formula, counterpart scope, A/A arm | the benchmark QC standard and campaign SOP; the newest rule text on branch `codex/methods-design` (draft PR #288), whose `aeread.design` package computes Table 6.2 |
| Rows in §6.0, Tables 6.1 and 6.4 | the incident log on branches `codex/housing-lemons-outside-demand`, `codex/procurement-pay-or-test` and `codex/datacenter-agreement`; the procurement and data-center QC profiles |
| Table 6.3 | row ids carrying each prefix, collected from `docs/operations/incident_log.md` on every remote branch, 2026-10-13 |
| Reference checks (§6.2) | Housing case contract (v14 branch), `price_reference.py`; `tests/test_procurement_pay_or_test.py` on branch `codex/procurement-pay-or-test`; the agreement controls run on branch `codex/datacenter-agreement` |
| Data-center measurement facts (§6.4) | `agreement_results_2026-10.md` on branch `codex/datacenter-agreement`, section "What the runs showed about measurement" |
| Summary-setting check | one-pager `housing_summary_on_off_experiment.pdf`, run root `summary_experiment_20261009_v2` |
| Examiner checklist counts | the Examiner's triage build of 2026-10-13 (private repository, branch `qc-triage`) |
| Terminal-Bench facts | [TB2] |
