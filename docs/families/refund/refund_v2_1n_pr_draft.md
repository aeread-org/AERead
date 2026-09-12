# Draft PR: Refund V2.1 1:N Selectable-Agent Pilot

## Summary

This PR adds an isolated Refund V2.1 1:N pilot on top of the current main-compatible
shared-runner layout. It does not modify shared-runner kernel files or existing
Refund V1.3 behavior. Each seed produces six cases spanning positive, partial,
boundary, conflict, and evidence-gated denial scenarios, for 120 planned
trajectories across 20 seeds.

The customer begins with only a public claim. Facts are disclosed gradually in
bounded batches of at most three fields. The `intake`, `customer`, and `policy`
seats are independently selectable with `--active-agents`; unselected seats use
deterministic counterparts. This supports controlled comparisons of one active
LLM, any pair, or all three active LLM seats without changing the case panel.
Payments remains scripted and verifier-protected: it executes only a confirmed
current proposal and is checked for exactly-once execution, amount, method, and
denial invariants.

Examples:

- `--active-agents policy` — backward-compatible policy-agent pilot.
- `--active-agents intake,customer,policy` — all three decision seats active.
- `--active-agents customer` — active disclosure behavior with scripted intake and policy.

## Five-model policy-seat panel

The primary V2.1 comparison uses 20 fixed world seeds and six scenarios per
seed, for 120 planned trajectories per model. Only `policy` is active in this
block; intake, customer, and payments are scripted. These results are
descriptive and preserve operational failures rather than silently dropping
them.

| Model | Completed | Operational failures | Policy compliance | Utility | Transaction | Coordination |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 120/120 | 0 | 30.0% | -6.400 | 0.950 | 1.000 |
| Gemini 2.5 Flash Lite | 120/120 | 0 | 0.8% | -9.900 | 0.517 | 0.992 |
| GPT-5.6 Luna | 119/120 | 1 | 16.0% | -8.084 | 0.782 | 0.924 |
| Grok 4.3 | 120/120 | 0 | 52.5% | -3.833 | 0.992 | 0.708 |
| Claude Haiku 4.5 | 120/120 | 0 | 33.3% | -6.000 | 1.000 | 1.000 |

The table is a completed policy-seat pilot, not a claim that the models are
ranked by utility alone. The verifier was hardened to treat null optional
refund amounts as invalid zero-amount proposals; DeepSeek and Claude were
rerun after that change. The Grok row was regenerated on 2026-09-12 with the
current shared-runner publication path. The reported means are conditional on
completed trajectories.

## Evidence

The canonical shared-runner publication is generated under
`evidence/refund/refund_v2_1_canonical_scripted_20_2026-09-12/`. It contains
`README.md`, `reports/summary.json`, `reports/qualification.json`, canonical
benchmark tables, a Refund-specific scenario result table, sealed receipt
projections, the kernel `aeread.sanitized_trajectory_row/0.1` grain, and a
sealed `publication_manifest.json`. The manifest digests bind every published
file to the shared-runner `RunPlan`, sealed `EvaluationReceipt`s, and source
run. Raw prompts, raw provider responses, hidden facts, complete receipts, and
reasoning are excluded from the publication boundary. The earlier deterministic
and five-model bundles remain historical publications.

The latest Grok 4.3 publication is under
`evidence/refund/refund_v2_1_grok43_controlled_2026-09-12/`; it contains the
same canonical artifact family and 820 sanitized logical-action rows.

## Rebase and scope

The V2 files are isolated under `src/aeread_families/refund/`, with focused tests and
family documentation. No shared-runner kernel files are changed. The branch can
therefore be rebased onto `origin/main`; after rebasing, rerun the focused V2
tests and regenerate the provider evidence because report digests depend on the
exact code and provider responses.

## Validation

- `pytest -q tests/test_refund_v2.py tests/test_refund_env.py tests/test_refund_experiment.py tests/test_source_layout.py` — 61 passed.
- Provider runs use the same 120-case V2.1 panel per model and model-specific report files.
