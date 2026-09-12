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
| DeepSeek V4 Flash 0731 | 112/120 | 8 | 26.8% | -6.786 | 0.911 | 1.000 |
| Gemini 2.5 Flash Lite | 120/120 | 0 | 0.8% | -9.900 | 0.517 | 0.992 |
| GPT-5.6 Luna | 119/120 | 1 | 16.0% | -8.084 | 0.782 | 0.924 |
| Grok 4.3 | 120/120 | 0 | 25.0% | -7.000 | 0.817 | 1.000 |
| Claude Haiku 4.5 | 76/120 | 44 | 52.6% | -3.684 | 1.000 | 1.000 |

The table is a completed policy-seat pilot, not a claim that the models are
ranked by utility alone. DeepSeek and Claude had operational failures caused by
provider outputs with null optional refund amounts; the verifier was hardened
to treat such proposals as invalid zero-amount proposals, and the affected
models should be rerun before a final comparative claim. The reported means are
conditional on completed trajectories.

## Evidence

The experiment runner writes a model-specific summary file plus an `evidence/`
directory. Every case has one trajectory JSON containing policy turns, customer
disclosures, transcript, handoffs, proposals, confirmations, transactions,
provider metadata, and verifier outcomes. Each trajectory directory also has a
sealed EvidenceStore event chain and content-addressed artifacts. The
`evidence_manifest.json` records the relative path and SHA-256 digest of every
trajectory. This makes the V2 output auditable in the same spirit as the V1.3
evidence workflow, while keeping the implementation isolated from the kernel.

The latest evidence-complete reruns are stored locally at:

- `/tmp/refund_v21_deepseek_policy_retry`
- `/tmp/refund_v21_gemini_policy_retry`
- `/tmp/refund_v21_gpt_5_6_luna_policy_retry`
- `/tmp/refund_v21_grok_4_3_policy_retry`
- `/tmp/refund_v21_claude_haiku_4_5_policy_retry`

## Rebase and scope

The V2 files are isolated under `src/aeread_families/refund/`, with focused tests and
family documentation. No shared-runner kernel files are changed. The branch can
therefore be rebased onto `origin/main`; after rebasing, rerun the focused V2
tests and regenerate the provider evidence because report digests depend on the
exact code and provider responses.

## Validation

- `pytest -q tests/test_refund_v2.py tests/test_refund_env.py tests/test_refund_experiment.py tests/test_source_layout.py` — 61 passed.
- Provider runs use the same 40-case panel and model-specific report filenames.
