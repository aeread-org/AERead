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
| Grok 4.3 | 120/120 | 0 | 25.0% | -7.000 | 0.817 | 1.000 |
| Claude Haiku 4.5 | 120/120 | 0 | 33.3% | -6.000 | 1.000 | 1.000 |

The table is a completed policy-seat pilot, not a claim that the models are
ranked by utility alone. The verifier was hardened to treat null optional
refund amounts as invalid zero-amount proposals; DeepSeek and Claude were
rerun after that change. The reported means are conditional on completed
trajectories.

## Evidence

The published V2.1 evidence is committed under the family-owned bundles
`evidence/refund/refund_v2_1_deterministic_2026-09-12/` and
`evidence/refund/refund_v2_1_policy_panel_2026-09-12/`. Each bundle contains
reports, canonical benchmark tables, Procurement-style per-logical-action
trajectory rows, and a sealed `publication_manifest.json` whose digests bind
the files used for the claims above. `receipts/projections.jsonl` contains
Refund-family receipt projections, explicitly not kernel `EvaluationReceipt`
objects, because this isolated family runner does not emit shared-runner
receipts. Raw prompts, raw provider responses, and undisclosed private fields
are excluded from the publication boundary.

## Rebase and scope

The V2 files are isolated under `src/aeread_families/refund/`, with focused tests and
family documentation. No shared-runner kernel files are changed. The branch can
therefore be rebased onto `origin/main`; after rebasing, rerun the focused V2
tests and regenerate the provider evidence because report digests depend on the
exact code and provider responses.

## Validation

- `pytest -q tests/test_refund_v2.py tests/test_refund_env.py tests/test_refund_experiment.py tests/test_source_layout.py` — 61 passed.
- Provider runs use the same 120-case V2.1 panel per model and model-specific report files.
