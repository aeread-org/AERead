# Draft PR: Refund V2 1:N Active-Policy Pilot

## Summary

This PR adds an isolated Refund V2 1:N pilot on top of the current main-compatible
shared-runner layout. It does not modify shared-runner kernel files or existing
Refund V1.3 behavior. Each seed produces two cases: one positive apparel refund
and one liquid-damage denial, for 40 planned trajectories across 20 seeds.

The customer begins with only a public claim. The policy agent must request
missing facts in bounded batches before deciding. Intake, customer, and payments
remain scripted in the model comparison, so the experiment isolates the active
policy seat. Payments executes only a confirmed current proposal and is checked
for exactly-once execution, amount, method, and denial invariants.

## Model comparison

All models used the same 20 seeds, two cases per seed, gradual-disclosure
protocol, and Arena route. The results below are fixed-panel diagnostics, not a
claim that the models are directly interchangeable under identical provider
availability.

| Model | Completed | Operational failures | Policy compliance | Utility | Transaction | Coordination |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4 Flash 0731 | 13/40 | 27 | 0.0%* | -2.62* | 1.00* | 1.00* |
| Gemini 2.5 Flash Lite | 40/40 | 0 | 0.0% | -10.00 | 0.50 | 0.05 |
| GPT-5.6 Luna | 40/40 | 0 | 47.5% | -4.80 | 0.975 | 0.875 |
| Grok 4.3 | 39/40 | 1 | 10.3% | -9.18 | 0.487 | 1.00 |

`*` DeepSeek's run was affected by repeated empty responses and timeouts during
the multi-turn rerun; it should be treated as an operationally incomplete
measurement rather than a final model ranking.

## Evidence

The experiment runner writes a model-specific summary file plus an `evidence/`
directory. Every case has one trajectory JSON containing policy turns, customer
disclosures, transcript, provider metadata, and verifier outcomes. The
`evidence_manifest.json` records the relative path and SHA-256 digest of every
trajectory. This makes the V2 output auditable in the same spirit as the V1.3
evidence workflow, while keeping the implementation isolated from the kernel.

## Rebase and scope

The V2 files are isolated under `src/aeread/refund_v2/`, with focused tests and
family documentation. No shared-runner kernel files are changed. The branch can
therefore be rebased onto `origin/main`; after rebasing, rerun the focused V2
tests and regenerate the provider evidence because report digests depend on the
exact code and provider responses.

## Validation

- `pytest -q tests/test_refund_v2.py` — 6 passed.
- Provider runs use the same 40-case panel and model-specific report filenames.
