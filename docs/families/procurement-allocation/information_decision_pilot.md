# GLM decision-point diagnostic

This is a small live diagnostic of the [twelve authoring probes](information_decision_case_design.md),
requested after the design slice. It is not the full-episode procurement campaign,
a treatment/control comparison, or a replacement for the completed Phase 2 results.

## Frozen measurement contract

- Twelve isolated requests: one next-action decision per case, one inference seed
  (73001), one attempt each, six matched families. No outcome-based selection or
  retries. Each request has fresh context and contains only its own case.
- Model `z-ai/glm-5.3-flash`, Parasail through OpenRouter, no provider/model fallback.
  The alias is not an immutable weight revision. Retain actual response route fields.
- The detailed Phase 2 strategy paragraph is copied byte-for-byte. The common task
  prompt changes to explain these finite decision points and their response schema;
  the complete prompt is therefore not identical to Phase 2.
- Temperature 0, reasoning effort low, maximum 4,096 completion tokens. Timeout
  180 seconds per request, 2,400 seconds for the campaign. At most 12 requests,
  zero retries. Stop on a provider failure, unexpected route, budget or time limit;
  malformed or economically poor model responses do not stop the run.
- New trial hard ceiling **$0.05**. Verify the live Parasail endpoint against price
  caps $0.15/M input and $0.50/M output. Reserve UTF-8 request bytes plus 1,024 input
  tokens and all allowed output tokens before dispatch; no cache discount assumed.
  Missing reported charges retain the full reservation. This bounds the API token
  charges at the declared route caps, not unrelated account fees.
- Freeze source, fixture, strategy and request hashes before generation. Keep raw
  provider responses, receipts and all planned rows in a fresh ignored `runs/`
  directory. Restart in place is forbidden. Replay must verify saved response hashes
  and reproduce the score; no LLM judge is used.

The public payload contains possible conditional payoffs and observation likelihoods,
not the realized hidden condition, optimal action, optimum value, case ID, family
label or fixture answer key. Allocation cases receive vendor terms and must construct
quantities themselves; they are not given the enumerated feasible allocations.

**The current posterior is explicitly supplied**, including in the walk-away cases.
This pilot measures acting on a calibrated belief, not deriving a posterior from
raw supplier history. The conditional dollar payoffs also simplify accounting.
These limits are deliberate for this small decision-quality diagnostic.

The metric is `V*(public belief) - Q*(chosen next action)`, computed by the exact
reference. For a research choice, Q assumes optimal later decisions; there are
no live continuations and no claim of realized business profit. Report optimal
choices out of all 12 planned rows, both-correct matched pairs out of six, and
value loss among valid decisions with its denominator. Invalid/schema failures
remain explicit with null economic loss. Provider failures remain operational
missingness. Do not pool these probes with the Phase 2 panel or claim population
significance from six curated pairs.

A mocked always-defer provider scores only **1/12** optimal choices. Offline checks
cover value-sensitive choice, eligibility, quantities/MOQ/cash, answer-key isolation,
provider failure with retained reservation, interrupted requests and raw replay.
**45 focused tests passed before live execution.**

## Observed result: completed 2026-09-20

**9/12 optimal next actions (75%); 3/6 matched pairs both correct.** Eleven
responses were economically legal, including two suboptimal decisions; one was
an invalid order. All twelve returned parseable final JSON on the configured
GLM/Parasail route. No provider failure, truncation, retry or unattempted row.

| Mechanism | Optimal choices | Observed behavior |
|---|---:|---|
| Supplier prioritization | 1/2 | Correct when A's inquiry cost is $3; still chooses A when it rises to $8, where B is better. |
| Extra sample versus commit | 2/2 | Buys another sample at P(good)=.5 and commits at .9. |
| Deadline cost | 2/2 | Commits with one day left; investigates with two days left. |
| Evidence-supported walk-away | 2/2 | Defers at posterior .1 and investigates at .4; the explanations contain errors (below). |
| Splitting versus fixed freight | 1/2 | Correct A12+B8 at zero B freight; with $20 freight submits A6+B8, only 14 units against required 20. |
| Multi-component BOM | 1/2 | At budget $60 buys A20 controllers+C10 radios: legal 10-kit order with excess controllers, not the claimed 20 kits. Correct B10+C10 at budget $50. |

The two valid mistakes have independently checked opportunity losses:

- **Supplier ranking, decision 02:** A's quote is worth `.2*80 + .8*10 - 8 = $16`;
  B's is worth `.7*22 + .3*10 - 1 = $17.40`. Choosing A loses **$1.40**.
  The final explanation assigns A the 70% favorable probability belonging to B,
  contradicting both the prose observation and aligned probability arrays.
- **BOM quantities, decision 11:** 20 controllers and 10 radios make
  `min(20,10)=10` kits, earning `$50-$30=$20`. A10+B10+C10+D10 makes 20 kits
  for `$58`, earning `$42`. The selected legal allocation loses **$22**.
- **Freight/splitting, decision 10:** A6+B8 makes 14 kits, below minimum service
  20. This is a constraint failure, not a legal low-profit award. The reference
  chooses C20, earning $44. This diagnostic preserves null decision loss for the
  rejected allocation under its frozen invalid-action policy; it does not invent
  a penalty or silently remove the case from the 12-row accuracy denominator.

Across the **11 valid decisions**, total expected opportunity loss is **$23.40**,
mean **$2.1273**. This is conditional on legality and assumes optimal continuation
following a research choice. It is not mean realized procurement profit, and the
invalid order's loss is not included in that conditional dollar average.

The always-defer check gets **1/12** optimal choices. An additional exploratory
offline baseline that perfectly optimizes among immediate qualified awards but
never researches gets **7/12**. That baseline includes an exact allocation solver;
it is a diagnostic of the value of research, not another model result or a
preregistered statistical comparison.

### Correct actions do not certify correct explanations

The action scorer does not grade the model's numerical explanation. Two relevant
counterexamples are retained:

- Decision 07 correctly defers, but says even a profitable quote leaves probability
  about .217. Here a profitable quote perfectly reveals the favorable condition;
  the actual reason to defer is that its ex-ante value is `.1*30-4 = -$1`.
- Decision 08 correctly investigates, but claims value $9.60 by omitting the $4
  quote cost on the profitable branch. The correct value is `.4*30-4 = $8`.

Thus, 9/12 is **action accuracy**, not nine verified reasoning traces. The
probability-table presentation can contribute to mistakes; this trial does not
isolate representation sensitivity from economic planning capability. It shows
these probes expose useful errors with detailed strategy guidance. One attempt
per curated case cannot establish broad saturation, model ranking, or robustness.

### Execution and audit

| Item | Observed value |
|---|---|
| Executed source commit | `91552768` |
| Frozen plan | `e80a6e4327105d24818acb0ba4215280319734a8dac2b7118ab8a26093e79129` |
| Fixture SHA-256 | `407e1c169058d97199f2dc0bacb8aa563a1f22f803dc99fa9fee26db1003d7ff` |
| Attempted / completed / replayed | 12 / 12 / 12 |
| Recorded model / provider | `z-ai/glm-5.3-flash` / `Parasail` in every response |
| Provider-reported charges | **$0.0029043630**, no unknown-charge reserve |
| Conservative pre-dispatch reserve / hard ceiling | $0.03512055 / $0.05 |
| Sum of request latencies | 73.247 seconds |
| Reported prompt / completion tokens | 9,708 / 2,955 |
| Finish reasons | `stop` for all 12 |
| Validation | 45 focused tests before execution; all frozen source hashes unchanged; all 12 payloads pass answer-key/credential boundary audit; two replays byte-identical and equal to original result |

All evidence remains local under ignored
`runs/procurement_information_decision_glm_v1/`: `plan.json`, saved requests,
provider responses, receipts, `result.json`, and repeated replay outputs. Raw
provider payloads are not committed or externally published. Phase 2 evidence is
unchanged; this is not a comparable end-to-end performance delta.

The next useful extension is a full episode with actual quote/sample observations,
belief updates and model continuations. That would test whether the apparently
correct stopping decisions survive the accounting and belief errors seen here.

## Reproduction

```sh
python tools/run_procurement_information_pilot.py prepare \
  runs/procurement_information_decision_glm_v1
# execute uses OPENROUTER_API_KEY or a hidden terminal credential prompt:
python tools/run_procurement_information_pilot.py execute \
  runs/procurement_information_decision_glm_v1
python tools/run_procurement_information_pilot.py replay \
  runs/procurement_information_decision_glm_v1
```

Inspect [public_observation and grade](../../../tools/run_procurement_information_pilot.py)
for the input/scoring boundary, [boundary/replay tests](../../../tests/test_procurement_information_pilot.py)
for failure semantics, and the frozen local run's `plan.json` / `result.json` for
actual requests and outcomes. Source and planning are reviewable locally; no new
external PR or evidence publication is part of this trial.

Provider routing controls follow [OpenRouter's provider-selection documentation](https://openrouter.ai/docs/guides/routing/provider-selection).
