# Public matched clause-composition diagnostic v1

This sanitized campaign compares the integrated Denton
land/power/construction case with three separately scored clause mechanisms:
assignment consent, coterminous land and power, and change-order-adjustable GMP.
It runs integrated baseline and affirm-only wording on the mechanism campaign's
same three inference seeds, model/provider routes, harness, 900-token output
budget, timeout, cost limit, and no-retry policy. The 54 decomposed calls are
hash-bridged from the prior mechanism campaign and were not rerun.

Sixteen of 18 new integrated cells completed, were included, route-verified, and
replayed. Two GPT-OSS baseline calls were rate-limited and remain operational
exclusions. Successful-call cost is a $0.003231954 lower bound. Seven of nine
within-integrated wording pairs are reportable.

The wording effect is not monotonic. All three Mistral pairs passed both
conditions with zero score delta. Qwen's baseline passed one of three hard gates,
but all three affirm-only outputs failed; seed 315003 is a hard-gate regression
where two forbidden actions were added. GPT-OSS has one reportable pair, which
was rescued from three forbidden selections and score 0 to no forbidden
selections and score 0.9667; two GPT-OSS pairs are missing.

Fifteen of 18 cross-granularity bundles are reportable. Six are composition
gaps, defined as an integrated hard-gate failure while all three decomposed
mechanisms pass. Qwen accounts for five: its integrated case passes one of six
bundles while all decomposed mechanisms pass five of six. GPT-OSS accounts for
one of four reportable bundles; Mistral has none in five. One inverse,
component-only gap also occurs: Qwen's integrated baseline passes at seed 315003
while the decomposed GMP case fails.

These are descriptive cross-granularity diagnostics, not score contrasts. The
integrated and decomposed tasks use different evidence scopes and response
vocabularies, and all cases share one filing cluster. Results do not establish a
composition causal effect, population effect, project generalization,
inferential model ranking, or winner. Raw prompts, provider payloads, reasoning,
complete receipts, and failure messages remain in ignored local run state.
