# DeepSeek procurement RFQ: 600-cell live result

Date: 2026-08-30. Status: complete.

This synthetic B2B procurement experiment compared DeepSeek V4 Flash with reasoning
disabled against the same model with low reasoning. The shared runner attempted all
600 planned cells: 100 generated worlds, two conditions, and three nested replicates.

## Result

Low reasoning increased mean normalized buyer surplus by **0.3088** relative to
reasoning disabled. The whole-world cluster-bootstrap 95% interval was
**[0.2632, 0.3538]**. The paired-t interval was [0.2630, 0.3546], and the declared
outcome-support bounds under observed missingness were [0.2860, 0.3454].

| Measure | Reasoning disabled | Low reasoning |
| --- | ---: | ---: |
| Mean normalized buyer surplus | -0.0304 | 0.2784 |
| Operational exclusions | 0 | 17 |

The result supports a positive treatment-minus-control effect within this synthetic
RFQ distribution. It does not establish performance in real procurement, with real
vendors, or on another model route.

## Completeness and limitation

The runner sealed 583 included cells and 17 operational exclusions, with no
unattempted cells. Eighty-seven of 100 worlds retained all expected observations, so
the preregistered planning target of 90 complete worlds was not met. All 17 exclusions
occurred in the low-reasoning condition. The missingness-support interval remains above
zero, but the asymmetric operational failure rate is a material deployment caveat and
must not be hidden by the favorable performance estimate.

Inference resampled whole world seeds with 10,000 bootstrap draws. Replicates are
nested observations, not independent clusters. Failed episodes remained exclusions;
they were not scored as zero outcomes and were not replaced to improve significance.

## Provider and execution pins

- Requested model: `deepseek/deepseek-v4-flash-0731`
- Resolved model: `deepseek/deepseek-v4-flash-20260731`
- Route: OpenRouter to Parasail fp8, fallback disabled
- Conditions: `reasoning_none_v1` versus `reasoning_low_v1`
- Master seed: `2026082901`
- Inference seed base: `20260829`
- Temperature: 1.0
- Output ceiling: 32,768 tokens
- Launcher cap: four new cells per invocation

The launcher used bounded four-cell waves even though the study metadata permits a
higher scheduler concurrency. This bounded the exposure of calls whose billing state
could become unknown during long provider waits.

## Billing and recovery

Thirteen timed-out calls had potentially unknown billing across the immutable recovery
chain. Each was acknowledged and reserved rather than automatically rerun. The final
verifier found zero unresolved unknown-billing calls.

- Known batch cost: $1.956692331
- Known cost including admission: $1.976871303
- Unknown-cost reserve: $0.52
- Prior replacement reserve: $0.413345078
- All-in conservative spend: $2.910216381
- Approved cap: $5.00
- Remaining authorization: $2.089783619

The machine-readable companion
[`procurement_deepseek_600_2026-08-30.json`](procurement_deepseek_600_2026-08-30.json)
records the exact estimates, execution pins, costs, RunPlan IDs, and SHA-256 commitments
for the final summary and recovery manifests. Raw episode evidence is intentionally not
committed because it includes a large generated transcript corpus; the committed hashes
bind this report to the sealed local artifacts.
