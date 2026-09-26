# datacenter_development_v2_world_panel_gap

Why the world panel's developer (Gemini 3.8 Flash, one route) falls short of the scripted reference on the same held-out worlds, once per frozen confirmatory: interface 2 (`datacenter_development_v2_world_panel_confirmatory_v1`) and interface 3 (`datacenter_development_v2_world_panel_interface3_confirmatory_v1`). Derived from the two published bundles and the committed world packs whose digests they publish by `python -m aeread_families.datacenter_development.world_panel_gap`; `--check` regenerates these bytes. Descriptive only: one route, no winner, no ranking.

**Endpoint.** Developer equity NPV as each campaign ranks it (`world_campaign._economic_value`): an admitted stack earns `outcome.developer_equity_npv_cents`; a walk or a round-out earns the same field, which is then the outside option; an invalid action, or an executed stack that fails admission, scores `outside_option_developer_equity_npv_cents`. The reference is `scripted_baseline_developer_equity_npv_cents`, each world's `payload.baseline`, re-simulated here from the scripted terms (24 of 24 worlds in each pack, every reference stack admitted). Each cell is the model minus the reference on its world, the leaderboard's *delta vs scripted*, in USD millions, averaged over a world's three seeds and then over 24 worlds. Mean NPV per world: model 127.2 against reference 554.1 (interface 2), 104.4 against 552.6 (interface 3); walking away is worth -11.9 and -11.7.

**Reconciliation.** The realized gap reproduces the leaderboard (-426.9 and -448.2). A gap read off the score leaf `scores.developer_equity_npv` is smaller (-269.7 and -75.1) because the leaf credits a stack that fails admission with its simulated NPV, which the ranking basis replaces with the walk-away value. The cell rows publish `agreements_executed: []` and `constraint_checks: null` for every cell (DC-T-14), so executed stacks are identified by `project_completed` and their failing checks are re-derived: each executed stack is rebuilt from the terms its trajectory signed and re-simulated on the committed world (39 and 64 stacks, all reproducing the published NPV, admission flag and default reasons).

Each cell's gap is exactly one part, chosen by how the episode ended (largest residual 0). USD M per world, 95% world-clustered bootstrap (each campaign's predeclared seed and 10,000 draws); the reference's own parts are zero:

| part (cells, interface 2 / 3) | interface 2 | interface 3 |
|---|---|---|
| **developer NPV minus the reference's** | **-426.9 (-484.8 to -370.6)** | **-448.2 (-507.7 to -386.5)** |
| ended on output the parser refused (format; 17 / 2 cells) | -129.2 (-172.6 to -86.9) | -15.5 (-39.1 to 0.0) |
| ended on an action the rules refuse (procedure; 16 / 0 cells) | -125.4 (-194.8 to -66.0) | 0.0 (0.0 to 0.0) |
| walked, or ran out of rounds (decision; 0 / 6 cells) | 0.0 (0.0 to 0.0) | -46.2 (-93.9 to -8.3) |
| signed a stack that fails admission (decision; 21 / 49 cells) | -166.9 (-227.3 to -110.2) | -385.2 (-453.2 to -313.9) |
| admitted, on different terms (decision; 18 / 15 cells) | -5.4 (-7.9 to -3.0) | -1.3 (-3.2 to 0.3) |

The admitted part by agreement, each agreement's terms put in place of the reference's in negotiation order (USD M per world):

| agreement | interface 2 | interface 3 |
|---|---|---|
| land purchase | 1.63 | 1.53 |
| power agreement | -0.98 | -1.04 |
| EPC contract | -5.47 | -1.36 |
| service agreement | 0.00 | 0.00 |
| land amendment | 0.00 | 0.00 |
| loan | -0.57 | -0.44 |

What happened, counted over all 72 cells of each run (diagnostic and overlapping, not parts of the sum; the amount is the gap of the cells carrying the class, USD M per world). The `fails_*` classes are the engine's own checks on each executed stack, re-derived as above:

| class | interface 2 cells | interface 3 cells | interface 2 per world | interface 3 per world |
|---|---|---|---|---|
| `malformed_json`: the developer's output was not valid JSON | 5 | 2 | -36.8 | -15.5 |
| `parser_rejected_action`: the action parser rejected a JSON action (malformed_datacenter_stack_action); its text is not published | 12 | 0 | -92.4 | 0.0 |
| `amendment_changes_nothing`: re-proposed the executed land terms as the amendment | 16 | 0 | -125.4 | 0.0 |
| `declined_land_amendment`: declined the land amendment (possible only under interface 3) | 0 | 66 | 0.0 | -421.8 |
| `walked_away`: walked away | 0 | 5 | 0.0 | -37.0 |
| `negotiation_rounds_exhausted`: a negotiation ran out of rounds | 0 | 1 | 0.0 | -9.2 |
| `fails_power_capacity_covers_lease`: executed stack: contracted power is below the leased capacity | 15 | 17 | -124.0 | -126.0 |
| `fails_site_control_holds_through_operations`: executed stack: site control does not reach commercial operation | 15 | 46 | -124.0 | -364.9 |
| `fails_financing_funded`: executed stack: the loan does not fund the project | 11 | 10 | -84.5 | -74.3 |
| `fails_no_default`: executed stack: the project defaults | 11 | 10 | -84.5 | -74.3 |
| `fails_epc_conditions_precedent_met`: executed stack: the EPC's conditions precedent are not met at notice to proceed | 0 | 2 | 0.0 | -13.5 |
| `fails_power_conditions_precedent_met`: executed stack: the power agreement's conditions precedent are not met at energization | 0 | 0 | 0.0 | 0.0 |
| `fails_epc_capacity_covers_lease`: executed stack: the EPC guarantees less than the leased capacity | 0 | 0 | 0.0 | 0.0 |
| `admitted_below_reference`: admitted, below the reference's NPV | 15 | 7 | -5.5 | -1.7 |

Every class instance and every part's contribution rows name the step that decided them (`step_index`, `phase_id`, `seat_id` in `trajectories/sanitized.jsonl`, and `round_index`, the 0-based count of land-offer phases started). Reports: `reports/gap_decomposition_interface2.json`, `reports/gap_decomposition_interface3.json`; rows: `tables/contributions_<interface>.jsonl` (162 and 147 rows; per cell, a part's rows sum to it exactly).

**Unit.** The world: 24 distinct worlds per pack, each run on three inference seeds that share its case digest, so the seeds vary the model's sampling, not the case. The reference's cells are one per world, identified by the world's case digest in `receipt_sha256` because the scripted reference has no receipt in the bundle. Every world file read here matches the `case_sha256` its cells publish, and both packs regenerate byte for byte from their master seeds (`tests/test_datacenter_holdout_pack.py`, `tests/test_datacenter_interface3_confirmatory.py`).

**Limits.** The two packs share 0 of 24 world seeds and 0 case digests (different master seeds), so interface 2 and interface 3 are not paired world by world. The parser keeps no text for a rejected action, so what the 12 `parser_rejected_action` cells of interface 2 said is not derivable here (DC-D-08 and DC-D-10 read them from the unpublished run root as walks with a stated reason). The summaries' label `constraint_failure:unfinanced` names stacks the engine funded (DC-T-15); this bundle names each failing check instead. The by-agreement split depends on the declared order.
