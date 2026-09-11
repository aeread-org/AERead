# Procurement allocation trajectory grains v1

Derived publication: the kernel trajectory grain (`aeread.sanitized_trajectory_row/0.1`, one row per logical action) for seven procurement bundles whose own `publication_manifest.json` is frozen as a control by a later campaign module (`PARENT_EVIDENCE_FILE_SHA256` pins). Adding the grain inside those bundles would change a frozen control, which campaign discipline forbids, so the rows are published here instead, one file per parent, bound to the parents' receipts by `source_receipt_sha256`. `source_bindings.parent_publications` records each parent manifest's digest at publication time.

| Parent bundle | Rows |
|---|---|
| `procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2` | 897 |
| `procurement_allocation_glm53_flash_parasail_strategy_scaffold_v4_retry_after` | 237 |
| `procurement_allocation_qwen3_235b_atlascloud_case_variance_v1` | 18 |
| `procurement_allocation_qwen3_235b_google_case_variance_v1` | 107 |
| `procurement_allocation_qwen3_235b_google_constraint_ledger_v1` | 46 |
| `procurement_allocation_qwen3_235b_google_constraint_ledger_v2` | 103 |
| `procurement_allocation_qwen3_30b_coreweave_case_variance_v2` | 77 |

Produced 2026-09-07 with `aeread.shared_runner.run.publish_trajectories` from the sealed local stores; report and table digests of every parent are unchanged. See `docs/getting-started/reviewing_trajectories.md` §5.
