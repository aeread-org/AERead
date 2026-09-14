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

## The stages a trajectory can fail at

Five stages, in the order a trajectory passes through them. A row is classified
at the first one it fails.

1. **never ran** — the provider or harness did not return a usable episode.
2. **no valid action** — a response could not be parsed into an action.
3. **no award** — the episode ended without an award, by deferral or exhaustion.
4. **bad award** — an award was made that the subject's own evidence contradicts.
5. **search** — the award was the best of what it verified, but it never verified
   anything adequate.

A sixth bucket, **other**, holds rows where every awarded supplier was adequate
for the world's binding risk and the award still fell short. Adequacy is judged
against that risk rather than against yield alone, because a supplier that is
fine on yield can be the wrong choice in a world where timing or capacity bites.

## Where each subject lost

### Gemini 3.8 Flash, 36 rows

| stage | mode | rows |
|---|---|---:|
| solved | | 22 |
| search | stopped with budget unspent, never checked an adequate supplier | 7 |
| no valid action | response could not be parsed | 5 |
| never ran | model qualification failure | 1 |
| no award | deferred deliberately | 1 |

Every decision failure is the same mode. It never awarded a supplier it had not
verified, never contradicted its own evidence, and never committed after a single
draw. It looked in the wrong place and stopped. That is the only failure a
subject can have once its procedure is sound, and it is the failure the panel
exists to measure.

### GLM 5.3 Flash, 72 rows

| stage | mode | rows |
|---|---|---:|
| solved | | 34 |
| search | spent the whole budget without finding an adequate supplier | 12 |
| search | stopped with budget unspent, never checked an adequate supplier | 6 |
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
| search | stopped with budget unspent, never checked an adequate supplier | 15 |
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
