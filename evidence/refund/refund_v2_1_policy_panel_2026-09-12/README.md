# Refund V2.1 five-model policy-seat panel

This publication contains the five-model Refund V2.1 policy-seat comparison:
20 fixed world seeds × six scenarios per model = 120 planned trajectories per
model. Intake and customer are scripted with gradual disclosure; policy is the
active Arena seat; payments remains scripted and verifier-protected.

The per-model summaries, 3,954-row sanitized trajectory grain, 600 receipt
projections, and aggregate benchmark table are committed in this bundle.
Trajectory rows use the kernel-standard
`aeread.sanitized_trajectory_row/0.1` schema, with one row per logical action.
Operational failures remain explicitly counted, and all files are sealed by
`publication_manifest.json`.

`receipts/projections.jsonl` is a Refund-family receipt projection
(`aeread.refund_v2.receipt/1.0`) over the family runner's sealed trajectory
records; it is not a kernel `EvaluationReceipt`. The projection is included to
give reviewers a stable receipt-shaped summary without claiming shared-runner
receipt replay that this family runner does not produce.
