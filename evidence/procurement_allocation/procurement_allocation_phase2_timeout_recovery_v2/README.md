# Phase 2 provider recovery: verified live evidence

Execution status: `completed`. See [the reconciled result](reports/execution_status.json).
Independently audited receipts: 64. Recovery settled spend: $0.1049674725.
Separately audited score-free failure receipts: 0.
Combined Phase 2 settled spend, including all prior attempts:
$0.1998826335. Combined unresolved reservations:
$0.0080104500.
The combined ceiling remains $0.45. No original failed episode is pooled or replaced.

The confirmation comparison, when present, averages paired seeds within each
world and then weights the eight worlds equally. Its validity guard and support
decision are preserved; completed/replayed does not imply a feasible purchase.
Canonical buyer actions, economic outcomes, typed failures and hashes are public.
Full prompts, observations, provider reasoning, raw payloads and account metadata
remain in ignored local storage. No provider is created by the exporter.

Reproduce against the matching executed source with:
`PYTHONPATH=src python tools/publish_procurement_phase2_recovery.py --run-root runs/procurement_allocation/procurement_phase2_timeout_recovery_v2 --publication-root evidence/procurement_allocation/procurement_allocation_phase2_timeout_recovery_v2`.
The raw local run is required for independent receipt audits; the publication
contains the exact source, plan, receipt, event and billing digests.
