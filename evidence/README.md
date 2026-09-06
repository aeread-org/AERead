# Evidence

This top-level directory contains version-controlled, reviewable evidence
artifacts. It is intentionally separate from both documentation and raw run
state:

- `docs/` explains benchmark and campaign design.
- `runs/` contains ignored local execution state, including full provider
  payloads and receipts.
- `work/` contains ignored non-benchmark scratch artifacts.
- `evidence/` contains sanitized reports, projections, and digest manifests
  suitable for code review and pull requests.

Generic `output/` and `outputs/` directories are not used. See the normative
[artifact layout](../docs/architecture/artifact_layout.md).

Campaign evidence should use a dedicated subdirectory. A publication must
retain typed failures and exclusions, identify its source receipts by digest,
and state whether costs are exact or lower bounds. Do not commit API keys,
provider-account identifiers, raw provider responses, hidden reasoning, or
complete prompts.

Current campaign directories include:

- `commercial_state_openweight_variance_v1/`: sanitized commercial-state
  profiles, model facts, results, transcript projections, and manifest;
- `housing_case_config_sweep_v1/`: provider-free Housing case facts and the
  selected development configurations;
- `housing_qc_goldens_v1/`: six provider-free Housing environment/verifier
  golden receipts and their digest-bound QC report;
- `procurement_allocation_glm53_flash_parasail_strategy_scaffold_v4_retry_after/`:
  qualified same-route labeled and opaque prompt-treatment evidence, including
  retry observability, paired effects, integrity gates, and sanitized row projections;
- `housing_model_sensitivity_openrouter_alt_v4/` through
  `housing_model_sensitivity_openrouter_alt_v9/`, plus
  `housing_model_sensitivity_openrouter_morph_v10/`: successive OpenRouter
  qualification records. V7 publishes its seven completed trajectories; V8
  publishes all 12 attempted cells, including one typed timeout, under
  `trajectories/`; V9 publishes reusable model-profile and admission fact
  tables and records that its 48-cell variance pilot was blocked before live
  execution; V10 publishes all 48 attempts and 12 canonical run-fact bundles,
  while recording 17 typed operational failures, zero complete paired worlds,
  and the missing pre-pilot full-trajectory gate. V10 is route-reliability and
  protocol-deviation evidence, not a leaderboard.
- `housing_model_sensitivity_openrouter_deepinfra_v11/`: the explicit
  four-condition full-trajectory promotion gate. DeepSeek passed 9/9 admission
  probes; DeepInfra GLM passed 6/9 before three probe-index-2 rate limits.
  Admission blocked all four trajectories, so this is reusable route-capacity
  and gate evidence rather than model-performance evidence.
- `housing_model_sensitivity_openrouter_deepinfra_v12/`: the same
  four-condition gate under a digest-pinned 15-second start-to-start pacing
  treatment. Admission passed 17/18 probes; one zero-wait DeepInfra follow-on
  call returned HTTP 429, so all trajectories remained blocked. The canonical
  admission table reports elapsed time and pacing delivery for every probe.
- `housing_model_sensitivity_openrouter_friendli_v13/`: the same
  four-condition gate with GLM repinned to Friendli, a digest-pinned 10-second
  completion-to-next-start cooldown, and admission calls bound to the frozen
  120-second timeout. Admission passed 18/18 and all four trajectories
  completed with exact replay; the gate is promotion-eligible but supports no
  ranking because it covers one world.
- `housing_model_sensitivity_openrouter_friendli_v14/`: the 48-cell
  four-world variance pilot promoted by V13 on the same routes and controls.
  Admission passed 15/18; three Friendli/GLM probes returned upstream HTTP
  429 after the full cooldown, so all trajectories remained blocked.
- `housing_model_sensitivity_openrouter_friendli_v15/`: the same 48-cell
  pilot with four receipt-visible admission attempts. Admission passed 18/18
  first try; 43/48 trajectories completed with exact replay. Five Friendli/GLM
  cells (four rate-limit exhaustions, one timeout) leave every world without
  a complete subject pair, so variance is not estimable and no ranking is
  supported. Protocol-conformant against the recorded V13 gate.
- `housing_model_sensitivity_openrouter_parasail_v22/` and
  `housing_model_sensitivity_openrouter_parasail_v23/`: the bounded-concurrency
  gate and the 192-cell, eight-world, two-replicate pilot it promoted. The
  pilot lost 3.1 percent of cells, measured a paired standard deviation of
  0.0385 around a near-zero contrast, and withheld the confirmatory world
  count because only four of eight worlds paired.
- `housing_operational_feasibility_2026-09-06/`: the serial wall-time
  projection the campaign SOP requires before a variance pilot, which stopped
  the first attempt at this pilot.
- `housing_failure_register/`: every typed Housing failure across all
  campaigns in one canonical table, derived only from published evidence so
  each row traces to a committed artifact by digest. Regenerate it with
  `python -m aeread_families.housing.failure_register`; the output must be
  byte-identical or the register and the evidence have diverged.
- `housing_glm_route_probe_2026-09-05/`: one-hour strict-client probe of all
  12 parameter-complete GLM 5.3 Flash routes on OpenRouter, 100 calls each.
  Sanitized per-call record plus a digest-bound summary; Parasail FP8 was the
  only route with zero failures. Referenced by the V16 campaign spec.
- `housing_model_sensitivity_openrouter_parasail_v16/`: the full-trajectory
  gate for the probe-selected route, both models on Parasail FP8. Admission
  18/18, four of four trajectories completed with exact replay, zero
  failures; promotion-eligible, one world, no ranking.
- `housing_model_sensitivity_openrouter_parasail_v17/`: the 48-cell pilot on
  the Parasail routes, stopped by the driver after three cells: two DeepSeek
  120 s timeouts and one hidden $0.01 per-seat budget breach that was wrongly
  treated as a campaign-critical failure; 45 cells never attempted. Recorded
  as a driver defect; no route failure occurred.
- `housing_model_sensitivity_openrouter_parasail_v18/`: the full-trajectory
  gate for the corrected controls (300 s wall time, contract-visible $0.03
  seat budget). Admission 18/18, four of four trajectories completed with
  exact replay, zero failures; promotion-eligible, one world, no ranking.
- `housing_model_sensitivity_openrouter_parasail_v19/`: the 48-cell pilot on
  the V18 controls. Admission 18/18; 32/48 completed with exact replay. Two
  worlds completed all 24 cells and give the family's first paired-world
  contrasts (exploratory, no ranking); a Parasail GLM rate-limit burst then
  cost 16 of the last 24 cells. No timeout or seat-budget failure occurred.
