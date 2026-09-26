# housing_oracle_gap

Why each Housing model falls short of the full-information oracle, in the confirmatory holdout (30 worlds) and the two eight-world variance pilots on the development panel, which ran the same worlds and configurations with action attempt limits of 10 and 30 (`confirmatory_v2` is `housing_confirmatory_parasail_v2`; `pilot_v23` is `housing_model_sensitivity_openrouter_parasail_v23`; `pilot_v26` is `housing_model_sensitivity_openrouter_parasail_v26`). Derived from each bundle's `trajectories/attempted.json` and the worlds regenerated from the committed sweep contract by `python -m aeread_families.housing.oracle_gap`; `--check` regenerates these bytes. Every cell's published welfare and oracle bound are recomputed from its world and leases and match to the cent. Descriptive: no winner, no ranking.

The endpoint is welfare minus the oracle's welfare per market (published `social_welfare` minus `oracle_upper_bound`; zero is the oracle). Rent cancels in welfare. The gap is indexed by listing, so each listing lands in one part and the parts sum to each cell's gap exactly (largest residual 1.1e-12). A model is the tenant seat, the campaign's subject, pooled over both landlord models. The unit is the world seed, with a world-clustered percentile bootstrap (seed 20260925, 10000 draws); eight worlds is marginal for it, so the pilots' intervals understate their spread.

In every report the largest part is the wrong tenant on a listing the oracle leases, 52 to 89 percent of the gap. Most of the rest is oracle listings left empty, which in the confirmatory run cost 63.8 per market with DeepSeek as tenant against 22.2 with GLM. Per market, dollars, 95% world-bootstrap interval in brackets:

| campaign, tenant model | worlds / cells | welfare minus oracle | oracle listing left empty | oracle listing, wrong tenant | listing the oracle leaves empty, leased | value-destroying lease |
|---|---|---|---|---|---|---|
| confirmatory_v2, GLM 5.3 Flash | 30 / 358 | **-298.2** (-326.4 to -271.0) | -22.2 (-32.6 to -12.8) | -266.5 (-290.3 to -243.0) | 0.3 (0.0 to 1.0) | -9.8 (-14.5 to -5.4) |
| confirmatory_v2, DeepSeek V4 Flash | 30 / 359 | **-317.4** (-343.3 to -291.9) | -63.8 (-79.1 to -49.0) | -246.5 (-267.5 to -226.2) | 0.2 (0.0 to 0.5) | -7.3 (-10.7 to -4.2) |
| pilot_v23, GLM 5.3 Flash | 8 / 90 | **-324.8** (-440.6 to -242.7) | -103.7 (-198.7 to -43.8) | -221.1 (-269.9 to -176.7) | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) |
| pilot_v23, DeepSeek V4 Flash | 8 / 96 | **-282.8** (-362.7 to -226.1) | -127.7 (-217.0 to -60.7) | -153.7 (-181.5 to -126.3) | 0.0 (0.0 to 0.0) | -1.4 (-3.7 to 0.0) |
| pilot_v26, GLM 5.3 Flash | 8 / 93 | **-299.7** (-397.2 to -220.2) | -79.7 (-162.4 to -28.3) | -220.0 (-267.3 to -170.9) | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) |
| pilot_v26, DeepSeek V4 Flash | 8 / 96 | **-280.9** (-378.6 to -204.0) | -133.7 (-230.2 to -64.3) | -147.2 (-185.5 to -112.0) | 0.0 (0.0 to 0.0) | 0.0 (0.0 to 0.0) |

An oracle listing left empty costs the oracle pair's whole surplus. A wrong tenant on an oracle listing costs the difference between the two pairs. An extra listing is credited with what its lease realized; the tenant it took is charged on the oracle listing that tenant left. A value-destroying lease is its negative surplus. The estimand review's split of this gap (20 percent empty, 68 wrong tenant, 12 value-destroying) does not reproduce under these definitions or the variants tried (incident J-7).

By landlord (per market, no interval):

| campaign | tenant | landlord | cells | welfare minus oracle | oracle listing left empty | oracle listing, wrong tenant | listing the oracle leaves empty, leased | value-destroying lease |
|---|---|---|---|---|---|---|---|---|
| confirmatory_v2 | GLM 5.3 Flash | GLM 5.3 Flash | 179 | -305.0 | -24.2 | -263.5 | 0.4 | -17.6 |
| confirmatory_v2 | GLM 5.3 Flash | DeepSeek V4 Flash | 179 | -291.2 | -20.2 | -269.3 | 0.3 | -2.0 |
| confirmatory_v2 | DeepSeek V4 Flash | GLM 5.3 Flash | 179 | -315.5 | -64.7 | -241.0 | 0.0 | -9.8 |
| confirmatory_v2 | DeepSeek V4 Flash | DeepSeek V4 Flash | 180 | -319.7 | -62.8 | -252.5 | 0.3 | -4.7 |
| pilot_v23 | GLM 5.3 Flash | GLM 5.3 Flash | 47 | -327.0 | -104.7 | -222.3 | 0.0 | 0.0 |
| pilot_v23 | GLM 5.3 Flash | DeepSeek V4 Flash | 43 | -325.8 | -104.6 | -221.2 | 0.0 | 0.0 |
| pilot_v23 | DeepSeek V4 Flash | GLM 5.3 Flash | 48 | -287.9 | -130.0 | -155.1 | 0.0 | -2.8 |
| pilot_v23 | DeepSeek V4 Flash | DeepSeek V4 Flash | 48 | -277.8 | -125.4 | -152.4 | 0.0 | 0.0 |
| pilot_v26 | GLM 5.3 Flash | GLM 5.3 Flash | 45 | -272.4 | -88.7 | -183.7 | 0.0 | 0.0 |
| pilot_v26 | GLM 5.3 Flash | DeepSeek V4 Flash | 48 | -323.2 | -71.2 | -252.0 | 0.0 | 0.0 |
| pilot_v26 | DeepSeek V4 Flash | GLM 5.3 Flash | 48 | -285.0 | -128.0 | -157.0 | 0.0 | 0.0 |
| pilot_v26 | DeepSeek V4 Flash | DeepSeek V4 Flash | 48 | -276.8 | -139.4 | -137.4 | 0.0 | 0.0 |

Classes, count (dollars per market). A1 to B3 are `failure_taxonomy.classify`'s classes and counts, checked cell by cell: A per lease, B per cell. A2 and A3 belong to the landlord seat, which both models play in every report. T1 and T2 split welfare into the tenants' and landlords' payoffs; the transfer between them cancels, and the oracle sets no rent. Diagnostic, overlapping, not parts of the sum:

| class | confirmatory_v2, GLM | confirmatory_v2, DeepSeek | pilot_v23, GLM | pilot_v23, DeepSeek | pilot_v26, GLM | pilot_v26, DeepSeek |
|---|---|---|---|---|---|---|
| `A1_tenant_signed_above_own_value` | 4 (2.0) | 23 (5.4) | 0 (0.0) | 2 (3.2) | 0 (0.0) | 0 (0.0) |
| `A2_landlord_signed_at_zero_rent` | 138 (939.0) | 126 (825.5) | 17 (507.9) | 17 (445.5) | 20 (545.1) | 21 (482.5) |
| `A3_landlord_signed_below_cost` | 18 (4.5) | 5 (1.1) | 1 (0.1) | 1 (0.1) | 1 (0.1) | 1 (0.4) |
| `A4_pair_destroys_value` | 35 (9.8) | 25 (7.3) | 0 (0.0) | 2 (1.4) | 0 (0.0) | 0 (0.0) |
| `B1_oracle_listing_left_empty` | 62 (22.2) | 104 (63.8) | 41 (103.7) | 55 (127.7) | 37 (79.7) | 53 (133.7) |
| `B2_leased_a_listing_the_oracle_leaves_empty` | 33 (-9.1) | 17 (-4.8) | 0 (0.0) | 2 (-1.4) | 0 (0.0) | 0 (0.0) |
| `B3_right_listings_wrong_tenants` | 350 (269.0) | 352 (252.3) | 88 (226.0) | 94 (160.0) | 93 (224.6) | 95 (152.5) |
| `T1_tenant_payoff` | 1611 (2261.4) | 1555 (1904.6) | 278 (1457.4) | 277 (1273.4) | 295 (1494.2) | 279 (1311.4) |
| `T2_landlord_payoff` | 1611 (-695.9) | 1555 (-353.6) | 278 (-306.5) | 277 (-95.2) | 295 (-331.0) | 279 (-131.2) |

No step-level log is published for these campaigns (`trajectories/` holds only `attempted.json`). Contribution rows and instances therefore carry null `step_index`, `round_index`, `phase_id` and `seat_id`, and name the lease (tenant, listing, rent) instead. Each report is `reports/gap_decomposition_<campaign>_<model>.json`; `tables/contributions_<campaign>_<model>.jsonl` (3505 rows in all) gives one row per listing per part, and per cell a part's rows sum to that cell's part. The oracle has no receipts: its cells are the world-configuration cases, identified as `oracle:<config_id>:<world_seed>`. These bundles publish no `publication_manifest.json`, so `source_manifest_sha256` is the digest of the `attempted.json` read.
