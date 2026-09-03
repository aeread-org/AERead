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
