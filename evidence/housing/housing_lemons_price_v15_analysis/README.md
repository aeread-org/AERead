# Housing v15: the confirmatory analysis

The declared contrasts of `docs/families/housing/price_confirmatory_v15_plan.md` (Section 5, amendments 2 and 5),
computed once by `tools/housing/price_v15_analysis.py` (committed at 4f219b13, before any confirmatory result; a
serialization fix at cb552908 changed no computation) from the sealed receipts under `runs/housing_v15/` and the pack's
published controls. Write-up: `docs/families/housing/price_confirmatory_v15_results.md`. Bundle:
`evidence/housing/housing_lemons_price_v15_confirmatory/`.

| | Contrast (main pack, 260 worlds) | $ a world [95%] |
|---|---|---|
| P | Gemini 3.8 Flash − GPT-6 Luna | +48.8 [34.9, 62.7] |
| A/A | Luna − its twin | −5.0 [−18.8, 8.9] |
| B1 / B2 | each − `inspect_then_sign` | +90.0 [76.0, 104.0] / +41.2 [25.3, 57.1] |
| G1 / G2 | each − best-informed tenant | −65.4 / −114.2 |
| R1 / R2 | each − `inspect_lowball` | −51.1 / −99.9 |

Rebuild: `PYTHONPATH=src python tools/housing/price_v15_analysis.py runs/housing_v15 OUT.json`.
