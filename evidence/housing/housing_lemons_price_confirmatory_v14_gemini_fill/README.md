# housing_lemons_price_confirmatory_v14_gemini_fill

The declared fill of the 36 Gemini cells the OpenRouter account refused in `housing_lemons_price_confirmatory_v14` (HL-O-21), run under its own identity by the owner's decision of 2026-10-06, an exception to 'a failed cell is never selectively rerun'. The v14 bundle is unchanged; this is a labelled sensitivity check beside it.

Fill cells completed: 36 of 36. Reproducibility: 12 of 12 cells v14 had completed, run again, give the same seat-0 outcome.

| Pair (v14 analysis with the fill) | Main pack | Holm p | Holdout |
|---|---|---|---|
| `housing_lemons_price_confirmatory_v14_glm53_flash_nextbit - housing_lemons_price_confirmatory_v14_gpt6_luna` | +7 [-16, +29] | 0.562 | -40 [-106, +26] |
| `housing_lemons_price_confirmatory_v14_glm53_flash_nextbit - housing_lemons_price_confirmatory_v14_gemini38_flash` | -74 [-95, -53] | 5.44e-11 | -105 [-164, -46] |
| `housing_lemons_price_confirmatory_v14_gpt6_luna - housing_lemons_price_confirmatory_v14_gemini38_flash` | -81 [-98, -63] | 8.05e-17 | -65 [-106, -23] |

Files: `tables/cells.jsonl` (all 48 fill cells, `role` filled or repeat), `reports/sensitivity.json`, `reports/contract.json`. `publication_manifest.json` digests every file and binds the bundle to its source receipts.
