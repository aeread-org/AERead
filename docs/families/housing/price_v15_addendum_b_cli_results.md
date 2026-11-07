# Housing v15, addendum B results: Sol 6.1 (Codex) and Opus 5.5 (Claude Code)

Read out as [the plan](price_v15_addendum_b_cli_plan.md) declares (5515349e, before any cell; amendments 1 and 2).
Rows computed once by `tools/housing/price_v15_addendum_b_analysis.py`, committed with the plan. Outside v15's Holm
family; v15's results and addendum A are unchanged. Bundles: [`evidence/housing/housing_lemons_price_v15_cli_addendum/`](../../../evidence/housing/housing_lemons_price_v15_cli_addendum/)
(rows in `housing_lemons_price_v15_cli_addendum_analysis`), admissions in `housing_lemons_price_v15_cli_addendum_admission`.

Main pack, 260 worlds, seat 0's measure-v2 net, the mean of the two landlord arms, $ a world (the best-informed
tenant earns 307.43):

| | Sol 6.1 (Codex) | Opus 5.5 (Claude Code) |
|---|---:|---:|
| Share of the best-informed tenant's value | 90.4% (277.83) | 80.4% (247.10) |
| Favourite a lemon / sound | 85.9% / 100.0% | 71.2% / 100.0% |
| B: − `inspect_then_sign` | +125.8 [111.3, 140.3]; at 1 − 0.05/3 [108.0, 143.5]: beats the baseline | +95.1 [80.9, 109.3]; at 1 − 0.05/3 [77.7, 112.5]: beats the baseline |
| G: − the best-informed tenant | −29.6 [−37.5, −21.7] | −60.3 [−71.2, −49.5] |
| R: − `inspect_lowball` | −15.3 [−24.5, −6.2] | −46.1 [−58.2, −34.0] |
| − Gemini 3.8 Flash | +35.8 [26.9, 44.7] | +5.1 [−0.9, 11.0] |
| − GPT-6 Luna | +84.6 [69.7, 99.4] | +53.8 [40.6, 67.1] |
| − GLM 5.3 Flash (addendum A) | +112.0 [92.6, 131.4] | +81.3 [63.2, 99.3] |
| Holdout (40 worlds, outside demand 0.3), share of its best-informed value (336.92) | 88.0% (296.58) | 80.1% (269.81) |
| Blind signings / invalid actions (600 cells) | 118 / 0 | 128 / 0 |

Sol − Opus on the main pack: +30.7 [22.7, 38.8], descriptive.

All comparisons are descriptive, with 95% intervals over worlds unless stated. Both CLIs stay below the
best-informed tenant and v14's reachable rule, and above `inspect_then_sign`. As with every model, the shortfall falls
in the worlds whose favourite is a lemon.

**Runs.**
- 600 of 600 cells for each subject, no operational failure; every receipt was replayed when written.
- `aeread verify-replay` on the bundle (`--setup housing_v15_cli_publication:replay_setup`) gives 600 verified, 0
  differ and 0 missing against each subject's run root.
- List prices on the subscription logins, not charges: Sol $24.30, Opus $54.03; admissions $0.13 and $0.24.
- Isolation probes were clean at both admissions and before both main runs.
- Wall time was about 5 hours each, longer than the 2.7-hour projection because the host's load average was about 370
  from other jobs. The owner had waived the 6-hour stop (amendment 2), and no other stop fired.
