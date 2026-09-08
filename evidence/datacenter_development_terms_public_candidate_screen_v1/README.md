# Public held-out candidate-screen diagnostic v1

This sanitized campaign tests whether a general cross-clause candidate-screen
instruction repairs the integrated Denton land/power/construction failure found
in the prior composition diagnostic. Baseline, affirm-only, and candidate-screen
wording use the same evidence and hidden oracle, three fresh inference seeds,
three pinned Apache-2.0 open-weight model/provider routes, the minimal-chat
harness, a 900-token output limit, and no retries, cache, or provider fallback.

Twenty-two of 27 cells completed, were included, route-verified, and replayed.
All five operational exclusions were GPT-OSS calls: three rate limits and two
provider-contract failures. They remain missing rather than zero. Successful-call
cost is a $0.00448640775 lower bound.

The predeclared primary Qwen contrast is fully reportable across three pairs.
Candidate screening reduced forbidden selections by one on average, but every
candidate-screen output still selected at least one forbidden action. Baseline
and candidate-screen hard-gate passage were both 0%, with zero rescues, zero
regressions, and mean score delta 0. The instruction therefore did not repair
Qwen's integrated-clause classification failure on these held-out seeds.

The secondary Mistral contrast was harmful: hard-gate passage fell from 100% to
33.3%, with two regressions and mean score delta -0.6444. The candidate-screen
outputs also omitted all required actions. GPT-OSS has no reportable primary
pair because all three candidate-screen calls failed operationally.

This negative result argues against further sentence-level prompt tuning as the
next intervention for this case. A typed two-stage candidate-classification
interface or model/data intervention is the higher-value follow-up. The result
is still a single-source, three-seed diagnostic; it does not establish a
population causal effect, project generalization, inferential model ranking, or
a winner. Raw prompts, provider payloads, reasoning, complete receipts, and
failure messages remain in ignored local run state.
