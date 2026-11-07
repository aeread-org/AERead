# Housing v15 addendum A: the declared rows

The rows addendum A of `docs/families/housing/price_confirmatory_v15_plan.md` declares for GLM 5.3 Flash on Near AI
fp8, computed once by `tools/housing/price_v15_addendum_analysis.py` (committed at c0a43f16, before any of its
results) from the sealed receipts under `runs/housing_v15/` and the pack's published controls. Outside v15's Holm
family; v15's results are unchanged. Write-up: `docs/families/housing/price_confirmatory_v15_results.md`, "Addendum A
results". Bundle: `evidence/housing/housing_lemons_price_v15_glm_addendum/`.

| | Row (main pack, 260 worlds) | $ a world [95%] |
|---|---|---|
| B3 | GLM − `inspect_then_sign` | +13.8 [−8.4, 36.1]; at 1 − 0.05/3 [−13.4, 41.0]: does not beat the baseline |
| G3 | GLM − best-informed tenant | −141.6 [−163.0, −120.2] |
| R3 | GLM − `inspect_lowball` | −127.3 [−149.4, −105.2] |
| | GLM − Gemini 3.8 Flash (descriptive) | −76.2 [−93.8, −58.5] |
| | GLM − GPT-6 Luna (descriptive) | −27.4 [−49.9, −5.0] |

Rebuild: `PYTHONPATH=src python tools/housing/price_v15_addendum_analysis.py runs/housing_v15 OUT.json`.
