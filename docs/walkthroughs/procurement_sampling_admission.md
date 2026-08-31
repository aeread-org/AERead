# Walkthrough: DeepSeek procurement sampling admission

Date: 2026-08-28. Entry point: repetitive output in two live admission failures.
Proposed action: request temperature 1.0 equally in the off and low conditions, then
repeat the six admission checks before attempting the unchanged 600-episode sample.
This is an operational hypothesis, not a demonstrated performance improvement.

## Step 1: Data sources

The third admission at `/private/tmp/aeread-procurement-deepseek600-wide.Ejt78y`
used temperature 0, 32,768 initial output tokens and one 65,536-token length retry.
Four of six episodes completed. Both remaining low-reasoning episodes exhausted
the retry; no sample episodes ran. All six receipts replayed against the frozen
source; 18 result/receipt/event files were unchanged by the audit.

Two initial truncated responses had zero visible answer characters. Their
nonempty-line counts were 544 and 399, with 54 and 35 distinct lines respectively.
The duplicate-line fractions are `1 - distinct / total`: about 90.1% and 91.2%.
These observations diagnose repetitive generation, not its cause or prevalence.
The longer available Housing experiment had many successful temperature-0
reasoning episodes, so this is not evidence that temperature 0 always fails.

Official sources checked on 2026-08-28:

- [DeepSeek V4 Flash model card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash/blob/main/README.md)
  recommends `temperature = 1.0, top_p = 1.0` for locally deployed weights.
- [Native API thinking guide](https://api-docs.deepseek.com/guides/thinking_mode/)
  says thinking mode ignores temperature and top-p. That is not this third-party route.
- [OpenRouter endpoint catalog](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash-0731/endpoints)
  advertises Parasail temperature/top-p support, fp8, a 1,048,576-token context,
  and the pinned input/output prices of $0.14/$0.28 per million tokens.

### DANGER ZONE D1

HIGH — two selected failures do not establish a causal sampling problem; bias is
toward overconfidently treating an implementation hypothesis as a model finding.

## Step 2: Assumptions

- Data-derived: all three admissions cost $0.097329276 in total; $4.902670724
  remains of the original $5 authorization. No admission charge is discarded.
- Manufacturer default: temperature 1.0 is from the open-weight model card,
  not fitted to procurement rewards. Top-p remains 1.0.
- Analyst judgment: the third-party hosted-weight route may honor sampling and
  avoid a greedy repetition loop. Native API guidance cannot establish this.
- Fixed design: both arms receive the same sampling, output, timeout and spend
  limits; only requested reasoning effort differs. Suppliers stay controlled/local.

### DANGER ZONE D2

HIGH — advertised support does not prove actual decoding behavior; bias direction
is unknown. Admission verifies requested temperature, not the provider's hidden sampler.

## Step 3: Model and gates

There is no reward optimization here. Admission requires six included, replayed,
native-provider episodes with the correct request, route, revision, seed, effort,
known billing and no scripted buyer calls. A valid poor decision still passes.
Both arms use the same three admission worlds. All 100 sample worlds are untouched.
Frozen study/source hashes prevent changing sampling inside an existing study.

The per-episode dispatch reservation is conservative under the pinned route:

`0.04 + 2 * (1048576 * 0.14 + 65536 * 0.28) / 1000000 = 0.37030144 < 0.40`.

It covers the post-call profile stop plus a full-context call and its length retry.
The guard reserves this amount before dispatch and accounts for drained calls;
unknown billing stops further dispatch. It is not a provider-side billing limit.

### DANGER ZONE D3

HIGH — changing temperature means this is not an exact replication of Housing's
temperature-0 settings; bias direction is unknown for cross-domain comparisons.
Repeated admission changes also prevent interpreting admission success rates as
an unbiased model benchmark. Confirmatory results must use the untouched sample.

## Step 4: Decomposition and sensitivity

Provider-free profile tests cover temperatures 0.5, 1.0 and 1.5 (the proposed
value plus/minus 50%): each is sealed in the buyer plan while supplier temperature
stays zero. These tests say nothing about live reward or completion sensitivity.

Independent Decimal calculations for the same reservation expression:

| Varied input | Minus 50% | Base | Plus 50% |
| --- | ---: | ---: | ---: |
| Output allowance | $0.35195136 | $0.37030144 | $0.38865152 |
| Context allowance | $0.22350080 | $0.37030144 | $0.51710208 |
| Both token prices | $0.20515072 | $0.37030144 | $0.53545216 |

Context/pricing pins, not temperature, drive this safety bound. Higher-price
stress cases are not authorized routes; maximum-price routing rejects them.

### DANGER ZONE D4

CRITICAL — unverified context or pricing would invalidate the reservation and
bias costs downward. Recheck the pinned endpoint before paid dispatch. Never
reset the $5 ledger, silently rerun attempted cells, or select sample outcomes.

## Danger zones summary

| Risk | Severity | Bias direction |
| --- | --- | --- |
| Selected repetitive responses do not prove cause | HIGH | Overstates certainty |
| Hidden provider sampler may ignore requests | HIGH | Unknown |
| Changed temperature breaks exact Housing comparability | HIGH | Unknown |
| Invalid route/cost assumptions or reset ledger | CRITICAL | Understates spend |

## Load-bearing assumptions

1. Parasail actually supports useful non-greedy sampling; verify operationally.
2. The unchanged unseen world panel is not selected using admission rewards.
3. Prices/context stay within the reservation assumptions and all spend is known.

## Invariants and validation

- Equal buyer settings across arms; local supplier behavior and private costs unchanged.
- Six receipts must pass before the frozen 600-sample schedule can dispatch.
- All historical charges survive; total authorization remains $5, not $5 per study.
- Missing episodes remain exclusions, not zero scores; world-level inference only.
- Parameter provenance, units, boundary sensitivity and longer-history counterevidence
  are checked above. Financial allocation-specific proxy/scenario checks do not apply.

Honest one-sentence conclusion: trying the manufacturer's sampling default may
resolve repetition, but only the new admission can establish that it runs reliably.
