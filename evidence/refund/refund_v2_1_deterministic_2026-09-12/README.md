# Refund V2.1 deterministic 1:N panel

This publication contains the provider-free Refund V2.1 deterministic panel:
20 fixed world seeds × six scenarios = 120 trajectories, with zero operational
failures. It is the V2.1 baseline and replaces the obsolete two-scenario V2
pilot. The summary, 120 receipt projections, and benchmark table are committed
beside this README and sealed by `publication_manifest.json`.

The panel covers full refunds, liquid-damage denials, partial software refunds,
the day-30 boundary, conflicting claims, and missing evidence. Customer facts
are disclosed gradually and payments are verifier-controlled.

This legacy bundle intentionally has no trajectory grain. Its previous custom
rows used episode-progress status semantics incompatible with the declared
kernel trajectory schema. The canonical scripted replacement is
`evidence/refund/refund_v2_1_canonical_scripted_20_2026-09-12/`, which contains
sealed shared-runner `EvaluationReceipt` projections and the canonical
per-logical-action trajectory grain.
