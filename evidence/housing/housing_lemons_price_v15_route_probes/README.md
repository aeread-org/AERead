# Housing v15: one-call route probes (plan Section 7, addendum A)

One paid call per identity through its exact route, written by `tools/housing/price_v15_route_probe.py`:
structured output under a strict schema and the reasoning tokens the provider reports.

| Identity | Probe | Structured output | Reasoning tokens |
|---|---|---|---|
| `housing_lemons_price_v15_glm53_flash_nearai` | before its admission (addendum A) | ok | 198 at `low` |
| `housing_lemons_price_v15_glm53_flash_novita` | with `require_parameters`, as the client sends it | refused at the parameter filter (HL-J-15) | |
| `housing_lemons_price_v15_gpt6_luna` | after the run, recorded only (cannot change Gate 4) | ok | 100 at `low` |
| `housing_lemons_price_v15_gemini38_flash` | after the run, recorded only | ok | 0 at `minimal` |

The Luna and Gemini probes here were sent before the tool set `require_parameters`; their routes carried every v15
cell, so the client's filter admits them. The branch `codex/housing-v15-probe` holds the probe rebuilt to the sealed
request digest and the audit of every sealed seat-0 call's reasoning count (HL-J-16, RN-T-07).
