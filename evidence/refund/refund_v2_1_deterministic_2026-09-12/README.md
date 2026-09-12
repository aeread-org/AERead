# Refund V2.1 deterministic 1:N panel

This publication contains the provider-free Refund V2.1 deterministic panel:
20 fixed world seeds × six scenarios = 120 trajectories, with zero operational
failures. It is the V2.1 baseline and replaces the obsolete two-scenario V2
pilot. The summary, 1,080-row sanitized trajectory grain, 120 receipt
projections, and benchmark table are committed beside this README and sealed by
`publication_manifest.json`. The trajectory file uses the kernel-standard
`aeread.sanitized_trajectory_row/0.1` schema, with one row per logical action;
prompts and raw provider payloads are excluded.

The panel covers full refunds, liquid-damage denials, partial software refunds,
the day-30 boundary, conflicting claims, and missing evidence. Customer facts
are disclosed gradually and payments are verifier-controlled.

`receipts/projections.jsonl` is a Refund-family receipt projection
(`aeread.refund_v2.receipt/1.0`) over the family runner's sealed trajectory
records; it is not a kernel `EvaluationReceipt`. The projection is included to
give reviewers a stable receipt-shaped summary without claiming shared-runner
receipt replay that this family runner does not produce.
