# Moved documents

**Status:** the redirect table for documentation paths that changed.

Source files, case packs, bridge scripts and published evidence cite documents
by repository-root path (`docs/steer_adapter_spec.md`). Many of those files are
hashed into sealed identities: an adapter pins its own source bytes as an
implementation reference, and a campaign driver records its own digest in the
bundle it publishes. Rewriting a citation there would move an identity for a
change that is not a change, so when a document moves, **the citation stays
and this table carries it**. Markdown under `docs/`, and comments and
docstrings under `tests/`, are rewritten at the time of the move.

`tests/test_docs_layout.py` reads the tables below: every `docs/…md` path cited
anywhere in the repository must exist, or appear here with a destination that
exists, or be listed under [Cited but not in this repository](#cited-but-not-in-this-repository).

When you move a document, add its row here in the same pull request.

## Moved

| Cited path | Current path | Moved |
|---|---|---|
| `docs/benchmark_qc.md` | [`docs/operations/benchmark_qc.md`](../operations/benchmark_qc.md) | phase 1 of the docs reorganisation |
| `docs/problem_bound_case_audit.md` | [`docs/research/problem_bound_case_audit.md`](../research/problem_bound_case_audit.md) | phase 1 of the docs reorganisation |
| `docs/verifier_taxonomy.md` | [`docs/research/verifier_taxonomy.md`](../research/verifier_taxonomy.md) | phase 1 of the docs reorganisation |
| `docs/agenticpay_adapter_spec.md` | [`docs/families/agenticpay-bilateral/adapter_spec.md`](../families/agenticpay-bilateral/adapter_spec.md) | #123 |
| `docs/agenticpay_adapter_status.md` | [`docs/families/agenticpay-bilateral/adapter_status.md`](../families/agenticpay-bilateral/adapter_status.md) | #123 |
| `docs/agenticpay_codex_triage.md` | [`docs/families/agenticpay-bilateral/reviews/agenticpay_codex_triage.md`](../families/agenticpay-bilateral/reviews/agenticpay_codex_triage.md) | #123 |
| `docs/agenticpay_migration_plan.md` | [`docs/families/agenticpay-bilateral/migration_plan.md`](../families/agenticpay-bilateral/migration_plan.md) | #123 |
| `docs/agenticpay_migration_review.md` | [`docs/families/agenticpay-bilateral/migration_review.md`](../families/agenticpay-bilateral/migration_review.md) | #123 |
| `docs/agenticpay_review_claude.md` | [`docs/families/agenticpay-bilateral/reviews/agenticpay_review_claude.md`](../families/agenticpay-bilateral/reviews/agenticpay_review_claude.md) | #123 |
| `docs/agenticpay_review_codex.md` | [`docs/families/agenticpay-bilateral/reviews/agenticpay_review_codex.md`](../families/agenticpay-bilateral/reviews/agenticpay_review_codex.md) | #123 |
| `docs/agenticpay_review_disposition.md` | [`docs/families/agenticpay-bilateral/reviews/agenticpay_review_disposition.md`](../families/agenticpay-bilateral/reviews/agenticpay_review_disposition.md) | #123 |
| `docs/alympics_adapter_spec.md` | [`docs/families/alympics-wac/adapter_spec.md`](../families/alympics-wac/adapter_spec.md) | #123 |
| `docs/alympics_adapter_status.md` | [`docs/families/alympics-wac/adapter_status.md`](../families/alympics-wac/adapter_status.md) | #123 |
| `docs/alympics_codex_triage.md` | [`docs/families/alympics-wac/reviews/alympics_codex_triage.md`](../families/alympics-wac/reviews/alympics_codex_triage.md) | #123 |
| `docs/alympics_fix_verification.md` | [`docs/families/alympics-wac/reviews/alympics_fix_verification.md`](../families/alympics-wac/reviews/alympics_fix_verification.md) | #123 |
| `docs/alympics_migration_plan.md` | [`docs/families/alympics-wac/migration_plan.md`](../families/alympics-wac/migration_plan.md) | #123 |
| `docs/alympics_migration_review.md` | [`docs/families/alympics-wac/migration_review.md`](../families/alympics-wac/migration_review.md) | #123 |
| `docs/alympics_review_claude.md` | [`docs/families/alympics-wac/reviews/alympics_review_claude.md`](../families/alympics-wac/reviews/alympics_review_claude.md) | #123 |
| `docs/alympics_review_codex.md` | [`docs/families/alympics-wac/reviews/alympics_review_codex.md`](../families/alympics-wac/reviews/alympics_review_codex.md) | #123 |
| `docs/alympics_review_disposition.md` | [`docs/families/alympics-wac/reviews/alympics_review_disposition.md`](../families/alympics-wac/reviews/alympics_review_disposition.md) | #123 |
| `docs/amazonbarg_adapter_spec.md` | [`docs/families/amazonbarg/adapter_spec.md`](../families/amazonbarg/adapter_spec.md) | #123 |
| `docs/amazonbarg_adapter_status.md` | [`docs/families/amazonbarg/adapter_status.md`](../families/amazonbarg/adapter_status.md) | #123 |
| `docs/amazonbarg_codex_triage.md` | [`docs/families/amazonbarg/reviews/amazonbarg_codex_triage.md`](../families/amazonbarg/reviews/amazonbarg_codex_triage.md) | #123 |
| `docs/amazonbarg_fix_verification.md` | [`docs/families/amazonbarg/reviews/amazonbarg_fix_verification.md`](../families/amazonbarg/reviews/amazonbarg_fix_verification.md) | #123 |
| `docs/amazonbarg_migration_plan.md` | [`docs/families/amazonbarg/migration_plan.md`](../families/amazonbarg/migration_plan.md) | #123 |
| `docs/amazonbarg_migration_review.md` | [`docs/families/amazonbarg/migration_review.md`](../families/amazonbarg/migration_review.md) | #123 |
| `docs/amazonbarg_review_claude.md` | [`docs/families/amazonbarg/reviews/amazonbarg_review_claude.md`](../families/amazonbarg/reviews/amazonbarg_review_claude.md) | #123 |
| `docs/amazonbarg_review_codex.md` | [`docs/families/amazonbarg/reviews/amazonbarg_review_codex.md`](../families/amazonbarg/reviews/amazonbarg_review_codex.md) | #123 |
| `docs/amazonbarg_review_disposition.md` | [`docs/families/amazonbarg/reviews/amazonbarg_review_disposition.md`](../families/amazonbarg/reviews/amazonbarg_review_disposition.md) | #123 |
| `docs/aucarena_adapter_spec.md` | [`docs/families/aucarena/adapter_spec.md`](../families/aucarena/adapter_spec.md) | #123 |
| `docs/aucarena_adapter_status.md` | [`docs/families/aucarena/adapter_status.md`](../families/aucarena/adapter_status.md) | #123 |
| `docs/aucarena_codex_triage.md` | [`docs/families/aucarena/reviews/aucarena_codex_triage.md`](../families/aucarena/reviews/aucarena_codex_triage.md) | #123 |
| `docs/aucarena_fix_verification.md` | [`docs/families/aucarena/reviews/aucarena_fix_verification.md`](../families/aucarena/reviews/aucarena_fix_verification.md) | #123 |
| `docs/aucarena_migration_plan.md` | [`docs/families/aucarena/migration_plan.md`](../families/aucarena/migration_plan.md) | #123 |
| `docs/aucarena_migration_review.md` | [`docs/families/aucarena/migration_review.md`](../families/aucarena/migration_review.md) | #123 |
| `docs/aucarena_review_claude.md` | [`docs/families/aucarena/reviews/aucarena_review_claude.md`](../families/aucarena/reviews/aucarena_review_claude.md) | #123 |
| `docs/aucarena_review_codex.md` | [`docs/families/aucarena/reviews/aucarena_review_codex.md`](../families/aucarena/reviews/aucarena_review_codex.md) | #123 |
| `docs/aucarena_review_disposition.md` | [`docs/families/aucarena/reviews/aucarena_review_disposition.md`](../families/aucarena/reviews/aucarena_review_disposition.md) | #123 |
| `docs/ci_cancellation_context_diagnosis.md` | [`docs/architecture/reviews/ci_cancellation_context_diagnosis.md`](../architecture/reviews/ci_cancellation_context_diagnosis.md) | #123 |
| `docs/collusion_adapter_spec.md` | [`docs/families/collusion/adapter_spec.md`](../families/collusion/adapter_spec.md) | #123 |
| `docs/collusion_adapter_status.md` | [`docs/families/collusion/adapter_status.md`](../families/collusion/adapter_status.md) | #123 |
| `docs/collusion_codex_triage.md` | [`docs/families/collusion/reviews/collusion_codex_triage.md`](../families/collusion/reviews/collusion_codex_triage.md) | #123 |
| `docs/collusion_fix_verification.md` | [`docs/families/collusion/reviews/collusion_fix_verification.md`](../families/collusion/reviews/collusion_fix_verification.md) | #123 |
| `docs/collusion_migration_review.md` | [`docs/families/collusion/migration_review.md`](../families/collusion/migration_review.md) | #123 |
| `docs/collusion_review_claude.md` | [`docs/families/collusion/reviews/collusion_review_claude.md`](../families/collusion/reviews/collusion_review_claude.md) | #123 |
| `docs/collusion_review_codex.md` | [`docs/families/collusion/reviews/collusion_review_codex.md`](../families/collusion/reviews/collusion_review_codex.md) | #123 |
| `docs/collusion_review_disposition.md` | [`docs/families/collusion/reviews/collusion_review_disposition.md`](../families/collusion/reviews/collusion_review_disposition.md) | #123 |
| `docs/econagent_adapter_spec.md` | [`docs/families/econagent/adapter_spec.md`](../families/econagent/adapter_spec.md) | #123 |
| `docs/econagent_adapter_status.md` | [`docs/families/econagent/adapter_status.md`](../families/econagent/adapter_status.md) | #123 |
| `docs/econagent_codex_triage.md` | [`docs/families/econagent/reviews/econagent_codex_triage.md`](../families/econagent/reviews/econagent_codex_triage.md) | #123 |
| `docs/econagent_fix_verification.md` | [`docs/families/econagent/reviews/econagent_fix_verification.md`](../families/econagent/reviews/econagent_fix_verification.md) | #123 |
| `docs/econagent_migration_plan.md` | [`docs/families/econagent/migration_plan.md`](../families/econagent/migration_plan.md) | #123 |
| `docs/econagent_migration_review.md` | [`docs/families/econagent/migration_review.md`](../families/econagent/migration_review.md) | #123 |
| `docs/econagent_review_claude.md` | [`docs/families/econagent/reviews/econagent_review_claude.md`](../families/econagent/reviews/econagent_review_claude.md) | #123 |
| `docs/econagent_review_codex.md` | [`docs/families/econagent/reviews/econagent_review_codex.md`](../families/econagent/reviews/econagent_review_codex.md) | #123 |
| `docs/econagent_review_disposition.md` | [`docs/families/econagent/reviews/econagent_review_disposition.md`](../families/econagent/reviews/econagent_review_disposition.md) | #123 |
| `docs/econevals_adapter_spec.md` | [`docs/families/econevals/adapter_spec.md`](../families/econevals/adapter_spec.md) | #123 |
| `docs/econevals_adapter_status.md` | [`docs/families/econevals/adapter_status.md`](../families/econevals/adapter_status.md) | #123 |
| `docs/econevals_review_claude.md` | [`docs/families/econevals/reviews/econevals_review_claude.md`](../families/econevals/reviews/econevals_review_claude.md) | #123 |
| `docs/econevals_review_codex.md` | [`docs/families/econevals/reviews/econevals_review_codex.md`](../families/econevals/reviews/econevals_review_codex.md) | #123 |
| `docs/econevals_review_disposition.md` | [`docs/families/econevals/reviews/econevals_review_disposition.md`](../families/econevals/reviews/econevals_review_disposition.md) | #123 |
| `docs/govsim_adapter_spec.md` | [`docs/families/govsim/adapter_spec.md`](../families/govsim/adapter_spec.md) | #123 |
| `docs/govsim_adapter_status.md` | [`docs/families/govsim/adapter_status.md`](../families/govsim/adapter_status.md) | #123 |
| `docs/govsim_codex_triage.md` | [`docs/families/govsim/reviews/govsim_codex_triage.md`](../families/govsim/reviews/govsim_codex_triage.md) | #123 |
| `docs/govsim_fix_verification.md` | [`docs/families/govsim/reviews/govsim_fix_verification.md`](../families/govsim/reviews/govsim_fix_verification.md) | #123 |
| `docs/govsim_review_claude.md` | [`docs/families/govsim/reviews/govsim_review_claude.md`](../families/govsim/reviews/govsim_review_claude.md) | #123 |
| `docs/govsim_review_codex.md` | [`docs/families/govsim/reviews/govsim_review_codex.md`](../families/govsim/reviews/govsim_review_codex.md) | #123 |
| `docs/govsim_review_disposition.md` | [`docs/families/govsim/reviews/govsim_review_disposition.md`](../families/govsim/reviews/govsim_review_disposition.md) | #123 |
| `docs/kernel_contract_design_critique.md` | [`docs/architecture/reviews/kernel_contract_design_critique.md`](../architecture/reviews/kernel_contract_design_critique.md) | #123 |
| `docs/kernel_contract_gap_review.md` | [`docs/architecture/reviews/kernel_contract_gap_review.md`](../architecture/reviews/kernel_contract_gap_review.md) | #123 |
| `docs/kernel_contract_impl_review.md` | [`docs/architecture/reviews/kernel_contract_impl_review.md`](../architecture/reviews/kernel_contract_impl_review.md) | #123 |
| `docs/kernel_contract_rebase_review.md` | [`docs/architecture/reviews/kernel_contract_rebase_review.md`](../architecture/reviews/kernel_contract_rebase_review.md) | #123 |
| `docs/kernel_r12_seat_context.md` | [`docs/architecture/reviews/kernel_r12_seat_context.md`](../architecture/reviews/kernel_r12_seat_context.md) | #123 |
| `docs/kernel_r13_conditional_leaves.md` | [`docs/architecture/reviews/kernel_r13_conditional_leaves.md`](../architecture/reviews/kernel_r13_conditional_leaves.md) | #123 |
| `docs/kernel_r9r10_review.md` | [`docs/architecture/reviews/kernel_r9r10_review.md`](../architecture/reviews/kernel_r9r10_review.md) | #123 |
| `docs/negarena_adapter_spec.md` | [`docs/families/negarena/adapter_spec.md`](../families/negarena/adapter_spec.md) | #123 |
| `docs/negarena_adapter_status.md` | [`docs/families/negarena/adapter_status.md`](../families/negarena/adapter_status.md) | #123 |
| `docs/negarena_codex_triage.md` | [`docs/families/negarena/reviews/negarena_codex_triage.md`](../families/negarena/reviews/negarena_codex_triage.md) | #123 |
| `docs/negarena_fix_verification.md` | [`docs/families/negarena/reviews/negarena_fix_verification.md`](../families/negarena/reviews/negarena_fix_verification.md) | #123 |
| `docs/negarena_migration_plan.md` | [`docs/families/negarena/migration_plan.md`](../families/negarena/migration_plan.md) | #123 |
| `docs/negarena_migration_review.md` | [`docs/families/negarena/migration_review.md`](../families/negarena/migration_review.md) | #123 |
| `docs/negarena_review_claude.md` | [`docs/families/negarena/reviews/negarena_review_claude.md`](../families/negarena/reviews/negarena_review_claude.md) | #123 |
| `docs/negarena_review_codex.md` | [`docs/families/negarena/reviews/negarena_review_codex.md`](../families/negarena/reviews/negarena_review_codex.md) | #123 |
| `docs/negarena_review_disposition.md` | [`docs/families/negarena/reviews/negarena_review_disposition.md`](../families/negarena/reviews/negarena_review_disposition.md) | #123 |
| `docs/refund_case.md` | [`docs/families/refund/case.md`](../families/refund/case.md) | #123 |
| `docs/refund_deepseek_v4_profiles_2026-09-11.md` | [`docs/families/refund/deepseek_v4_profiles_2026-09-11.md`](../families/refund/deepseek_v4_profiles_2026-09-11.md) | #123 |
| `docs/refund_reasoning_experiment.md` | [`docs/families/refund/reasoning_experiment.md`](../families/refund/reasoning_experiment.md) | #123 |
| `docs/runner_hardening_report.md` | [`docs/architecture/reviews/runner_hardening_report.md`](../architecture/reviews/runner_hardening_report.md) | #123 |
| `docs/steer_adapter_spec.md` | [`docs/families/steer/adapter_spec.md`](../families/steer/adapter_spec.md) | #123 |
| `docs/steer_adapter_status.md` | [`docs/families/steer/adapter_status.md`](../families/steer/adapter_status.md) | #123 |
| `docs/steer_codex_triage.md` | [`docs/families/steer/reviews/steer_codex_triage.md`](../families/steer/reviews/steer_codex_triage.md) | #123 |
| `docs/steer_fix_verification.md` | [`docs/families/steer/reviews/steer_fix_verification.md`](../families/steer/reviews/steer_fix_verification.md) | #123 |
| `docs/steer_migration_plan.md` | [`docs/families/steer/migration_plan.md`](../families/steer/migration_plan.md) | #123 |
| `docs/steer_migration_review.md` | [`docs/families/steer/migration_review.md`](../families/steer/migration_review.md) | #123 |
| `docs/steer_review_claude.md` | [`docs/families/steer/reviews/steer_review_claude.md`](../families/steer/reviews/steer_review_claude.md) | #123 |
| `docs/steer_review_codex.md` | [`docs/families/steer/reviews/steer_review_codex.md`](../families/steer/reviews/steer_review_codex.md) | #123 |
| `docs/steer_review_disposition.md` | [`docs/families/steer/reviews/steer_review_disposition.md`](../families/steer/reviews/steer_review_disposition.md) | #123 |
| `docs/termsbench_adapter_spec.md` | [`docs/families/termsbench/adapter_spec.md`](../families/termsbench/adapter_spec.md) | #123 |
| `docs/termsbench_adapter_status.md` | [`docs/families/termsbench/adapter_status.md`](../families/termsbench/adapter_status.md) | #123 |
| `docs/termsbench_codex_triage.md` | [`docs/families/termsbench/reviews/termsbench_codex_triage.md`](../families/termsbench/reviews/termsbench_codex_triage.md) | #123 |
| `docs/termsbench_review_claude.md` | [`docs/families/termsbench/reviews/termsbench_review_claude.md`](../families/termsbench/reviews/termsbench_review_claude.md) | #123 |
| `docs/termsbench_review_codex.md` | [`docs/families/termsbench/reviews/termsbench_review_codex.md`](../families/termsbench/reviews/termsbench_review_codex.md) | #123 |
| `docs/termsbench_review_disposition.md` | [`docs/families/termsbench/reviews/termsbench_review_disposition.md`](../families/termsbench/reviews/termsbench_review_disposition.md) | #123 |

## Cited but not in this repository

Paths that source, tests or documents cite and that were never committed to
`main`. They are listed so the citation is not mistaken for a broken link, and
so the guard fails on a new dangling citation rather than on these.

| Cited path | Where it is |
|---|---|
| `docs/design/2026-07-06_oracle_carveout_spec.md` | private development repository; this repository is a curated export (`export_manifest.json`) |
| `docs/design/2026-07-08_carveout_oracle_unsaturated.md` | private development repository |
| `docs/exchange_economy/benchmark_scoping/2026-07-01_bundle_under_budget_env_spec.md` | private development repository |
| `docs/exchange_economy/benchmark_scoping/2026-07-01_supply_chain_procurement_scenario.md` | private development repository |
| `docs/exchange_economy/v1_baselines.md` | private development repository |
| `docs/exchange_economy/v1_filter_decisions.md` | private development repository |
| `docs/experiments/2026-07-06_oracle_carveout_spec.md` | private development repository |
| `docs/govsim_migration_plan.md` | branch `zeyu/govsim-contract-migration` (35cf3d73), never merged to `main` |
| `docs/govsim_migration_review.md` | branch `zeyu/govsim-contract-migration` (35cf3d73), never merged to `main` |
| `docs/kernel_scripted_seats_design.md` | open pull request #150; its home on merge is `docs/architecture/` |
| `docs/operations/errata.md` | open pull request #117 |
| `docs/superpowers/specs/2026-09-07-issue-135-repair-design.md` | a session-local design note for #135; the ruling is on the issue |
