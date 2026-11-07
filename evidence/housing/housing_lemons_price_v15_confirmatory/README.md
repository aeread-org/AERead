# housing_lemons_price_v15_confirmatory

Housing lemons price with outside demand, v15 confirmatory (plan `docs/families/housing/price_confirmatory_v15_plan.md`,
amendments 1 to 5). Seat 0 against scripted outside demand and both landlord kinds; measure v2, mean of the two
landlord arms per world; main pack 260 worlds, holdout 40 at outside-demand rate 0.3. 1720 cells, 1720 completed.

| Contrast (main pack) | $ per world [95%] |
|---|---|
| P: Gemini 3.8 Flash − GPT-6 Luna | +48.8 [34.9, 62.7] |
| A/A: Luna − its twin | -5.0 [-18.8, 8.9] |
| B: gemini - inspect_then_sign | +90.0 [76.0, 104.0] |
| B: luna - inspect_then_sign | +41.2 [25.3, 57.1] |
| G: gemini - best_informed | -65.4 [-77.1, -53.7] |
| G: luna - best_informed | -114.2 [-130.5, -97.9] |
| R: gemini - inspect_lowball | -51.1 [-64.0, -38.3] |
| R: luna - inspect_lowball | -99.9 [-116.0, -83.8] |

`tables/cells.jsonl`: one row per cell with seat 0's primary, metrics and references from its receipt;
`receipts/projections.jsonl`: each receipt's projection; `reports/analysis.json`: the declared analysis
(`tools/housing/price_v15_analysis.py`). Replay: `aeread verify-replay <bundle> --run-root runs/housing_v15/<id>
--setup aeread_families.housing.price_publication:replay_setup`.
