# Timeout recovery: exact offline review package

Status: ready for human QC, not executed. Zero new live calls or model outcomes.
All three earlier attempts remain immutable, with no outcome pooling.

Contribution: `dce22532afeb71afca545e41df07888fcecb9eb0f96c01a43b8fe2e76c7f7436`.
Execution contract: `978bd81452fea5b339e546c38fb988cb4f43d81a7f8d623973a42cc420c39c6c`.

Review [the contract](../../../../../docs/families/procurement-allocation/phase2_timeout_recovery.md).
This permits one identical-request timeout retry through the existing scheduler,
with a 175-second provider deadline inside the explicit 180-second harness limit.
Unknown charges remain reserved. Second failures, changed requests and external
cancellation stop dispatch. The common budget starts at $0.102925611 accounted,
leaving $0.347074389 under the original $0.45 ceiling.

Prompts, route, worlds, seeds, economics, evidence gates and analysis are fixed.
Both canaries and all 16 pilot rows run afresh before a gated 48-row confirmation.
This does not complete or repair the previous incomplete confirmation.

Observed validation: 55 focused tests passed; full provider-free pytest results
are bound below. The complete 64-episode fixture and two identical export audits
exercise production gates and receipts. Three deliberate mutations were killed:
disabled timeout retry, dropped unknown reservation and permitted changed request.
Original bytes were restored before the full suite. The first setup-builder
failure log is retained; the subsequent tests verify the Phase 2 profile fix.

Reproduce without constructing a provider:
`PYTHONPATH=src python evidence/procurement_allocation/procurement_phase2_timeout_recovery_v1/qc/verify_review.py`.
It checks every artifact, source/test pin, all eight cases, 192 offline reference
episodes, contribution and execution contract. Full suite summary: {'tests': 4162, 'errors': 0, 'failures': 0, 'skipped': 268}.

A genuine approval of this exact contribution is required by
`phase2_admission.load_contribution`; no approval file has been created or copied.
Global `aeread errata` remains unavailable on this revision.
