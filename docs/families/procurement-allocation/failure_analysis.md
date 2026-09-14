# Procurement failure analysis

What four subjects did on the inference panel, and where each one lost. Every
number here is derived from the trajectories by
`scratchpad analysis over runs/procurement_allocation/inference_v1_*`, and each
row is assigned the first mode that applies, so the counts partition the rows
rather than overlapping.

The panel is 18 worlds. In each, one visible attribute predicts supplier quality,
and which attribute and which direction differ between worlds. The binding
constraint also varies and is never labelled: yield in six worlds, delivery
timing in six, capacity in six. A rule committed to one direction can solve at
most nine, so nine is the fixed-rule ceiling.

## The scoreboard

| subject | worlds solved of 18 | rows | cost |
|---|---:|---:|---:|
| Gemini 3.8 Flash | 11 | 36 | $0.5582 |
| *fixed-rule ceiling* | *9* | — | — |
| GLM 5.3 Flash | 8 | 72 | $0.1945 |
| Qwen3-Next 80B instruct | 5 | 36 | $0.0832 |
| Qwen3-Next 80B thinking | not measurable | 36 | $0.0859 |

## How to check any of this yourself

The classifier is `aeread_families.procurement_allocation.trajectory_analysis`,
not a scratch script, so every number below is regenerable and every row is
inspectable. Three resolutions:

```
python -m aeread_families.procurement_allocation.trajectory_analysis \
    --runs runs/procurement_allocation                 # counts by stage
    --worlds                                           # solved per world per subject
    --table > rows.csv                                 # one line per trajectory
    --episode <world> <seed>                           # one trajectory, rendered
```

The episode view is the one that earns its keep. It prints the supplier table the
buyer actually faced, marks what it sampled and what those samples showed,
reconstructed from the declared noise seed rather than from hidden truth, and
marks what it awarded. Reading one changed this taxonomy: see the ignored
evidence stage below.

## The verifier at its edges

Worth knowing before reading any score, because feasibility is a cliff rather
than a slope. An award is checked line by line, and the checks are pinned in
`tests/test_procurement_scorer_boundaries.py`.

| award placed | result |
|---|---|
| exactly at capacity | accepted |
| one unit above capacity | `over_capacity` |
| one unit below the minimum order | `below_moq` and `invalid_order_step` |
| off the order step | `invalid_order_step` |
| on a supplier never quoted | `unknown_offer` |
| covering one component of two | zero kits, `minimum_service_not_met` |

**The service minimum is the edge that decides everything.** Completed kits are
`floor(quantity x yield x on-time + 1e-12)`, taken as the minimum across
components, and the award fails outright if that falls below the declared
minimum. At 20 units and 0.99 on-time, reaching 18 kits needs a yield of exactly
0.9090909091.

| yield | expected units | kits | feasible |
|---|---:|---:|---|
| 0.9091000000 | 18.000180 | 18 | yes |
| 0.9090909091 | 18.000000 | 18 | yes |
| 0.9090909000 | 17.999999820 | 17 | no |
| 0.9090000000 | 17.998200 | 17 | no |

Nine ten-billionths of yield separate a feasible award from a $275 regret. The
epsilon is load-bearing: removing it makes the exactly-on-threshold case round to
seventeen kits and scores a feasible award as a failure. Both that and the
threshold comparison are mutation-verified.

An award that fails any check is **not executed**. The buyer is scored as if it
had deferred, minus whatever it spent looking, so a failed award costs only its
information spend rather than the goods.

## A known-invalid output

Not every row is a decision. A recorded Qwen3-Next thinking trajectory:

```
action_count          1
termination_reason    invalid_action
action_trace          [{'action': 'unparseable', 'status': 'agent_action_failure'}]
violations            ['malformed_json']
contribution_margin   0.0
regret                272.44
receipt_replayed      True
```

The parser could not turn the response into an action, the episode ended after
one step, and the scorer still produced a number: margin zero, regret the whole
upper bound. That number is about the scaffold, not the buyer. It is why the
taxonomy gives parse failures their own stage and why design defect 29 treats
this model as unmeasurable rather than as scoring zero.

## The stages a trajectory can fail at

Five stages, in the order a trajectory passes through them. A row is classified
at the first one it fails.

1. **never ran** — the provider or harness did not return a usable episode.
2. **no valid action** — a response could not be parsed into an action.
3. **no award** — the episode ended without an award, by deferral or exhaustion.
4. **bad award** — an award was made that the subject's own evidence contradicts.
5. **ignored evidence** — the awarded supplier was ruled out by its own formal
   quote. On-time probability and capacity are both quoted, so a buyer that
   quoted a supplier already held the answer and did not need to sample.
6. **search** — the award was the best of what it verified, but it never verified
   anything adequate. Only yield worlds can reach here, because yield is the one
   risk a quote cannot settle.

A sixth bucket, **other**, holds rows where every awarded supplier was adequate
for the world's binding risk and the award still fell short. Adequacy is judged
against that risk rather than against yield alone, because a supplier that is
fine on yield can be the wrong choice in a world where timing or capacity bites.

## Where each subject lost

### Gemini 3.8 Flash, 36 rows

| stage | mode | rows |
|---|---|---:|
| solved | | 22 |
| ignored evidence | awarded a supplier its own quote ruled out | 3 |
| search | never checked an adequate supplier | 4 |
| no valid action | response could not be parsed | 5 |
| never ran | model qualification failure | 1 |
| no award | deferred deliberately | 1 |

It never awarded a supplier it had not verified and never committed after a
single draw. Its failures split between looking in the wrong place and ignoring a
quote it already held, and it is the only subject where search failures outnumber
ignored evidence. That is the only failure a
subject can have once its procedure is sound, and it is the failure the panel
exists to measure.

### GLM 5.3 Flash, 72 rows

| stage | mode | rows |
|---|---|---:|
| solved | | 34 |
| ignored evidence | awarded a supplier its own quote ruled out | 10 |
| search | never checked an adequate supplier | 8 |
| never ran | timeout | 12 |
| other | every awarded supplier was adequate yet the award fell short | 4 |
| bad award | awarded a supplier it never verified | 3 |
| no award | deferred deliberately | 1 |

Two things separate it from Gemini. It burns its budget rather than holding it,
failing twice as often with the field exhausted as with actions in hand. And
three rows award a supplier that was never verified at all, which is a procedure
failure rather than a judgment one. Its twelve timeouts are a route problem and
are counted apart from anything about the buyer.

### Qwen3-Next 80B instruct, 36 rows

| stage | mode | rows |
|---|---|---:|
| ignored evidence | awarded a supplier its own quote ruled out | 11 |
| search | never checked an adequate supplier | 4 |
| solved | | 13 |
| no award | budget exhausted before awarding | 4 |
| bad award | awarded a supplier it never verified | 3 |
| other | every awarded supplier was adequate yet the award fell short | 1 |

The weakest measurable subject, below every fixed rule. Fifteen of its failures
stop early with budget unspent, and four never reach an award at all.

### Qwen3-Next 80B thinking, 36 rows

Thirty-five rows ended on the first action with an unparseable response, and its
zero says nothing about the model. The plan caps output at 1800 tokens an action;
probing the route directly shows the model spending all 1800 on reasoning and
returning empty content with `finish_reason: length`. On a short prompt the same
endpoint returns clean JSON with its reasoning in a separate field, so neither the
parser nor the model is at fault. See design-review defect 29.

## The failure that dominates, and how it was found

Splitting *ignored evidence* out of *search* changes the headline. Across the
three measurable subjects, **24 of 41 decision failures awarded a supplier whose
own quote had already ruled it out.**

| subject | ignored evidence | failed search |
|---|---:|---:|
| GLM 5.3 Flash | 10 | 8 |
| Qwen3-Next 80B instruct | 11 | 4 |
| Gemini 3.8 Flash | 3 | 4 |

These were one bucket until an episode was read by hand. Gemini on
`lead_time_long_is_good__timing`: it quoted and sampled the two cheapest
suppliers, saw yields of 1.000 and 0.875, and awarded both. The samples were
fine. The world turned on delivery timing, and both awarded suppliers carried an
on-time probability of 0.55 against 0.99 for the two it never looked at. That
number was in the quotes it already held, and four actions were left unspent.

So the dominant failure is not insufficient searching. It is reading one field of
the evidence and ignoring another, in worlds deliberately built so that which
field matters changes. A subject that sampled less and read its quotes would
score better.

## The cut that explains the scoreboard

Split the worlds by which direction the signal runs.

| subject | solved when cheap, fast, small is good | solved when dear, slow, large is good |
|---|---:|---:|
| Gemini 3.8 Flash | 18 of 18 | 4 of 12 |
| GLM 5.3 Flash | 31 of 32 | 3 of 28 |
| Qwen3-Next 80B instruct | 13 of 18 | 0 of 18 |

All three carry the same prior: a good supplier is the cheap, fast, low-minimum
one. On worlds where that is true they are near perfect. On worlds where it is
false they collapse, and Qwen never recovers once. Gemini's eleven comes entirely
from partly escaping this, four times out of twelve.

This is the single most diagnostic number in the analysis. It says the subjects
are not reading the world, they are applying a belief about what good looks like,
and the panel's value is that it holds that belief up against both directions.

## Which constraint does the killing

| subject | yield | timing | capacity |
|---|---:|---:|---:|
| Gemini 3.8 Flash | 6 of 10 | 6 of 10 | 10 of 10 |
| GLM 5.3 Flash | 8 of 18 | 11 of 19 | 15 of 23 |
| Qwen3-Next 80B instruct | 5 of 12 | 3 of 12 | 5 of 12 |

Capacity worlds are solved most often by the two stronger subjects, and Gemini
solves all ten. Capacity is the one constraint visible in the formal offer
without a sample, so a buyer that reads offers carefully clears it without
inferring anything. Yield and timing need evidence, and both subjects lose about
40% of those worlds. Qwen shows no such profile, losing everywhere about equally,
which is consistent with it not using the offers either.

## Behaviour common to all three measurable subjects

| | Gemini | GLM | Qwen instruct |
|---|---:|---:|---:|
| suppliers verified per row, median of 8 | 2 | 3 | 2 |
| spare actions at the end, median of 9 | 4 | 2 | 4 |
| rows that re-sampled anyone | 0 | 11 | 0 |
| rows that used the cheap inquiry | 0 | 0 | 0 |

Not one row in 144 used the cheap screening reading, which is now the fifth
model-and-prompt combination to record zero on that channel. Two of three
subjects finish holding nearly half their budget. Verification runs to two or
three suppliers of eight, and only GLM ever takes a second draw.

## What the taxonomy is for

Three uses, in order of how much they change what to do next.

**It separates a subject from a scaffold.** Twelve GLM timeouts and thirty-five
Qwen thinking parse failures are not results about buyers, and a taxonomy that
did not hold them apart would have reported a capability ranking that was partly
a route and a token cap.

**It separates process from judgment.** GLM awards unverified suppliers and
exhausts its budget; Gemini does neither and fails only by looking in the wrong
place. Those call for different fixes, and a single "failed" count hides that.

**It names the behaviour to target.** Every subject stops early, none re-samples
under noise, and none buys cheap information. That is one behaviour, it is
model-independent so far, and it is the thing the family should be built to
measure.
