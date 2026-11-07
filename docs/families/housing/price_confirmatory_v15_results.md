# Lemons price with outside demand: v15 confirmatory results

**Status:** the declared analysis of [price_confirmatory_v15_plan.md](price_confirmatory_v15_plan.md) (amendments 1 to
5), committed before any confirmatory result (`tools/housing/price_v15_analysis.py`, 4f219b13) and run once on
2026-10-19. Bundle [`evidence/housing/housing_lemons_price_v15_confirmatory/`](../../../evidence/housing/housing_lemons_price_v15_confirmatory/);
development evidence (admissions, pilot) in `housing_lemons_price_v15_admission_and_pilot`.

## Answer

Both remaining models beat the simple baseline, Gemini 3.8 Flash out-earns GPT-6 Luna by about $49 a world, and both
stay well below the reachable reference and the best-informed tenant. Main pack, 260 worlds, seat 0's net under
measure v2, the mean of the two landlord arms, $ a world:

| | Contrast | Estimate [95%] | Reading |
|---|---|---|---|
| P | Gemini − Luna | +48.8 [34.9, 62.7] | found (p = 3.8e-11); not shown to exceed $50 |
| A/A | Luna − its twin (seed 88001) | −5.0 [−18.8, 8.9] | inside ±$50: the band is calibrated |
| B1 | Gemini − `inspect_then_sign` | +90.0 [76.0, 104.0] | beats the baseline (1 − 0.05/2 lower end 74.0; Holm p 1.5e-28) |
| B2 | Luna − `inspect_then_sign` | +41.2 [25.3, 57.1] | beats the baseline (lower end 23.0; Holm p 6.7e-7) |
| G1, G2 | each − the best-informed tenant | Gemini −65.4 [−77.1, −53.7]; Luna −114.2 [−130.5, −97.9] | the gap to the reference |
| R1, R2 | each − `inspect_lowball` (v14's reference) | Gemini −51.1 [−64.0, −38.3]; Luna −99.9 [−116.1, −83.8] | both below v14's reachable rule |

World means: ceiling 370.9, best-informed tenant 307.4, `inspect_lowball` 293.2, Gemini 242.0, Luna 193.3,
`inspect_then_sign` 152.0. Favourite-is-lemon worlds: Gemini 187.8, Luna 127.8; favourite-is-sound: 422.9 and 411.5.
The gap between the models is in the lemon worlds, where Luna signs blind twice as often (230 blind signings in 600
cells against Gemini's 114). Holdout (40 worlds, outside demand at 0.3, its brief saying so): Gemini 267.0, Luna 205.8,
best-informed 336.9; Gemini − Luna +61.2 [19.5, 103.0]. Seat 0 took no invalid action in either model.

## Coverage, cost and checks

- 1,720 of 1,720 cells completed (Luna and Gemini 600 each over both streams, the twin 520); every receipt replayed
  against its sealed events when it was written, and `aeread verify-replay` re-drove the bundle (see the bundle's
  verification line in the QC section). $8.64 at OpenRouter prices (Gemini $7.34, Luna $0.71, twin $0.59); pilot
  $1.08 and admission $0.035 before it.
- Every receipt's reference values equal the pack's published controls (checked for every cell by the analysis).
- GLM 5.3 Flash left at admission: its v14 route no longer exists (NextBit serves fp4, v14 sealed fp8; HL-O-22). The
  pair family is therefore the one pair above, and the A/A twin is Luna's (amendment 5).

## Against v14, descriptively

v15 is not v14 rerun. The pack is screened for worlds where inspecting pays (119 of 437 main seeds failed the
screen), the notice states the landlords' pricing rule, the primary is measure v2 from the start, and the receipts
score seat 0. Under those changes the v14 finding that Luna does not separate from `inspect_then_sign` (−15 [−32, +2])
does not recur: Luna is +41 above it. Which change is responsible is not identified by this design; the told-pricing
notice is the leading candidate, since v14's best-informed tenant analysis put part of the models' gap on
information.

## Addendum A results: GLM 5.3 Flash on Near AI fp8

Addendum A (plan, "Addendum A" and its amendments 1 and 2) added GLM on a comparable route after v15 ran without it.
Its rows were declared before any GLM cell and computed once by `tools/housing/price_v15_addendum_analysis.py`
(c0a43f16, committed before its results). It is outside v15's Holm family and changes nothing in v15's results above.
Bundle [`evidence/housing/housing_lemons_price_v15_glm_addendum/`](../../../evidence/housing/housing_lemons_price_v15_glm_addendum/);
admissions (Novita's refused cells included) in `housing_lemons_price_v15_glm_addendum_admission`. Main pack, 260
worlds, the same measure and arm mean as above, $ a world:

| | Row | Estimate [95%] | Reading |
|---|---|---|---|
| B3 | GLM − `inspect_then_sign` | +13.8 [−8.4, 36.1] | does not beat the baseline (at 1 − 0.05/3: [−13.4, 41.0]) |
| G3 | GLM − the best-informed tenant | −141.6 [−163.0, −120.2] | the gap to the reference |
| R3 | GLM − `inspect_lowball` | −127.3 [−149.4, −105.2] | below v14's reachable rule |
| | GLM − Gemini | −76.2 [−93.8, −58.5] | descriptive |
| | GLM − Luna | −27.4 [−49.9, −5.0] | descriptive |

GLM's world mean is 165.9 on the main pack (Gemini 242.0, Luna 193.3, `inspect_then_sign` 152.0) and 207.0 on the
holdout. It signed blind 146 times in 600 cells (Luna 230, Gemini 114) and is the only model whose seat 0 took invalid
actions (33). 600 of 600 cells completed, $0.39 at Near AI's list price; `aeread verify-replay` on the bundle: 600
verified, 600 scored, 0 differ, 0 missing. The route differs from v14's (NextBit fp8), so nothing here compares with
v14's GLM except descriptively.

## Addendum B results: Sol 6.1 (Codex) and Opus 5.5 (Claude Code)

Declared after addendum A ([plan](price_v15_addendum_b_cli_plan.md), 5515349e), outside v15's Holm family; results in
[price_v15_addendum_b_cli_results.md](price_v15_addendum_b_cli_results.md). Main-pack share of the best-informed value:
Sol 90.4%, Opus 80.4%; both beat `inspect_then_sign` at 1 − 0.05/3; 600 of 600 cells each; verify-replay 1,200 of 1,200.
