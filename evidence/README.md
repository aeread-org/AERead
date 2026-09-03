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
- `datacenter_development_terms_probe_2026-09-03/`: one corrected synthetic
  agreement-state probe with a completed GLM receipt and typed Mistral
  operational missingness;
- `datacenter_development_terms_reliability_v1/`: five-seed paired route
  reliability panel on the corrected synthetic agreement-state case, with
  eight completed receipts, two typed operational exclusions, and no
  project-generalization or winner claim;
- `datacenter_development_terms_grounded_v1/`: four-case, two-route,
  three-seed source-grounded data-center commercial-state panel; all 24 cells
  completed and replayed, with one included hard-gate failure and one
  conservative archive cluster, so results are descriptive rather than a
  project-generalization or model-winner claim;
- `datacenter_development_terms_grounded_glm_v1/`: hash-bridged GLM add-on over
  the same four case hashes and three seeds; four cells completed with strong
  hard-gate-safe scores, while eight rate-limit failures remain exclusions, so
  conditional task quality and route reliability are reported separately;
- `datacenter_development_terms_public_v1/`: five-public-filing-cluster,
  two-route, three-seed agreement-state panel; 27 of 30 cells completed, three
  rate limits remain excluded, four included Qwen outputs failed deterministic
  safety gates, and successful-call spend is reported as a lower bound;
- `datacenter_development_terms_public_gptoss_v1/`: hash-bridged GPT-OSS 120B
  add-on over the same five public cases and three seeds; all 15 calls completed,
  but every integrated land/power/construction response failed deterministic
  safety gates, so completion, component accuracy, and primary safety score stay
  separate;
- `datacenter_development_terms_public_mechanism_v1/`: one-source-cluster,
  three-mechanism, paired baseline/affirm-only campaign across three routes and
  three seeds; 53 of 54 cells completed, affirm-only wording rescued all three
  baseline GMP hard-gate failures with no hard-gate regressions, and one Mistral
  rate limit remains an exclusion;
- `datacenter_development_terms_public_affirm_only_v1/`: five-cluster replication
  of one frozen affirm-only instruction across three routes; 41 of 45 treatment
  cells form reportable baseline pairs, with four hard-gate rescues and no
  regressions, but effects remain model- and case-dependent;
- `datacenter_development_terms_public_composition_v1/`: matched integrated versus
  decomposed-clause diagnostic on one filing cluster; six composition gaps and
  one inverse gap are descriptive and cross-granularity scores are not compared;
- `datacenter_development_terms_public_candidate_screen_v1/`: held-out
  three-wording diagnostic on the integrated case; Qwen had no rescue in three
  predeclared pairs, Mistral regressed twice, and five GPT-OSS provider failures
  remain exclusions;
- `datacenter_development_terms_public_glm_transfer_v1/`: three-call GLM model
  transfer probe on the exact integrated baseline; one hard-gate-safe 0.9667
  result and two rate-limit exclusions leave the frozen decision inconclusive;
- `datacenter_development_v2_interaction_v1/`: three-seed V2 agreement-stack
  campaign pairing a live developer with scripted counterparties against a
  homogeneous six-seat model-to-model condition; results are a single-project
  interaction diagnostic, not a model ranking or causal condition effect;
- `datacenter_development_v2_objective_grounding_v1/` and
  `datacenter_development_v2_objective_grounding_v2/`: preserved route-panel
  qualification campaigns for the bounded objective-visible stack; all cells
  are typed operational exclusions and therefore have no model scores;
- `datacenter_development_v2_objective_grounding_v3/`: parameter-compatible
  open-source route panel for the bounded objective-visible stack, with four
  included negotiation outcomes and two provider-contract exclusions;
- `datacenter_counteroffer_adoption_v1/` and
  `datacenter_counteroffer_adoption_v2/`: preserved full-panel instrumentation
  preflights exposing, respectively, an initial-offer confound and a nullable
  nonbinding-prose parser mismatch;
- `datacenter_counteroffer_adoption_v3/`: schema-aligned nested land,
  land-plus-power, and land-plus-power-plus-EPC diagnostic; all 15 included
  cells reached a written counteroffer, one adopted it exactly, and three
  rate-limit failures remain typed exclusions;
- `datacenter_counteroffer_salience_v1/`: paired land-only diagnostic comparing
  a complete written counteroffer with the same package plus a public explicit
  field delta; all 20 cells and 10 matched pairs are included, with no adoption
  in either condition and no population, causal, or model-winner claim;
- `datacenter_counteroffer_affordance_v1/`: paired land-only diagnostic comparing
  complete-package re-emission with acceptance of the same formal counteroffer
  by public ID; all 20 cells are included, with 9/10 versus 5/10 exact
  executions and no population, causal, or model-winner claim;
- `datacenter_counteroffer_action_schema_v1/`: instrumentation preflight for a
  shared versus dedicated acceptance schema; 17 included cells failed before
  counteroffer exposure due an ambiguous opening offer-ID contract;
- `datacenter_counteroffer_action_schema_v2/`: fresh full-panel successor with
  an explicit opening contract; all 14 included cells executed exactly, six
  rate-limit failures remain exclusions, and all six usable pairs adopted under
  both schemas without a population, causal, or model-winner claim;
- `datacenter_development_terms_public_integrated_v4/`: unique-array
  three-project agreement-state campaign; Qwen/Google completed and replayed
  9/9 cells, Mistral/DeepInfra excluded 9/9 because its grammar compiler did not
  support `uniqueItems`, and no model-to-model pair is reportable;
- `datacenter_development_terms_public_integrated_v5/`: complete indicator-map
  successor with 18/18 completed cells and nine reportable pairs; Qwen passed
  9/9 hard gates versus Mistral 3/9, with sign-changing project effects and one
  exact output per model-project group across three stability seeds;
- `datacenter_development_terms_public_integrated_v6/`: three additional SEC
  project clusters covering Helios lease/power/loan timing, Lake Mariner lease
  commencement/prepaid rent/site control, and Tydal open-book construction;
  four of six cells completed and passed, two Mistral rate limits remain typed
  exclusions, only the Helios pair is validly reportable, and the raw Tydal
  score is invalidated because one oracle amount was omitted from observation;
- `datacenter_development_terms_public_integrated_v7/`: fresh full-panel
  replacement on the answerability-corrected expansion pack; four of six cells
  completed at 1.0 and replayed, the corrected Tydal Qwen output recovered the
  visible 22nd-day invoice term, two DeepInfra rate limits remain exclusions,
  and the only reportable Helios pair tied at 1.0 without supporting a route
  ranking or project-population claim;
- `datacenter_development_terms_public_integrated_v8/`: provider-paced
  corrected-pack panel with 6/6 completed, route-verified, replayed cells and
  three mechanically complete pairs; Helios and Tydal are interpretable 1.0
  ties, while Lake's raw score and delta are invalidated by an unspecified
  currency-unit contract even though its separate power-limit error is valid;
- `datacenter_development_terms_public_integrated_v9/`: unit-explicit,
  provider-paced full panel with five of six cells completed and replayed; both
  Lake routes returned base-dollar amounts and 750 MW for a valid 1.0 tie,
  Helios also tied at 1.0, and one Mistral Tydal rate limit remains a typed
  exclusion rather than a score;
- `datacenter_development_terms_public_integrated_v10/`: 60-second DeepInfra
  cooldown bake-off on the same unit-explicit pack; it matched V9 at 5/6 total
  and 2/3 DeepInfra completions despite higher wall time, with a Helios tie, a
  valid +0.0111 Qwen Lake delta from one 750-versus-250 MW error, and Tydal
  operationally missing on Mistral;
- `datacenter_development_terms_public_integrated_v11/`: reversed-DeepInfra-order
  diagnostic at the preferred 30-second pacing; Tydal completed first, Lake
  rate-limited second, and Helios completed third, ruling out Tydal-specific and
  deterministic third-call explanations while preserving the failure as typed
  intermittent provider missingness;
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
