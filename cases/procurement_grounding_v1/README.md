# Procurement grounding v1

This development family tests whether an analyst can turn mixed-quality sourcing
records into a procurement-readiness decision without collapsing unlike denominators
or fabricating commercial certainty.

The first case freezes the 31 August 2026 workbook derived from:

- the 231-project community corpus;
- the original exact-variant 1688 findings/rejections screen;
- recent 1688 search cards, outreach assignments, conversations, and quote rows; and
- the Alibaba resume queue and structured conversation ledger.

The case is a deterministic `property_or_answer` task, not a landed-cost optimizer.
Displayed marketplace prices, search cards, and reply messages are not treated as
verified offers. A bulk-order-ready answer is therefore an invalid action. Valid
answers receive a 0–100 deterministic score across source counts, priority selection,
supplier-distribution interpretation, evidence boundaries, and next-step controls.

Run an already-produced model response through the native shared runner:

```bash
python -m aeread_families.procurement_grounding \
  --response response.json \
  --run-root /tmp/aeread-procurement-grounding
```

The command emits the scored family outcome and writes AERead's canonical action and
evidence event chain. The test suite exercises a strong response, a structurally valid
but poor response, and an invalid premature-order response.

The case payload contains an evaluator-only oracle. `observe()` exposes only the
snapshot metadata and `visible_evidence`; leakage tests cover that boundary.

## OpenRouter bake-off

Print the pinned candidate matrix and conservative spend ceiling without making live
requests:

```bash
python -m aeread_families.procurement_grounding.bakeoff
```

Run the live comparison only after setting `OPENROUTER_API_KEY`:

```bash
python -m aeread_families.procurement_grounding.bakeoff \
  --execute \
  --run-root runs/procurement-grounding-openrouter \
  --replicates 3 \
  --warmups 1 \
  --concurrency 4 \
  --max-spend-usd 0.15
```

Run only the active open-weight matrix, which excludes previously rejected slow
routes:

```bash
python -m aeread_families.procurement_grounding.bakeoff \
  --open-weight-only \
  --execute \
  --run-root runs/procurement-grounding-open-weight \
  --replicates 3 \
  --warmups 1 \
  --concurrency 4 \
  --max-spend-usd 0.05
```

The runner verifies the live endpoint catalog before dispatch, pins provider,
revision, quantization, and price ceilings, disables fallbacks and exact-response
caching, warms each standard model before parallel fan-out, and records score,
latency, token use, provider prompt-cache hits, and cost. Discounted batch variants
use OpenRouter's asynchronous Batch API as one grouped job and are evaluated as an
offline-throughput lane rather than as interactive requests.

The dated three-replicate development bake-off selected `gpt56_luna` as the default
interactive route: 0.987 mean score, 6.94-second median latency, and $0.00087 median
cost after a cache-seeding warmup. `gemini37_flash` was the fastest route at 3.14
seconds and a perfect score, but cost $0.00629 per result. Its batch variant also
scored perfectly at $0.00170 per result, but the grouped job took about 485 seconds,
so it is reserved for deferred bulk work. See the committed
[`results.json`](../../evidence/procurement_grounding_openrouter_bakeoff_2026-08-31/reports/results.json)
for the complete protocol, failures, limitations, and hashes of the local raw logs.

The follow-up open-weight bake-off excludes DeepSeek from active dispatch. It selected
`glm53_flash` as the open-source route with 3/3 perfect measured responses, a
9.64-second median, and $0.00037 median cost. `mistral_small4` also passed all three
measured calls but had one malformed warmup response, a 21.81-second median, and
$0.00140 median cost. Qwen 3.8 Flash and MiniMax M3 failed the measured runtime
contract. See
[`results.json`](../../evidence/procurement_grounding_open_weight_bakeoff_2026-08-31/reports/results.json)
for license classes, endpoint pins, failure classes, limitations, and the raw-result
hash.

## Harness probe

The paired harness probe holds the frozen case, GLM 5.3 Flash DeepInfra FP8 route,
inference seeds, retry policy, and token budgets fixed. It varies only the AERead
Minimal Chat and LangChain Provider Strategy execution layers. Planning is offline:

```bash
python -m aeread_families.procurement_grounding.harness_bakeoff \
  --run-root runs/procurement-grounding-harness-probe \
  --replicates 3
```

Install the exact optional framework versions and set `OPENROUTER_API_KEY` locally
before adding `--execute`. The runner preflights the pinned endpoint, enforces a
conservative spend ceiling, rotates arm order across paired seeds, writes atomic
per-run records, and requires receipt replay for every completed result. These are
descriptive repeated-inference measurements on one frozen case, not independent
procurement cases or population-level evidence.

The first live probe and a separately labeled paced diagnostic found perfect
scores on every completed call, but DeepInfra shared-pool overload excluded seven
of twelve planned calls. The two complete pairs favored AERead Minimal Chat on
latency and LangChain slightly on token cost. See
[`summary.md`](../../evidence/procurement_grounding_harness_probe_2026-08-31/reports/summary.md)
for the measurement boundary, receipt audit, hashes, and interpretation limits.
