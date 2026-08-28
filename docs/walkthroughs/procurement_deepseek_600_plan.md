# DeepSeek procurement: 600-episode run plan

Date: 2026-08-28. Request: run 600 procurement episodes with DeepSeek.
Status: user approved $5 total and continuation to the final result. Three admission
studies are preserved below; none launched the sample. A common-temperature repair
is awaiting a fresh admission with all earlier spend carried forward.

## Locked comparison and measurement

| Parameter | Setting |
| --- | --- |
| Model | `deepseek/deepseek-v4-flash-0731` |
| Canonical revision | `deepseek/deepseek-v4-flash-20260731` |
| Route | OpenRouter → Parasail, fp8, no fallback |
| Conditions | `reasoning_none_v1` versus `reasoning_low_v1`, matching Housing |
| Sample | 100 generated worlds × 2 conditions × 3 nested repeats = 600 episodes |
| Admission | 3 separate worlds × 2 conditions × 1 repeat = 6 additional episodes |
| Fresh repaired-study master seed | `2026082802` (initial failed admission used `2026082801`) |
| Inference seed base | `20260828`, paired across conditions within each world/repeat |
| Primary endpoint | Treatment-minus-control mean normalized buyer surplus, `R/U` |
| Inference | Whole-world cluster bootstrap; exact declared panel and missingness support |
| Verifier | `objective_reference`, deterministic objective upper bound |
| Spending limit | User-approved $5 total; includes admission plus sample and any later repair probes |
| Current buyer limits, both conditions | 32,768 output tokens; one length retry at 65,536; 1,800-second call timeout; $0.04 post-call profile stop |
| Next admission sampling, both conditions | Temperature 1.0, top-p 1.0; differs from Housing's temperature 0 |
| Repaired dispatch | Bounded waves, maximum 16 episodes; $0.40 reserved for every in-flight episode |

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

Seal the study manifest in a new output directory, run admission, and proceed to the
sample only if admission passes. Report complete world
clusters alongside the 600 episode statuses. Do not top up the sample based on significance.

## Implementation validation

Commits `35b8e97` and `b2b75b8` add configurable pinned RFQ routes, the DeepSeek admission
path, and independent selected-route checks in shared batch metrics. New tests were observed
failing before implementation; all 36 focused procurement/experiment/batch tests passed.
The full offline regression suite passed **679 tests, with 3 skipped and 1 expected failure**
in 116.54 seconds. Those offline checks preceded the live admission below; a green regression
suite did not establish that every legal model action path would execute successfully.

## Live admission result, 2026-08-28

The shared failure circuit stopped after **5 of 6 planned admission episodes**: all five
were typed operational exclusions, and the sixth was not attempted. The **600 sample
episodes did not start**; there are no live procurement performance estimates from this run.

- Three low-reasoning episodes exhausted their output ceilings, including the declared
  length-retry policy. Across the run, seven provider calls ended with `length`; request
  ceilings were 2,048 tokens initially and 4,096 on applicable retries.
- Two reasoning-off episodes failed with `phase 'counter' has no eligible actors`.
  The RFQ plugin accepts a legal negotiation `pass` but still transitions to the supplier
  counter phase with an empty actor set. This is an integration failure, not a zero-payoff
  procurement result.
- Fourteen external requests were made: ten low-reasoning and four reasoning-off. Actual
  route metadata verified Parasail and the pinned canonical DeepSeek revision. Billing was
  known for every call; no supplier-private `unit_cost` field appeared in buyer requests.
- Provider-reported response costs sum to **$0.0083390472**. The remaining authorization is
  **$4.9916609528**; a replacement study must carry forward this spend rather than reset the
  user's $5 allowance. Episode-row floating-point summation differed by less than $1e-12.
- All five sealed receipts and 329 events were audited against the original plans. There
  were no additional paid calls during the audit, and the admission process has exited.

Evidence root: `/private/tmp/aeread-procurement-deepseek600.QqG0m7`.
Summary: `admission/summary.json`.
Summary SHA-256: `ccc43ca5397fde5aa10ec1746c3c3a2870360ab61073af390d2d2d385baddc98`.

The next step is to repair and test the RFQ empty-phase path and review the token ceiling,
then create a fresh sealed admission study before any sample run. The failed receipts are
preserved; no source fix or paid restart was made during this run.

## Repaired continuation

The user requested work through to the final result after the initial admission failure.
Commit `6b73908` adds the legal empty-RFQ and empty-counter transitions without relaxing the
shared scheduler contract. Eight regression cases failed before the repair and now reach
replayable terminal scores, including the observed generated admission world.

Commit `ae18fb8` seals explicit, equal buyer runtime ceilings for both reasoning conditions.
Commit `9dc4ed5` adds bounded parallel waves, per-episode budget reservations, no-duplicate
resume, and a failure circuit that remains latched even when later in-flight cells succeed.
All **50 focused RFQ, experiment, and batch tests passed**. The frozen full regression suite
passed **693 tests, with 3 skipped and 1 expected failure**, in 277.95 seconds.

The new evidence directory is `/private/tmp/aeread-procurement-deepseek600-repaired.OTthte`.
Its `authorization.json` carries forward the prior $0.0083390472 charge and sets the new
admission-plus-sample limit to $4.9916609528. The new 100 sample worlds and three admission
worlds are disjoint from both panels in the initial study.

The $0.40 episode reservation exceeds the conservative post-call stop plus two full-context
requests at the pinned prices: `0.04 + 2 * (1048576 * 0.14 + 16384 * 0.28) / 1000000
= 0.34277632`. A read-only live endpoint check verified the 1,048,576-token context limit
and that prompt/completion pricing does not exceed those bounds. Dispatch is reduced when
the remaining budget cannot reserve a full wave. Unknown billing, a reservation breach,
or the failure circuit prevents a subsequent wave; already-started episodes drain to receipts.

### Second admission outcome and final ceiling

The admission at `9dc4ed5` completed five of six episodes. The remaining low-reasoning
episode, world `1172446110`, exhausted its 16,384-token retry and was excluded. Its panel
cost was $0.021089277; no sample was launched. The first two studies together cost
$0.0294283242, leaving **$4.9705716758** of the original authorization.

Commit `9bf15f6` raises the shared initial output ceiling to 32,768, retains one length
retry at 65,536, and passes the 1,800-second timeout through to the OpenRouter SDK call.
Both conditions receive the same ceilings. The $0.40 reservation remains conservative:
`0.04 + 2 * (1048576 * 0.14 + 65536 * 0.28) / 1000000 = 0.37030144`.
The live endpoint advertised a 943,718-token completion maximum, above both requested limits.

The study at `/private/tmp/aeread-procurement-deepseek600-wide.Ejt78y` repeats all six
admission checks on the same three admission worlds. Its 100 sample worlds remain the
unchanged, unattempted panel from master seed `2026082802` until the gate passes. The
multi-study `authorization.json` retains both earlier summary hashes and their charges.

At `46f3fc3`, all **698 tests passed, with 3 skipped and 1 expected failure**, in 118.93
seconds. The independent report checker has five unit tests covering world-cluster
arithmetic, missingness, duplicate identities, scripted-evidence rejection, and prior-spend
reconciliation. Historical admission replay used the original `fb22aa3` and `9dc4ed5`
sources: all 11 receipts validated, all 33 checked files were unchanged, and no provider
calls were made during those audits.

### Third admission outcome and sampling hypothesis

The wide-ceiling admission completed four of six episodes; two low-reasoning
episodes exhausted their 65,536-token retries. Its cost was $0.0679009518, bringing
all three studies to **$0.097329276** and leaving **$4.902670724**. Six receipts
replayed against the frozen source; all 18 checked files were unchanged. The
temporary operator sample-lock hold was released after the launcher exited.
No sample call was made. Summary SHA-256:
`8e96d395619680b906c01592b5355c91c47a4c24dd34898cbbb6501ffc2918eb`.

The next admission changes only the common buyer temperature to 1.0, following
the official open-weight model-card default. This is a hypothesis about the
third-party route, not a claim about DeepSeek's native API, which ignores sampling
in thinking mode. See the [sampling walkthrough](procurement_sampling_admission.md).
The same three admission worlds and untouched 100-world sample remain frozen.
Six targeted checks failed before implementation; 95 focused checks then passed.
The full offline regression passed **701 tests, with 3 skipped and 1 expected
failure**, in 119.22 seconds. The standalone historical budget/sensitivity checker
at the third study's `verify_sampling_numbers.py` also passed without provider calls.
