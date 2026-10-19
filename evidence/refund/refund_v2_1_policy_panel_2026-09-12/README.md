# Refund V2.1 five-model policy-seat panel

This publication contains the five-model Refund V2.1 policy-seat comparison:
20 fixed world seeds × six scenarios per model = 120 planned trajectories per
model. Intake and customer are scripted with gradual disclosure; policy is the
active Arena seat; payments remains scripted and verifier-protected.

The per-model summaries, 600 receipt projections, and aggregate benchmark
table are committed in this legacy bundle. Operational failures remain
explicitly counted, and all files are sealed by `publication_manifest.json`.

This legacy bundle intentionally has no trajectory grain. Its previous custom
rows used episode-progress status semantics incompatible with the declared
kernel trajectory schema. The canonical successor publications for Grok,
Gemini, GPT, and DeepSeek are under
`evidence/refund/refund_v2_1_*_controlled_2026-09-12/`; each contains sealed
shared-runner `EvaluationReceipt` projections and canonical per-logical-action
trajectory rows.
