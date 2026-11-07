# housing_lemons_price_v14_reply_conditioned

The v14 confirmatory price panel scored under measure v2 (`price_reply_posterior`, HL-D-07): each blind signing at its lemon probability given every inspection and every informative landlord reply seat 0 had seen, instead of v1's reading of a hold below the sound floor only. A derived analysis beside the sealed v14 bundle, which is not edited: `python -m aeread_families.housing.price_reply_conditioned`; `--check` regenerates these bytes, and `--check --from-runs` first re-extracts the trajectory table from the sealed run roots.

v1 recomputed from `tables/seat0_trajectories.jsonl` reproduces every published cell and the published `analysis.json` and fill `sensitivity.json` exactly; v2 then runs the declared analysis unchanged.

| | GLM | Luna | Gemini |
|---|---|---|---|
| primary, main pack, v1 (published) | +137 [+111, +162] | +130 [+104, +156] | +211 [+188, +233] |
| primary, main pack, v2 | +149 [+124, +175] | +147 [+121, +174] | +213 [+190, +235] |
| blind signings v2 reprices (all populations) | 21 | 33 | 3 |
| of them on a reply on another listing | 0 | 0 | 0 |
| cells with an invalid seat-0 action | 16 | 0 | 0 |

| Pair, main pack | v1 (published) | v2 | v2, Holm p | v2 with the fill | v2 holdout |
|---|---|---|---|---|---|
| Gemini-GLM | +70 [+48, +92] | +60 [+39, +81] | 1.4e-07 | +63 [+43, +84] | +102 [+41, +163] |
| Gemini-Luna | +80 [+62, +99] | +67 [+49, +84] | 1.6e-12 | +65 [+49, +82] | +27 [-6, +60] |
| GLM-Luna | +7 [-16, +29] | +2 [-20, +24] | 0.85 | +2 [-20, +24] | -61 [-123, +0] |

Declared verdicts (separated after Holm; at least the $50 band) changed: no. Every repriced signing was of a sound listing. Invalid seat-0 actions are counted by the kernel's typed code (the family applies one as a pass): GLM malformed_commit 1, unavailable_listing 15; Luna none; Gemini none.

Files: `tables/seat0_trajectories.jsonl` (per completed cell: seat 0's commit decisions, inspection rounds, landlord replies, typed invalid actions, receipt and event-root digests; numbers only), `tables/cells.jsonl` (v1 and v2 per cell), `reports/reply_conditioned.json` (the declared analysis under v2, with and without the fill, and the counts).
