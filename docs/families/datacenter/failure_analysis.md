# Data-center family: failure analysis

A taxonomy over the 766 incidents recorded across 9 runs and 768 cells, and
over the 15 design defects found while building the family. The register at
`evidence/datacenter_failure_register.json` is the source; this document is the
reading of it.

The two halves answer different questions. **Trajectory failures** say what
models do wrong. **Design defects** say what the benchmark got wrong, and they
turned out to be the more instructive half.

---

## Part 1: trajectory failures

### 1.1 The top level

| Class | Attribution | Incidents | Share |
|---|---|---:|---:|
| Excluded | model | 356 | 46% |
| No agreement | negotiation | 213 | 28% |
| Operational | provider | 166 | 22% |
| Operational | model | 15 | 2% |
| Operational | environment | 9 | 1% |
| Operational | budget | 7 | 1% |

Attribution answers the question worth asking later: whose fault was it?
Anything a model can trigger is the model's, never the provider's. Seventeen
incidents were recorded under one attribution and belong to another, and the
register keeps the original beside the correction rather than overwriting it.

### 1.2 Model failures, by kind

**Schema failures — 214 incidents.** Malformed JSON (109) and well-formed JSON
that is not a valid action (105). These say nothing about deal-making.

They concentrate at one moment. Of 79 in the most recent panel, 42 followed a
signature and 27 followed a decline; only 9 followed a counter. That is the
moment the developer must *open a new agreement* and emit a complete term set
for the first time, ten to sixteen structured fields at once. It is the hardest
action in the family.

Two hypotheses were tested and refuted, and both are worth recording as wrong:

- **Not context length.** Failing cells carry *fewer* input tokens per call,
  1,607 against 2,616, because they are shallower.
- **Not the richer counter messages.** Only 11 percent follow a counter.

The count rose from 38 to 79 when the negotiation wall came down. That is a
consequence of progress: models now reach more agreement openings, and each one
is a fresh chance to fail the hardest action. Schema compliance was always the
binding capability; it was masked.

**Substantive deal failures — 137 incidents.** A stack signed and executed that
cannot stand up. These are the trajectories worth reading.

Before the design was reworked, all 41 in a single panel failed identically, on
undersized power, after signing exactly five agreements. Six strata had been
built and none had ever been met by a live model. Afterwards, 61 failures
spread across five causes:

| What the stack got wrong | Cells |
|---|---:|
| Site control lapses before operations | 51 |
| Financing never funded | 21 |
| Project defaults | 21 |
| EPC conditions precedent unmet | 17 |
| Contracted power below the lease | 15 |

Many fail on several at once, which is why the constraint vector is reported
rather than its conjunction: a stack that failed on one thing and one that
failed on four used to score identically.

**Illegal but well-formed actions — 5 incidents.** Signing an offer never
accepted (4), and proposing an amendment that changes nothing (1). Rare, and
each one a genuine reasoning error rather than a formatting one.

### 1.3 Failure to transact — 213 incidents

| Where the negotiation stalled | Incidents |
|---|---:|
| Power | 119 |
| EPC | 36 |
| Land | 33 |
| Loan | 18 |
| Service | 5 |
| Land amendment | 2 |

Power dominates, and the cause was ours. The counterparty's entire message was
"utility counterproposal." It re-sent the same package every round with no
indication of what was short, so the integrative trade was undiscoverable in
three rounds except by luck. A typical trace showed land countered once and
then accepted, while power was countered three times and never accepted.

Once the counterparty began naming what it needed, stalls fell from 46 to 7 in
a comparable panel.

### 1.4 Infrastructure — 181 incidents

Rate limits (151), unknown provider outcomes (15), timeouts (11), 5xx (3),
empty responses (1). Roughly a quarter of every cell ever run.

This is not a nuisance category: ranking requires a complete panel, so
reliability decides *which routes get measured at all*. Two of four routes have
been excluded on these grounds rather than on anything about their negotiating.
Re-executing failed cells as further declared attempts recovered 12 of 49; the
other 37 hit the same limits again, so the throttling is persistent rather than
transient.

### 1.5 Our own failures — 16 incidents

Environment crashes (9) and budget ceilings (7). Both categories were larger
before the misattributions were corrected: a model emitting a 5,800-digit
integer and a model inventing a condition precedent both crashed the ledger and
were charged to the environment, and exhausting a declared action budget was
charged there too.

---

## Part 2: design defects

Fifteen found, all closed. This is the more useful half, because the pattern in
them is stronger than anything in the trajectory data.

### 2.1 By severity

| Severity | Count |
|---|---:|
| Invalidates the measurement | 3 |
| Mechanism does not bind | 2 |
| Strata do not test what they claim | 1 |
| Under-tests a declared capability | 1 |
| Headline number not comparable | 1 |
| Confounds a reported metric | 1 |
| Silent wrong metric | 1 |
| Mis-attributes failure | 1 |
| Truncates trajectories | 1 |
| Kills cells | 1 |
| Specification not realisable | 1 |
| Blocks a clean checkout | 1 |

### 2.2 The dominant family: mechanisms that did not bind

Five of the fifteen are the same error. A lever was declared, tests were
written for the properties its author had thought of, and only later did it
emerge that the lever constrained nothing.

- **The counter was the answer.** Adopting every counterparty's counter matched
  or beat the scripted baseline in 20 of 24 worlds. The panel was measuring
  whether a model copies.
- **The covenant cliff could not be built from leverage.** At a realistic
  loan-to-cost cap the commitment binds before the advance rate does, so
  leverage produced byte-identical outcomes from 50 to 80 percent. The plan
  names leverage as a lever for that stratum. It is not one.
- **The bankability threshold was cleared by convention.** Take-or-pay
  convention is 100 percent against a requirement of 85 to 95, and the security
  requirement was six months of rent, which is the conventional answer.
- **One obvious correction solved the task.** Adopting every counter and then
  sizing the connection to the lease solved 19 of 24 worlds.
- **The traps were unreachable by the behaviour models exhibit.** In four of six
  strata the counter package was the safe one, so an agent that adopts counters
  walked past the trap without facing the decision.

**The common cause.** Verification checked two points the author had
constructed — the feasible path and the trap — and treated that as proof the
mechanism discriminated. It never checked the space between them, which is
where the agent operates. There was a reference *right* answer and no reference
*wrong* answers. An answer key working says nothing about whether the question
is hard.

**The remedy, now enforced at generation.** A world that any naive strategy
solves is never emitted, and a stratum whose declared lever leaves the outcome
unchanged across its admissible range is never emitted. Levers are declared in
world data rather than in comments, so the check is mechanical.

### 2.3 Measurement defects

- **A survivorship-biased headline.** Mean NPV averaged only admitted stacks and
  declared walk-aways; excluded cells contributed nothing. The leading route's
  $437.9M was an average over 7 of its 48 cells, and became $94.7M once every
  completed episode was scored. It also rewarded failing loudly over failing
  quietly, since an exclusion left the mean untouched while a walk-away dragged
  it down.
- **A silently wrong diagnostic.** Counters recorded no structured terms, so the
  verbal/written metric compared against an empty package and reported zero
  adoptions for cells that had demonstrably adopted the hidden term.
- **A confounded metric.** The agreement listing was presented in canonical
  order, which puts financing last, which is also the order that forgoes
  learning the lender's terms. The presented default was systematically the
  worse choice, so copying could not be distinguished from reasoning.
  Alphabetical would have been worse: it puts the loan fourth and the lease
  last, so a copier would have scored full marks by accident.

### 2.4 Attribution defects

Three separate cases where a model's error was charged elsewhere: a
several-thousand-digit integer and an invented condition precedent both crashed
the ledger inside the provider call and were booked as infrastructure, and
exhausting a declared action budget was booked as an environment fault. The
rule that settles all three: **if a model can trigger it, it is not
infrastructure.**

### 2.5 Self-inflicted defects

Three were introduced by the fix for an earlier one.

- Allowing an optional agreement to be declined introduced a transition the
  phase graph never declared, which killed 6 of the first 7 cells of the next
  run.
- Making planning necessary made models negotiate more, and the episode's
  30-action budget could not fit a fully negotiated stack of 42, so a developer
  using the rounds it was granted was cut off and booked as an environment
  failure. The benchmark was penalising the behaviour it exists to measure.
- Longer negotiation pushed episodes past the per-route cost cap, truncating
  five of nine cells mid-stack.

All three were caught by a live panel rather than by the suite, which is the
expensive way to find them.

### 2.6 How defects were found

| Method | Count | Cost per finding |
|---|---:|---|
| Offline probe over the pack | 5 | free, seconds |
| Live panel | 5 | $2 to $4, about an hour |
| Recalibration to market magnitudes | 2 | free |
| Reading sealed evidence after a panel | 1 | free |
| Reading a completed summary | 1 | free |
| Running the suite in a fresh worktree | 1 | free |

A third of all defects cost a live run to find. The generation gates exist to
move that class into the free column.

---

## Part 3: what this leaves

**Usable yield.** In the most recent 192-cell panel, 61 cells were substantive
deal failures, 9 were admitted, 8 failed to transact, and 114 were discarded as
schema or infrastructure. Roughly two fifths of a panel is waste, and schema
compliance is what gates the sample.

**What is sound.** The engine's accounting identities, the two-sided acceptance
model, the planning requirement, the integrative trade, the calibration to
published market figures, and the attribution taxonomy. All are covered by
tests that would fail if they regressed.

**What is not yet established.** No route has produced enough admitted cells to
compare deal *quality*; the panel currently separates failure modes, not skill.
The counterparty still does not concede across rounds, so extra rounds add
little. Only V2 has worlds. Only one harness has run. And the 24 mechanism
annotations remain machine-derived, marked `generated`: the expert review panel
is published but no verdicts have been recorded against it yet.
