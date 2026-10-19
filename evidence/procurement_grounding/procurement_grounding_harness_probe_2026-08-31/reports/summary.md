# Procurement Grounding Harness Probe, 2026-08-31

## Case and measurement design

This is a single-turn, structured procurement-grounding case over one frozen
source snapshot containing 231 project records. The 231 projects are evidence
inside one case, not 231 statistically independent benchmark cases. One analyst
submits one strict JSON report. The environment allows no ordering, supplier
messages, tools, memory, or hidden-oracle access.

The evaluator is a deterministic canonical-reference scorer, not a learned
classifier or an LLM judge. Its primary estimand is
`procurement_grounding_accuracy`, measured as a ratio from 0 to 1 over the
terminal report. The 100-point rubric contains:

- source counts: 26 points
- priority families: 24 points
- supplier distribution: 10 points
- evidence interpretations: 15 points
- procurement controls and scope: 15 points
- readiness decision and next steps: 10 points

The derived quality bands are `strong` at 85 points or above, `adequate` at 60
points or above, and `valid_but_poor` below 60. An invalid model submission
receives zero credit as an included benchmark outcome. Provider and execution
failures are instead sealed as excluded `invalid_measurement` receipts.

## Harness treatment

The probe held the case, GLM 5.3 Flash revision, DeepInfra FP8 endpoint,
inference seeds, temperature, token budgets, price ceilings, and one-attempt
retry policy fixed. Only the execution layer varied:

- `aeread_minimal_chat_v1`
- `langchain_provider_strategy_v1`

Calls were sequential and arm order rotated across seeds. Exact-response caching
was disabled. Provider prompt caching remained observable but automatic.

## Results

Two separately labeled three-pair runs were executed. The second added five
seconds of neutral pacing after the first run exposed upstream overload.

- planned calls: 12
- completed calls: 5
- excluded calls: 7
- completed paired observations: 2
- completed-call score: 1.0 for both harnesses in every observation
- provider-reported completed-call spend: $0.00191824875
- prompt-cache hits: 0
- model requests per completed call: 1

Across the two complete pairs:

| Harness | Mean latency | Mean cost | Mean output tokens |
|---|---:|---:|---:|
| AERead Minimal Chat | 14.7384 s | $0.00040201425 | 709 |
| LangChain Provider Strategy | 20.3589 s | $0.00037157175 | 586 |

The paired mean score difference was 0.0. LangChain was 38.1% slower and 7.6%
less expensive, an absolute mean saving of about $0.0000304 per completed call.
With two complete pairs on one case, these are descriptive observations only.

All seven exclusions were OpenRouter 429 responses from the DeepInfra shared
pool with upstream `engine_overloaded`. Both harnesses were affected. The
completion counts therefore do not identify a harness reliability difference,
and five-second pacing did not resolve route availability.

## Audit and local evidence

All 12 durable receipts passed independent audit: 5 included `ok` receipts and
7 excluded `invalid_measurement` receipts. Raw provider responses remain in the
ignored local output tree and are not committed.

- original summary artifact field SHA-256:
  `d2989bf418bf4e5f1907cbdc8195ec615aca580a00d0e7f5bb69821215170d34`
- original summary file SHA-256:
  `a28e2d9c30aff8c663c72f78598dc384be4f6f095d235f22bf25a26e8ec944b6`
- paced summary artifact field SHA-256:
  `b05e337bc484a476e5af66d0903f417605e65a19b86d40fe13b82c6bd55b10e1`
- paced summary file SHA-256:
  `b2b6dc526040b44e8bf3596d3c48ca7ed2c490b9a080029e9b83cda71ba3a6ed`

Development recommendation: retain AERead Minimal Chat as the default
procurement harness. Keep LangChain as a validation arm; the observed fractional
cost saving does not offset its latency and dependency overhead in this probe.
Route reliability should be evaluated separately on a fresh pinned provider
panel rather than attributed to either harness.
