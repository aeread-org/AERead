# DeepSeek procurement: 600-episode run plan

Date: 2026-08-28. Request: run 600 procurement episodes with DeepSeek.
Status: implementation prepared; paid calls await an explicit total spending limit.

## Locked comparison and measurement

| Parameter | Setting |
| --- | --- |
| Model | `deepseek/deepseek-v4-flash-0731` |
| Canonical revision | `deepseek/deepseek-v4-flash-20260731` |
| Route | OpenRouter → Parasail, fp8, no fallback |
| Conditions | `reasoning_none_v1` versus `reasoning_low_v1`, matching Housing |
| Sample | 100 generated worlds × 2 conditions × 3 nested repeats = 600 episodes |
| Admission | 3 separate worlds × 2 conditions × 1 repeat = 6 additional episodes |
| Proposed fresh master seed | `2026082801` |
| Inference seed base | `20260828`, paired across conditions within each world/repeat |
| Primary endpoint | Treatment-minus-control mean normalized buyer surplus, `R/U` |
| Inference | Whole-world cluster bootstrap; exact declared panel and missingness support |
| Verifier | `objective_reference`, deterministic objective upper bound |
| Spending limit | Awaiting user choice; includes admission plus sample |

The world distribution, supplier policy, economic reference, receipts, and shared scheduler
are unchanged from the provider-free validation. Only synthetic buyer prompts are sent to
OpenRouter/Parasail. Supplier-private costs remain in local supplier observations and evaluator
truth. This is a synthetic procurement benchmark, not an actual purchase.

## Provider preflight

The read-only OpenRouter catalog on 2026-08-28 listed the selected Parasail endpoint as
available with structured outputs, reasoning effort, and seed support. Pinned prices per
million tokens are input **$0.14**, cached input **$0.05**, and output **$0.28**. The cached-input
price differs from the older Housing snapshot and is therefore pinned separately.

The repo's configured OpenRouter credential authenticated successfully, and the account had
a positive credit balance. These checks do not establish successful generation or available
per-model generation quota; the live admission panel is still required. No key or credential
value is written into this plan or into evidence.

## Admission and stopping rules

Use `--provider deepseek --control-effort none --treatment-effort low` with the same master
seed, inference seed, and approved total spend limit in both `admission` and `sample` modes.
Every admission cell must have a replayed included receipt, four or more external buyer calls,
the expected requested seed/effort, the exact canonical model and selected route, no scripted
provider evidence, and known billing. The off condition must not report reasoning tokens.
Economic success is not an admission filter: a valid poor decision remains a valid measurement.

The sample entry point refuses to run without this admission evidence. Operational failures
remain exclusions, not zero payoffs. A three-consecutive-failure circuit, recorded-cost stop,
and unknown-billing stop protect the batch. Recorded spend is checked after each episode;
one in-flight episode can cross the limit, so this is not a provider-side hard billing cap.
No automatic rerun of a previously attempted cell is permitted.

Once the total spend limit is supplied, seal the study manifest in a new output directory,
run admission, and proceed to the sample only if admission passes. Report complete world
clusters alongside the 600 episode statuses. Do not top up the sample based on significance.

## Implementation validation

Commits `35b8e97` and `b2b75b8` add configurable pinned RFQ routes, the DeepSeek admission
path, and independent selected-route checks in shared batch metrics. New tests were observed
failing before implementation; all 36 focused procurement/experiment/batch tests passed.
The full offline regression suite passed **679 tests, with 3 skipped and 1 expected failure**
in 116.54 seconds. No paid DeepSeek admission or sample calls have been made under this plan.
