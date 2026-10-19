# Lemons price with outside demand: confirmatory plan, v15

**Status:** declared on 2026-10-19, before any v15 module, pack, probe or cell. The owner approved the design on
2026-10-18 ("Housing v15 next"). Nothing that calls a provider runs until the OpenRouter balance covers Section 9's
ceilings; the offline steps (Sections 2, 3, 6) may run now. A changed control is a new identity. The v14 identities,
bundle and fill stay as published; QC section 22 (`docs/families/housing/qc.md`) records why each of v14's gates is
`partial`, and this plan exists to close those blockers before a freeze rather than after one.

## 1. What v15 fixes, gate by gate

| Gate | v14 blocker (qc.md section 22) | v15 step |
|---|---|---|
| 1 | no measured-headroom screen; no near-duplicate check; the holdout is new seeds, not a held-out mechanism | Section 2: a headroom screen on every world before admission, a near-duplicate check, a holdout with a changed mechanism |
| 2 | goldens are tests, not sealed receipts; the bundle holds no receipts | Section 6: a sealed golden-receipt bundle; the bundle carries seat 0's receipts and trajectory table |
| 3 | no beatability rule before results; primary v1 with HL-D-07 unresolved; HL-D-09 open; the brief hid the lemon pricing rule | Sections 3 to 5: the brief states the pricing rule, the primary is measure v2, receipts score seat 0, the rule is declared here |
| 4 | no sealed profile-admission probes | Section 7: one sealed probe and one full trajectory per profile before the freeze |
| 5 | no variance pilot, no sizing record, no A/A arm | Section 8: a variance pilot, a committed sizing record and an A/A arm |

## 2. Pack: `housing_lemons_price_pack_v2`

v14's generator and admission (`lemons_design.confirmatory_pack()`: one deciding tenant, a favourite and a second
listing with positive gain if sound, the stratum read afterwards from the seed's own lemon draw) are reused through a
new unhashed module; nothing hashed by a sealed Housing plan is edited (HL-T-04). Added before any world is admitted:

- **Headroom screen.** Both landlord arms of a candidate world are played offline by the scripted controls and the
  best-informed tenant (`price_best_informed`, knowledge `pricing`, the level this brief now states). A world is
  admitted only if its full-information ceiling is above $0 in both arms and, averaged over the two arms, the
  best-informed tenant's net less `inspect_then_sign`'s is at least $25 (one inspection fee) on measure v2. The
  $0-ceiling rule of v14 therefore never applies. A failing seed is logged with its numbers and does not fill a quota.
- **Near-duplicate check.** No two admitted worlds may give seat 0 views within $10 on every listing's rent, value and
  floor after sorting the listings; the check runs on the pack and is a test.
- **Quotas and seeds.** Main: 200 favourite-lemon and 60 favourite-sound from seeds 500,000 upward. Holdout: 30 and 10
  from 520,000 upward with **one changed mechanism**, outside demand leaving at 0.3 a round instead of 0.5. The rate
  is a constant of `price_outside_demand.py` (`RATE = 0.5`), whose bytes sealed plans hash, so the holdout's schedule
  comes from a new module that draws it the same way at 0.3; the main pack uses v14's. The holdout is reported apart
  and never pooled. Development worlds for Sections 7 and 8 come from
  540,000 upward. All three are disjoint from each other and from every v13 and v14 seed.

The pack, its scan log, the controls and the best-informed tenant's value per world and arm are published before the
freeze.

## 3. Brief: notice v5

Notice v4 (`price_outside_demand.DISCLOSURE_V4`: departure rule, horizon, round order, reply history in the
observation, all in the sealed tenant prompt) followed by notice v3's pricing paragraph unchanged
(`price_outside_demand.PRICING_RULE`: a sound landlord accepts at or above its cost plus $25, or the ask if lower, and
otherwise counters there; a sound cost is $20 to $80 under the ask, so a rent more than $55 under the ask proves a
lemon). The v14 models were not told this, so part of their gap to the best-informed tenant was information rather
than judgment (Section 5.2 of the working paper). The best-informed tenant also holds even odds over the two landlord
kinds, which the notice does not state; in this design they are the true frequency, because every world is played
under both kinds.

## 4. Measurement

- **Primary**: seat 0's net at the reply-conditioned odds, measure v2 (`housing_price_reply_conditioned_v2`,
  `price_reply_posterior`, HL-D-07), mean of the two landlord arms per world.
- **Receipts score seat 0** (HL-D-09): a new scorer module under a new scorer id
  (`housing_lemons_price_seat0_outcome_v1`) whose primary leaf is seat 0's net under measure v2 and whose reference
  leaves are the best-informed tenant and the ceiling for the same world and arm. `runner.py` is not edited.
- **Action validity** (HL-D-08): seat 0's invalid actions per cell are a published secondary column.
- Secondary, as v14: realized net, signings of a hold below every sound floor, the share of cells ending on an
  inspected listing, both strata, the holdout.

## 5. Contrasts and the beatability rule, declared before any result

On the main pack, paired by world, 95% Student-t over worlds, a model's cells averaged within a world first.

| | Contrast | Rule |
|---|---|---|
| P1 to P3 | every pair of the three models | Holm over the three; a difference is claimed when Holm rejects 0, and called larger than $50 only when the 95% interval clears $50 |
| B1 to B3 | each model less `inspect_then_sign` | **beatability:** a model beats the baseline when the lower end of its interval at 1 - 0.05/3 is above $0 |
| G1 to G3 | each model less the best-informed tenant | reported with intervals; no test, the best-informed tenant is the reference the gap is measured to |

A contrast that loses more than 10% of its worlds is reported inconclusive. The $50 band is read against the A/A arm
(Section 8): if the A/A interval does not lie inside ±$50, every "larger than $50" reading is reported as uncalibrated.

## 6. Environment and verifier, before any model plays

- A sealed golden-receipt bundle: the five golden kinds of `tests/test_housing_price_goldens.py` (successful, valid
  but poor, invalid or unauthorized, malformed or operational failure, degenerate) run through the kernel with
  scripted seat-0 policies on pack worlds, receipts and events published, as section 14 does for the bid world.
- The oracle run of `tests/test_housing_price_oracle_run.py` on every v15 world and arm, the full-information tenant
  realizing the ceiling exactly.
- The v15 bundle publishes seat 0's trajectory table and each receipt's projection, so the primary is recomputed from
  `evidence/` alone and `aeread verify-replay` runs against the run roots.

## 7. Profiles: GLM 5.3 Flash (NextBit), GPT-6 Luna, Gemini 3.8 Flash

v14's three routes, reasoning tiers and sampling controls (the contract diff of `tests/test_housing_price_v14_contract_diff.py`
then differs from v14's only in the identity, the notice, the pack, the scorer and the ceilings). Before the freeze,
each profile gets a sealed admission: one probe call checking structured output and the reasoning tokens the tier
produces, and one full trajectory on a development world; both published. A profile that fails is dropped before the
freeze and its pairs leave Section 5.

## 8. Variance pilot, sizing and the A/A arm

- **Pilot:** 20 development worlds, both arms, 2 replicates, the three models (240 cells). It estimates the world and
  replicate variance of each pairwise difference; its cells are development evidence and never analysed with the
  confirmatory.
- **Sizing record:** the committed sizing module (`aeread.design.sizing` at 159cba3c) at power 0.8, the first Holm step
  (0.05/3), 5% attrition and the $50 effect gives the main-pack world count. If it needs more than 260 worlds, the
  plan is amended and committed before the freeze; it is never resized after.
- **A/A arm:** GLM 5.3 Flash runs the main pack twice under two identities that differ only in their name. The paired
  difference calibrates the $50 band (Section 5). GLM is the cheapest route ($0.41 for 600 v14 cells).

## 9. Cost, ceilings and stops

At v14's measured spend ($6.40 Gemini, $0.41 GLM, $0.63 Luna per 600 cells): pilot about $3.10, profile admission
under $0.50, confirmatory about $7.45, A/A arm about $0.41; about $11.50 in all. Each identity's ceiling is twice its
estimate (about $23 in all), declared in its contract, with v14's per-cell ceiling, retry policy v2, 8 attempts a move
and the 300-second timeout. A failed cell is typed missingness and never rerun. Because the TERMS-Bench reproduction
holds $22 of the $23.96 balance (2026-10-18), v15 needs a top-up of at least $23 before Section 7 runs.

## 10. Order

1. This plan (committed). 2. The pack module and pack v2, its scan log, controls and best-informed values (offline).
3. Notice v5, the seat-0 scorer, the golden-receipt bundle, the oracle run (offline). 4. Top-up. 5. Profile admission
(Section 7). 6. Variance pilot, sizing record, amendment if needed. 7. Freeze the three identities and the A/A twin.
8. Run, verify-replay, publish, analyse as Section 5 declares, QC section for v15.

## Correction, 2026-10-19 (before any v15 artifact)

Section 2 gave the wrong reason for putting the holdout's 0.3 departure schedule in a new module: `price_outside_demand.py`
is not hashed into any sealed Housing plan (its docstring says so; `runner.py` hashes the housing, lemons,
price-bargaining and bridge sources). The step is unchanged, for the reason that holds: editing `RATE` in place would
change the departures every v14 identity runs on its declared pack, so the 0.3 schedule stays in a new module and v14's
module keeps 0.5. Found by the session building steps 2 and 3, which read the module and the runner's digest code.

## Amendment 1, 2026-10-19 (before any v15 pack, probe or cell is frozen)

Three things Sections 2, 3 and 8 left open, fixed while the offline steps were built (branch
`codex/housing-v15-offline`):

- **The holdout's brief states the rule it runs.** Notice v5 says outside demand leaves "with probability 0.5". The
  holdout runs 0.3, so its tenant reads `DISCLOSURE_V5_HOLDOUT`, identical to notice v5 except that number
  (prompt id `housing_tenant_lemons_price_outside_v5_rate30`). A brief that misstated the departure rate would add a
  second, undeclared difference to the held-out mechanism. The main pack's tenant reads notice v5.
- **Development worlds:** 20 (15 favourite-lemon, 5 favourite-sound) from 540,000 upward, the same admission and
  screen; they serve the profile admission (Section 7) and the variance pilot (Section 8).
- **The seat-0 scorer's route (HL-D-09).** v14's scorer id, its pin, the manifest's scoring block and the plugin
  instance are fixed inside `runner.build_housing_smoke`, which sealed plans hash. The seat-0 scorer therefore comes
  with a new plan builder that rebuilds those around a plugin subclass registered under the same trusted key (no kernel
  change), in a new module with a fixed interface (`build_v15_setup(contract, arm, *, live, holdout_rate)`, returning
  what `build_housing_smoke` returns); the campaign's setup and its replay path call that builder for v15 identities
  only. The golden-receipt bundle (Section 6) is sealed through the same builder.

## Amendment 2, 2026-10-19 (before any v15 probe or cell)

The pack v2 build (`evidence/housing/housing_lemons_price_pack_v2/`, branch `codex/housing-v15-offline` 0d3b5403)
shows, on the main pack and measure v2, a world mean of $307.4 for the best-informed tenant, $293.2 for
`inspect_lowball`, $152.0 for `inspect_then_sign` and $370.9 for the ceiling. The screen guarantees at least $25 over
`inspect_then_sign`, the baseline of B1 to B3, while `inspect_lowball`, the reachable reference v14 subtracted, sits
only $14 below the best-informed tenant; a model could pass the beatability rule and remain far below v14's reference.
So Section 5 gains a secondary row:

| | Contrast | Rule |
|---|---|---|
| R1 to R3 | each model less `inspect_lowball` | reported with 95% intervals and intervals at 1 - 0.05/3, no test, as v14 reported its reachable reference; beside B1 to B3 wherever they are reported |

Nothing else in Section 5 changes.

## Amendment 3, 2026-10-19 (before any v15 contract is frozen)

- **Ceilings carry one cell's reservation.** `price_campaign.run()` starts a live cell only while the spend plus the
  per-cell ceiling ($0.30) stays within the identity's total, so a total of twice the estimate alone would stop the
  small identities before or soon after their first cell. Each total is therefore twice its estimate plus $0.30:
  confirmatory GLM $1.13, Luna $1.57, Gemini $13.11; A/A twin $1.02; pilot GLM $0.41, Luna $0.47, Gemini $2.01;
  profile admission $0.60 each (two cells); goldens $0 (scripted). In all, $21.52 of ceilings against the $48.96
  balance checked on 2026-10-19.
- **Main pack and holdout are two plans of one identity.** Their sealed prompts (notice v5 and its rate-0.3 text) and
  their outside demand differ, so each confirmatory identity resolves one plan for the 260 main worlds and one for the
  40 holdout worlds; the contract's `holdout` block names the holdout's worlds and rivals and is allowed only with
  notice 5.
- **The goldens identity names GLM's route nominally**, because a contract requires one; it is scripted and makes no
  provider call.

## Amendment 4, 2026-10-19 (before any v15 contract is frozen)

**The A/A twin draws its own samples.** Built as "identical except the name", the twin resolved to the same run plan as
the GLM confirmatory's main plan (same profile, same inference seed base 87001): its receipts would share run-plan and
cell ids with the confirmatory's, and on a route that honours the seed it would replay the same samples, so the A/A
difference would measure nothing but route nondeterminism. The A/A arm exists to measure what a second, independent
run of the same model on the same worlds differs by, so the twin's tenant inference seed base is 88001; everything
else stays identical. Only notice-5 identities may declare a seed base other than 87001, so every v14 contract is
unchanged.

## Amendment 5, 2026-10-19 (after profile admission, before any pilot or confirmatory cell)

**GLM 5.3 Flash leaves v15 (Section 7's rule; HL-O-22).** Its v14 route is gone: NextBit now serves the model at fp4
where v14 sealed fp8, and both admission cells were refused at OpenRouter's quantization filter before any token.
GPT-6 Luna and Gemini 3.8 Flash passed admission (two cells each, $0.035 together). Consequences, declared before any
pilot or confirmatory cell:

- **Contrasts.** P1 to P3 become one pair, Gemini − Luna, tested at α = 0.05 (no Holm family left); "larger than $50"
  still needs the 95% interval to clear $50. B and G rows keep one row per remaining model, Holm over the two B rows;
  R rows as amendment 2. The variance pilot and its sizing record are for the one pair.
- **The A/A twin moves to Luna**, the cheapest remaining route ($0.63 for 600 v14 cells):
  `housing_lemons_price_v15_gpt6_luna_aa`, the Luna confirmatory's main pack under another name with inference seed
  base 88001 (amendment 4), total ceiling $1.40 (twice $0.55 for 520 cells, plus one cell's $0.30). The GLM twin is
  never run.
- A GLM profile on another route or quantization is a new identity after v15, never a substitute inside it.

## Addendum A, 2026-10-19: GLM 5.3 Flash on Novita fp8 (declared after v15's analysis, before any cell of its own)

The owner asked for GLM on a comparable provider after v15 ran without it (amendment 5). By amendment 5 that is a new
identity, so this addendum is reported beside v15 and never changes v15's declared results, family or readings.

- **Route.** Novita, fp8 (`z-ai/glm-5.3-flash-20260826`), the same quantization v14 sealed at NextBit. Chosen on
  2026-10-19 among the fp8 endpoints that accept a seed, structured output, reasoning and temperature, by one paid
  call to each of three (Novita, GMICloud, Near AI) with the run's routing constraints: all three returned valid JSON;
  at reasoning effort `low` Novita reported 51 reasoning tokens, Near AI 25 and GMICloud 0 (it ignores the setting).
  Pinned at Novita's undiscounted list price ($0.15, $0.03 cached, $0.50 per M; the listing showed a 44% discount),
  so a discount ending mid-run cannot refuse calls. The provider differs from v14's; that is a stated limit on any
  comparison with v14's GLM.
- **Identities.** `housing_lemons_price_v15_glm53_flash_novita` (main 260 and holdout 40, v15's controls, notice v5,
  seat-0 scorer, seed base 87001) and its admission `housing_lemons_price_v15_admission_glm53_flash_novita`.
  Ceilings: $0.80 and $0.60 (twice the estimate from v14's GLM spend at these prices, plus one cell's $0.30).
- **Admission, both parts of Section 7 this time** (HL-J-14): a recorded one-call probe of structured output and
  reasoning tokens through the run's route, and the one-world full trajectory.
- **Rows, declared now, outside v15's Holm family:** B3, GLM − `inspect_then_sign`, read by Section 5's rule at
  1 − 0.05/3 (three models now carry a B row); G3 and R3 as G and R; GLM − Gemini and GLM − Luna with 95% intervals,
  descriptive; the holdout beside. No pilot: the addendum adds no test that needs sizing.

### Addendum A, amendment 1 (before any GLM cell answered)

Novita cannot carry the run: the kernel's client sends `require_parameters: true` with a strict JSON-schema response
format, which OpenRouter admits only on endpoints listing `structured_outputs`, and Novita lists only
`response_format`. Both Novita admission cells were refused at the parameter filter before any token ($0; HL-J-15).
The route is **Near AI, fp8**, the cheapest fp8 endpoint listing every parameter the client sends (seed,
`structured_outputs`, reasoning, temperature, top_p); its probe on 2026-10-19 returned valid JSON with 25 reasoning
tokens at `low`. Pinned at its listed price ($0.08, $0.012 cached, $0.50 per M; no discount). Identities
`housing_lemons_price_v15_glm53_flash_nearai` and `..._admission_glm53_flash_nearai`; the Novita identities stay
defined and their refused admission is published with the rest. Everything else in addendum A stands, and the probe
now sends `require_parameters` as the client does.
