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
