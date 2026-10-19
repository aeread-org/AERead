# housing_lemons_price_v15_glm_addendum

Housing v15 addendum A: GLM 5.3 Flash on Near AI fp8 as seat 0, on v15's main pack (260 worlds) and holdout
(40), v15's controls, notice v5 and seat-0 scorer (plan `docs/families/housing/price_confirmatory_v15_plan.md`,
Addendum A and its amendments 1 and 2). Reported beside v15, outside its Holm family; it changes nothing in
v15's results. 600 cells, 600 completed.

| Row (main pack) | $ per world [95%] |
|---|---|
| B3: GLM − `inspect_then_sign` | +13.8 [-8.4, 36.1]; at 1 − 0.05/3 +13.8 [-13.4, 41.0]: does not beat the baseline |
| G3: GLM − best-informed tenant | -141.6 [-163.0, -120.2] |
| R3: GLM − `inspect_lowball` | -127.3 [-149.4, -105.2] |
| GLM - Gemini (descriptive) | -76.2 [-93.8, -58.5] |
| GLM - Luna (descriptive) | -27.4 [-49.9, -5.0] |

GLM's mean seat-0 value: main 165.85, holdout 207.00 a world.

`tables/cells.jsonl`, `receipts/projections.jsonl` and `reports/contracts.json` as in v15's bundle;
`reports/analysis.json`: the declared rows (`tools/housing/price_v15_addendum_analysis.py`). Replay:
`aeread verify-replay <bundle> --run-root runs/housing_v15/housing_lemons_price_v15_glm53_flash_nearai
--setup aeread_families.housing.price_publication:replay_setup`.
