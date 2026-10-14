# Quality control (draft section of the AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. It describes the quality-control design as the
[benchmark QC standard](../operations/benchmark_qc.md), the
[campaign SOP](../operations/experiment_campaign_sop.md) and the
[incident log](../operations/incident_log.md) define it, with the newest rule text from
draft PR #288 (sampling plans, reliability, counterpart scope, the A/A arm), and illustrates
each part with what it caught in the four cases of the companion
[case-study section](paper_case_studies.md). Incident row ids (HL-, P-, DC-) refer to the
incident log on the branch of each case.

---

## 6. Quality control

### 6.0 What quality control has to catch

An AERead item is a world drawn from a generator, scored in dollars against a reference
computed for it, often against a counterpart that adapts. The defects that mattered in the
four cases were properties of the distribution, the information structure, the brief, the
counterpart or the analysis, and every world was individually correct when they were found:

- in Housing's six-tenant market, which tenant signed a sound listing was decided by a
  tie-break on seat number (seat 0 signed one in 59% of cells, seats 1 to 5 in 18% to 35%;
  HL-D-04);
- the rule admitting a Housing world made the favourite listing's quality depend on how many
  tenants shared it (HL-D-03);
- procurement's prompt pointed every subject at the cheapest listing, which was the right
  supplier in half the worlds and the wrong one in the other half, so the pack's two halves
  measured whether an instruction happened to be right (P-D-15);
- in the data-center packs the hidden type moved with public features of the world, so any
  comparison by type across worlds compared the worlds (DC-D-33).

Reading one world at a time passes all four. Quality control is therefore built around checks
on populations of worlds and on the experiment, and around recording every failure at the
moment it happens. Because AERead is meant to grow through contributed cases, the same process
is the checklist a contributor works through, and the four cases of Section 5 went through it
with the defects in §6.7 to show for it. This section describes that checklist (§6.1),
the automated checks (§6.2), the tools for reading a play (§6.3), the adversarial checks
(§6.4), the statistical controls (§6.5), how failures are recorded and evidence reviewed
(§6.6), what the checks found (§6.7), an assessment against the Agentic Benchmark Checklist
(§6.8), and where quality control falls short (§6.9).

### 6.1 The case author's checklist

Quality control runs on two tracks with a deliberate boundary. **Benchmark QC** qualifies the
instrument: the world distribution, the environment and verifier, the construct and the
attribution design, in six gates recorded per family in a QC profile. **Campaign gates**
qualify one experiment on that instrument: `design_contract`, `provider_free_validation`,
`profile_admission`, `full_trajectory`, `variance_pilot`, `confirmatory_freeze`,
`confirmatory_execution` and `publication`, in that order. A green campaign cannot repair a
bad reference, and a qualified family does not make an underpowered or selectively missing
campaign reportable. Each gate ends in one of five typed states (`passed`, `failed`,
`partial`, `not_run`, `not_applicable`), and only `passed` promotes.

**Table 6.1. Benchmark QC gates.**

| Gate | Question | Stops when | In the four cases |
|---|---|---|---|
| 0. Profile | Is there a place to record each gate's verdict? | the family has no QC profile | Procurement's construct check ran and found a public-price rule beating the model by $28.50 a world; with no profile, the verdict was read as a campaign finding and lost |
| 1. Task distribution | Are the worlds valid, distinct, split and informative? | an unverified bound, duplicates across clusters, development and holdout overlap, no measured headroom | Housing v14 admits a seed on the tenant's own structure and reads quality afterwards, with a holdout from a disjoint seed range; pay-or-test admits on what a buyer can see and draws types afterwards |
| 2. Environment and verifier | Do actions change the intended state, and is every score rebuilt from sealed evidence? | invalid actions mutate state, an oracle disagrees, hidden state leaks, replay differs | 1,800 of 1,800 Housing v14 receipts replay with no provider call; P-D-17 (open): under sample noise a pre-award check computes kits from true yield, so one free action reveals the hidden quality |
| 3. Construct and baselines | Does a better-informed policy do better, and do shortcuts lose? | stronger and weaker policies indistinguishable, a shortcut drives the score | Procurement's shortcut rules give up $45.7 to $146.1 a world against an exact policy that a one-step comparison matches; an earlier data-center baseline was worse than walking away, by $550 (DC profile audit) |
| 4. Attribution and controls | Does the result support the attribution it claims? | an undeclared control changes, the matrix is incomplete, the block cannot carry the claim | the three v14 identities differ only in model and route; data-center claims name their counterparts |
| 5. Confirmatory reliability and publication | Was the comparison sized, frozen and executed without tuning on outcomes? | incomplete pilot, a frozen control changed, selective missingness, a guardrail no behaviour can fail | v14's analysis was declared before any cell; 36 refused cells stayed missing and a fill ran under its own identity |

Changing any bound input reopens the gates downstream of it: a generator change reopens Gates
1 to 5, a scorer change 2 to 5, a new counterpart 4 and 5, and a change to the analysis, seeds
or sample size after a freeze requires a new campaign identity.

**A contributed case enters through its own admission path.** Before it joins the registry a
contributed family must bind, in one version-bound record: a unique namespace; closed action and
observation schemas (every property required, nothing extra allowed); a provider-free conformance
report covering everything it declares; finite ceilings on wall time, actions, provider calls,
tokens and cost; and a human QC approval whose digest binds that exact contribution. The
approval must come from outside the contribution. Refund V2.1 showed why: its runner hashed two
status-only QC stubs and set the approval's digest to the contribution it had just built, so the
approval bound whatever the runner produced (RF-T-01). Refund V2.5's record names a reviewer and a
date and rejects V2.1's, but its runner still binds the approval to the contribution it has just
built (RF-D-06): the admission path is specified, and the mechanism that makes the approval
independent is not yet in place.

Three checks are owed before any model plays a new case. The reference plays every admitted
world and agrees with the environment (§6.2). Every rule the brief states is checked against
the environment by a test, and the brief states what the side is judged on and whether a
price is final. And the simplest one-step rule is run first: if it matches the best policy,
the case is arithmetic and is not run. Procurement's pay-or-test pack is where this last check
was learned; a one-step comparison matches its best policy to within $0.06 a world, and both
frontier agents found that comparison (§5.5).

### 6.2 Check tools

Each kind of verifier in §5.1 owes a different proof that it measures what it claims.

**Table 6.2. What each kind of verifier must be shown to do, and how the four cases show it.**

| Kind | Must be shown | How it is shown in the four cases |
|---|---|---|
| Answer | the key is correct and complete for every admitted case | Refund's reference resolution is written by hand per template, and admission requires the policy's public compiler to reproduce it on every case, with a unique path through the policy's precedence |
| Rule | every rule is stated to the subject, and each check fails on a counterexample | briefs are checked against the environment by tests; checks are mutation-verified (below); a rule left unstated is a defect of the case (P-D-19, RF-D-03) |
| Value | the reference agrees with the environment, and a simple rule does not already match it | Procurement's policy equals the environment's average over 27 type profiles; Housing's offline reference replays the sealed scripted cells to the cent; the one-step rule is run first |
| Relative | the counterparts are named, the gap is reported per counterpart, and the analysis does not fire on identical arms | the data-center counterpart table (Table 5.7); an A/A arm (§6.5) |
| Rubric | the rater agrees with people and resists gaming | not used in the four cases |

The checks below run without calling a model.

- **Regeneration.** Every world is re-resolved from its generator, parameters and seed, and its
  canonical content digest must match. Denominators, bounds and reference values are
  validated, and degenerate worlds stay visible under a declared rule rather than being
  silently resampled.
- **The reference against the environment.** Procurement's best informed policy is tested
  against the environment's average over all 27 ways the newcomers can turn out. Housing's
  offline reference first replays the sealed scripted reference cell for cell on the
  development worlds, 120 of 120 to the cent. In the data-center case a pair of reference
  players loses nothing on all 58 worlds, and a pair that signs the draft loses $318k a world
  over the same 58.
- **Replay.** Every published receipt is rebuilt from its sealed events with no provider call
  and must reproduce its state and score; for Housing v14 that is 1,800 of 1,800. Refund V2.5
  qualifies its whole public release this way, with deterministic profiles in every seat: 816 of
  816 trajectories, every leaf covered, each receipt replayed independently.
- **Visibility.** Every payload a seat receives is audited for evaluator-only state.
- **Plan-level contract tests.** Paired plans are tested to differ only in the declared
  treatment or rotation.
- **Headroom screen.** The declared control is run on every candidate world, and a world is
  rejected on three grounds tested separately: *trivial* (a deterministic policy reading only
  public observations already succeeds), *floored* (the control never succeeds) and *saturated*
  (it always does). "The two policies disagree" is not a substitute; it admits a saturated
  world whenever a baseline happens to lose there. For a continuous score the grounds become
  *degenerate* (the control scores the same at every seed) and *trivial*.

Saturated and floored are claims about a rate, so the number of seeds per world is a sampling
plan with known errors, and the panel manifest states them.

**Table 6.3. How often a screen admits or refuses a world, by seeds per world (control outcome is success or failure).**

| Seeds per world | Rejected when the control succeeds | Admits a world solved 95% of the time | Rejects one solved 50% of the time |
|---:|---|---:|---:|
| 1 | never or always | 0% | 100% |
| 3 | never or always | 14% | 25% |
| 10 | never or always | 40% | 0% |
| 10 | 1 or fewer, or 9 or more | 9% | 2% |

One seed can discard a world but cannot admit one, and under a never-or-always rule more seeds
admit more near-saturated worlds. A shared calculation (`aeread.design.screen_plan`) produces
these rates for any plan; no shared calculation yet covers the dispersion rule for continuous
scores.

**A check counts only once it has been seen to fail.** A required check is evidence only after
it has failed on a counterexample: revert the guard, confirm the check dies for the intended
reason, restore it, confirm it passes, and record the kill. Three defects fixed on 2026-09-05
had passed every existing suite because the suites asserted something true by construction.
For the same reason a screening loop never catches an exception: procurement's first two-sided
screen called a policy with a positional argument where the parameter was keyword-only, scored
the resulting error as a loss in every world, and printed a unanimous "admitted 6/6". A
unanimous verdict from an instrument is a reason to check the instrument.

### 6.3 Trace and debug tools

**The Examiner.** Every published run opens in a trajectory viewer that shows each step as the
seat saw it, beside the state the seat could not see, with the parsed action, the transition
and the sealed score, and a QC checklist per run. On 2026-10-13 that checklist flagged 670
lines across 144 bundles; once every design row was read against its run, 58 needed a
reviewer, and each run opens with the lines that do.

**A hand trace.** Once per family, and again after any change of mechanism, one admitted cell
is walked by hand: the observation the seat received, the text the model returned, the parse,
the legality check, the transition and the sealed score, read from the real bytes. An admitted
cell is chosen rather than a failure, because it shows what the case rewarded. On an earlier
data-center design this found two design defects in about an hour at no cost, where live
panels found defects at $2 to $4 and an hour each.

### 6.4 Adversarial checks

AERead has no model-driven exploit agent. Its adversarial checks are policies and audits that
try to score well without making the decision the case is about.

- **Shortcut policies must lose a declared margin.** In the data-center case walking away once
  came within $11k to $46k of the right contract and asking for every protection within $26k
  to $88k (DC-D-27); since then each named shortcut (sign the draft, haggle only the price, ask
  for every protection, walk) must cost $75k more than the best contract before a world is
  admitted. Procurement's fixed rules are scored exactly against the best policy (§5.3).
- **Trivial agents are reported.** Signing the draft unchanged (14% of the value available) and
  always paying the premium ($75.2 a world given up) are reported beside the subjects; Housing
  v14 reports no do-nothing tenant.
- **The brief is audited for instructions that decide the outcome.** Procurement's earlier
  prompt pointed every subject at the cheapest listing (P-D-15), and its first pay-or-test brief
  left unsaid that a quote is final and that the average is the criterion (P-D-19, P-D-21).
- **Look-back analyses run a placebo outcome first.** A pattern found by looking back through
  runs is tested on an outcome that cannot depend on the attribute in question. The data-center
  look-back regression of Opus's price on its hidden type gave 0.52; the same regression on the
  opening price of a scripted integrator that is never told the type gave 0.38 [0.23, 0.52],
  where the answer must be 0 (DC-D-33). A random relabelling of types did not catch it (0 of
  3,000 shuffles reached the observed value), because a permutation null tests association and
  a confound is an association.
- **Guarded metrics must be falsifiable.** For each quantity a promotion rule guards, a
  synthetic arm that maximises it through the behaviour the rule should reject must be
  rejected. Terminal feasibility failed this test, because an explicit deferral counted as
  feasible.

### 6.5 Statistical controls

**The unit is the world.** Repeats, seats, turns and calls inside a world are correlated;
uncertainty is computed over worlds, paired across conditions on the same worlds. On the
data-center runs, treating plays as independent made intervals about 1.5 times too narrow, and
more worlds beat more repeats: a $50k gap needs 83 to 91 negotiations an arm at one play a
world against about 160 at three.

**Claims name their counterparts.** When more than one counterpart type is run, the gap is
reported per type and tested for variation before pooling, and a general advantage needs a
positive gap against every declared type. In the data-center case the counterpart accounts for
25% to 33% of the spread in what a model earns (shuffled labels give 2% or less), and the gap
between the same two agents runs from not distinguishable to $251k (Table 5.5).

**An A/A arm runs through the whole pipeline.** One profile in both arms, through execution,
scoring, analysis and the claim rule; a rule that fires stops the campaign before its freeze.
On the data-center repeat plays, 0 of 48 same-condition comparisons were flagged, and two runs
of one condition on 20 worlds differed by $16k to $25k typically.

**Sizing and reliability are computed and sealed.** The confirmatory number of worlds comes
from the variance pilot's paired world-level spread, a declared minimum meaningful effect, a
target power and an attrition rule, and the calculation is sealed with the freeze. A comparison
also reports its reliability, the expected correlation between the model means of two
independent runs of the same design:

```text
reliability = var_model / (var_model + var_world_model / worlds + var_play / (worlds x plays))
```

A world's own level is not error, because every model meets the same worlds; a counterpart or
seat that the design samples is error, and one it fixes narrows the claim instead.

**Declared tests.** A pattern found by looking back is a hypothesis. To become a result it is
written down first: the claims, measures, exclusions and primary predictions are committed
before the runs, the analysis code before the runs finish, on worlds no model has played, with
the world held fixed and one thing changed, and the primary predictions corrected together. Of
the two patterns the data-center signalling test declared, one was supported and one was not,
and the unsupported one had already been reported on a result sheet (DC-J-07).

**Harness settings are tested, not assumed.** Whether a CLI is asked for reasoning summaries
changed nothing detectable in Housing (Opus +17 [−28, +62], Sol +3.5 [−46, +53] on five
selected worlds, 120 episodes, randomised order), a small check whose limits are stated on its
sheet: the worlds were chosen after an earlier result and three plays cannot exclude a small
effect.

### 6.6 Failure records and evidence review

Every failure is written down at the moment it occurs, including the wrong first hypothesis,
in two registers that are not interchangeable.

- **Tier 1, the machine register,** one per family, derived only from published evidence so
  every row traces to a committed artifact by digest; it is regenerated, never edited, and
  regenerating it must reproduce the committed bytes.
- **Tier 2, the judgment log,** for what a machine cannot derive, in four categories: design
  (D), operational (O), tooling (T) and judgment (J), the last including errors by whoever
  writes the entry. Rows are never deleted; only their disposition changes, and `open` is a
  normal resting state.

**Table 6.4. Judgment-log rows by case and category (all branches, 2026-10-13).**

| Case (row prefix) | Design | Operational | Tooling | Judgment | Total |
|---|---:|---:|---:|---:|---:|
| Housing lemons and price line (HL) | 7 | 21 | 8 | 11 | 47 |
| Procurement (P) | 22 | 4 | 13 | 5 | 44 |
| Data center (DC) | 33 | 21 | 20 | 7 | 81 |
| Refund (RF) | 6 | 0 | 1 | 1 | 8 |

The counts cover each family's earlier designs as well as the current one. Operational rows are
where a measurement was lost and not rerun (a provider account out of credit, a CLI outage, an
overloaded route); judgment rows are where a reading was wrong, including two withdrawn claims
of our own (HL-J-08, DC-J-07) and a ratio misstated on a result sheet (P-J-05). A finding that reaches already-published numbers also gets a
sealed erratum selecting the affected evidence by identity; published bundles are never edited.
The errata tooling is in review (PR #117).

**Evidence is reviewed by verification.** A sealed run root is published as a bundle with a
manifest of content digests. Reviewing an evidence bundle means recomputing its digests,
replaying every receipt from its sealed events with no provider call, scanning for prohibited
text, and pasting the output as the review; nobody is asked to read a 100,000-line bundle.
Changes to the shared runner need an approving review from someone other than the author.

### 6.7 What quality control found in the four cases

**Table 6.5. Defects found by quality control, with the level at which each was visible.**

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
| DC-D-33 | The hidden type was fixed by pack cell and moved with public quantities | no | a placebo outcome (§6.4) | packs that play each world under each type |
| HL-D-07 | The primary measure conditions on the landlord's reply only below the sound floor; a reply that proves a listing sound is still scored at the stated odds | yes, by reading the measure's code | writing the formal appendix of this paper | open; to be recomputed from the published bundle |
| RF-D-01 | The 120-cell panel was six cases: the world seed changed only the case id, and the policy seat ran at temperature 0 | no: needs the seeds compared | rebuilding the cases and reading the reference run's resolutions | the case is the unit of analysis; V2.5 varies declared conditions by seed |
| RF-D-03 | A correct denial written with method `null` failed: the prompt says "none", the schema allows null, the verifier compares strings | yes, by reading one proposal against the verifier | building the gap decomposition | recorded; reported as format, not outcome |
| RF-T-01 | The human-QC approval was minted by the runner from two status-only stubs, so it bound whatever the runner produced | yes, by reading the runner's code | the Refund audit | V2.5 names a reviewer, but the runner still binds the approval to its own output (RF-D-06, open) |
| RF-D-05 | Refund's payment leaf checks that payments executed what the proposal asked, so a proposal with an aliased mutation moves no money where the reference refunds $185.22 and still scores 1.0 | yes, by tracing one case | writing the formal appendix of this paper | open; report the leaf as binding and add a check against the reference |

Twelve of the eighteen were invisible in any single world, and the six that were visible were
found by reading code or sealed bytes, or by tracing one case, not by playing a panel. That is the main reason quality control
is organised around populations of worlds, declared analyses, code reading and recorded
failures rather than around reviewing instances.

### 6.8 Assessment against the Agentic Benchmark Checklist

The QC standard aligns its task and outcome validity checks with the Agentic Benchmark
Checklist [ABC]. Table 6.6 assesses the four cases as they stand, item by item; the
outcome-validity items that apply are those for a quality measure, since no case is scored by
string matching, unit tests or a judge model.

**Table 6.6. The four cases against the checklist.**

| Item | Status | Evidence |
|---|---|---|
| T.1 Tool versions specified | partly | routes, prompts, schemas and implementation digests are sealed in each plan; the two CLI agents expose no seed or temperature |
| T.2 Required APIs accessible | partly | provider outages lost cells (36 Housing cells to an empty account, 39 data-center negotiations to CLI errors), each recorded as typed missingness |
| T.3 Terminates or handles API errors | met | a sealed retry policy; three consecutive failed cells stop a run; a failure is never scored as zero |
| T.4 Residual state cleared between runs | met | each cell is a fresh episode from a sealed plan; the CLI agents run one ephemeral subprocess per action |
| T.5 Agent isolated from ground truth | partly | observations are audited for evaluator-only state; one leak was fixed (HL-D-01) and one is open in noisy-sample packs (P-D-17) |
| T.6 Setup does not change over time | met | the environments are deterministic and sealed; hosted model routes are pinned and snapshotted |
| T.7 Ground truth verified | met | each reference is checked against the environment (§6.2) |
| T.8 Each task verified solvable | met | the reference plays every admitted world, and admission requires that the decision matters |
| T.9 Oracle solver | partly | exact for Procurement; an independent reference resolution and a scripted policy that resolves every case for Refund; a reachable reference for Housing, with an exact best informed tenant in development; a full-information stand-in for Data center, whose per-turn best informed policy is not built |
| T.10 Free of exploitable shortcuts | partly | shortcut policies, trivial-world screens and brief audits (§6.4); eighteen defects found (Table 6.5); a wrong refund can still pass Refund's payment leaf (RF-D-05); no model-driven exploit agent |
| O.i.1 Quality metric resists exploitation | met | dollars against an exact or reachable reference; blind bets priced at expected value; guarded metrics must be falsifiable |
| R.1 Open source | partly | the environments, runner and evidence are public; the trajectory viewer is private |
| R.2 Open evaluation harness | met | the shared runner is in the public repository |
| R.3 Contamination prevented | met | generated worlds; holdouts from a disjoint seed range; fresh worlds for declared tests |
| R.4 Plans to update | partly | packs regenerate from new seeds; no refresh schedule is stated |
| R.5 Capability related to construct | met | each case states the decision it measures (Table 5.1) |
| R.6 Evaluation subject stated | met | the subject is a profile (model, harness, prompt, tools, reasoning, retries); CLI agents are named with their harness |
| R.7 Steps to prevent, find and correct flaws | met | the gates, the incident log and errata (§6.1, §6.6) |
| R.8 Qualitative discussion of unavoidable flaws | met | §5.7 and §6.9 |
| R.9 Quantitative analysis of flaw impact | partly | measured for the brief change, the refused cells and missingness bounds; not for every open row |
| R.10 Statistical significance | met | paired world-level intervals; Holm correction across declared primaries |
| R.11 Guidance on interpreting flawed results | met | every result is labelled confirmatory, declared or development |
| R.12 Non-AI baselines | partly | scripted policies in every case; no human |
| R.13 Trivial agents | partly | always paying (Procurement) and signing the draft (Data center) are reported; Housing v14 reports no do-nothing tenant, and Refund V2.1 has no lower anchor (RF-D-04) |

### 6.9 Where quality control falls short today

- **The current designs are not yet in their QC profiles.** Each family has a profile, and each
  profile covers that family's earlier designs: Housing `partial`; Procurement `partial` with
  its V1 construct gate `failed`; Data center `failed` at its 2026-09-19 audit and `partial`
  since. None of the three current designs (Housing's price case, pay-or-test, the agreement)
  has its own section yet, so their results are campaign evidence under the family's status,
  not a qualified construct.
- **Only Housing ran a declared confirmatory campaign.** Procurement and the data-center
  agreement have not passed a variance pilot and a confirmatory freeze; the agreement runs
  were not sized from a declared minimum effect.
- **Qualification is not discrimination.** Refund V2.5's release shows that its environment,
  scripted seats and verifiers agree on every case; with no lower control it does not show that
  the panel separates strong from weak play (RF-D-06).
- **No practitioner has set or reviewed the numbers.** Every price, fee, odds figure and clause
  cost is the designers' assumption.
- **No model-driven exploit agent and no human baseline.**
- **The checklist is noisy.** 612 of 670 flagged lines needed no reviewer; the rules themselves
  are an open issue (#287).
- **Contributed families cannot yet be admitted on their own.** Trusted execution of
  contributed conformance reports, runtime enforcement of declared resource ceilings, and
  authenticated human approval remain open.
- **Two CLIs expose no seed or temperature,** so their repeat plays are fresh draws and their
  determinism cannot be set.

### References

- [ABC] Zhu, Y., et al. *Establishing Best Practices for Building Rigorous Agentic Benchmarks.* arXiv:2507.02825, 2025.

### Sources for the numbers in this section

| Claim | Source |
|---|---|
| Gate definitions, sampling-plan table, reliability formula, counterpart scope, A/A arm | the benchmark QC standard and campaign SOP; the newest rule text on branch `codex/methods-design` (draft PR #288), whose `aeread.design` package computes Table 6.3 |
| Rows in §6.0, Tables 6.1 and @5 | the incident log on branches `codex/housing-lemons-outside-demand`, `codex/procurement-pay-or-test` and `codex/datacenter-agreement`; the procurement and data-center QC profiles |
| Table 6.4 | row ids carrying each prefix, collected from `docs/operations/incident_log.md` on every remote branch, 2026-10-13 |
| Reference checks (§6.2) | Housing case contract (v14 branch), `price_reference.py`; `tests/test_procurement_pay_or_test.py` on branch `codex/procurement-pay-or-test`; the agreement controls run on branch `codex/datacenter-agreement` |
| Data-center measurement facts (§6.5) | `agreement_results_2026-10.md` on branch `codex/datacenter-agreement`, section "What the runs showed about measurement" |
| Summary-setting check | one-pager `housing_summary_on_off_experiment.pdf`, run root `summary_experiment_20261009_v2` |
| Examiner checklist counts | the Examiner's triage build of 2026-10-13 (private repository, branch `qc-triage`) |
| Table 6.5 items | [ABC], Figures 2 to 4 |
