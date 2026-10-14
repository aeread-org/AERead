# housing_lemons_price_v14_controls

Scripted seat-0 controls on every world of the v14 price pack, both landlord arms, played offline through the sealed market, beside the ceiling and the three models' published values. A derived analysis: `python -m aeread_families.housing.price_controls`; `--check` regenerates these bytes. The reference and the ceiling reproduce the v14 bundle's `reference_net` and `ceiling` in all 600 cells.

Dollars per world (mean of the two arms), main pack (260 worlds). Primary v1 is the v14 primary measure; v2 is `price_reply_posterior`. Shares of the ceiling follow the $0-ceiling rule below.

| Seat 0 | Realized | Primary v1 | Primary v2 | Share of ceiling | Favourite lemon, realized | Favourite sound, realized | Holdout, realized |
|---|---|---|---|---|---|---|---|
| `pass` (no-op) | +0 | +0 | +0 | 0% | +0 | +0 | +0 |
| `sign_anything` (weak) | -349 | -80 | -80 | -92% | -577 | +410 | -356 |
| `inspect_then_sign` (baseline) | +145 | +145 | +145 | 39% | +72 | +385 | +148 |
| `inspect_lowball` (reference) | +292 | +292 | +292 | 79% | +255 | +414 | +280 |
| GLM (published) | +132 | +137 | see `housing_lemons_price_v14_reply_conditioned` | 36% | +69 | +345 | +81 |
| Luna (published) | +136 | +130 | see `housing_lemons_price_v14_reply_conditioned` | 37% | +55 | +405 | +138 |
| Gemini (published) | +211 | +211 | see `housing_lemons_price_v14_reply_conditioned` | 57% | +153 | +397 | +188 |
| ceiling | +370 | | | 100% | +349 | +440 | +353 |

Model minus control on the v14 primary, paired by world, main pack, 95% Student-t: GLM minus `sign_anything` +216 [+188, +244], minus `pass` +137 [+111, +162]; Luna minus `sign_anything` +210 [+181, +238], minus `pass` +130 [+104, +156]; Gemini minus `sign_anything` +292 [+268, +316], minus `pass` +211 [+188, +233].

**$0-ceiling rule** (`housing_price_zero_ceiling_v1`): a cell whose ceiling is $0 stays in every net measure, per-world mean and contrast, is excluded from the numerator and denominator of every share of the ceiling, and is counted here. On this pack: 10 cells, 300002 pooled, 300055 pooled, 300073 pooled, 300308 pooled, 300346 pooled, 300357 pooled, 300409 pooled, 400007 pooled, 400019 pooled, 400061 pooled, all pooled-arm favourite-lemon (7 main, 3 holdout). The v14 bundle's `realized_share_of_ceiling` kept them in the ratio; `reports/controls.json` gives both per model.

Not included: the best-informed tenant (`price_best_informed`), which is on branch `codex/housing-best-informed` and not on this branch. The `sign_anything_total` and `reference_total` in the v14 receipts are six-tenant figures from a market without outside demand, not these seat-0 controls (HL-D-09).

Files: `tables/cells.jsonl` (one row per world and arm: every control under every measure, and the ceiling), `reports/controls.json` (every scope: intervals, shares under the rule, the models beside the controls).
