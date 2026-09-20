# Timeout recovery: exact offline review package

Status: ready for human QC, not executed. Zero new live calls or model outcomes.
This V2 supersedes the unexecuted V1 review at b727feb2, correcting the
Python 3.10 distinction between asynchronous and built-in timeout classes.
All three earlier attempts remain immutable, with no outcome pooling.

Contribution: `1ae5c78733b420bcd6ad8e50cd5dc9ab2fc0365c40b087d0215256a69a00c511`.
Execution contract: `8424c1e9d3ac49290eaa82e149c60a045c7eb0ea6778b68274d95f1ff57e6ad7`.

Review [the contract](../../../../../docs/families/procurement-allocation/phase2_timeout_recovery.md).
This permits one identical-request timeout retry through the existing scheduler,
with a 175-second provider deadline inside the explicit 180-second harness limit.
Unknown charges remain reserved. Second failures, changed requests and external
cancellation stop dispatch. The common budget starts at $0.102925611 accounted,
leaving $0.347074389 under the original $0.45 ceiling.

Prompts, route, worlds, seeds, economics, evidence gates and analysis are fixed.
Both canaries and all 16 pilot rows run afresh before a gated 48-row confirmation.
This does not complete or repair the previous incomplete confirmation.

Observed validation: 55 focused tests passed on each of Python 3.10 and 3.12; full provider-free pytest results
are bound below. The complete 64-episode fixture and two identical export audits
exercise production gates and receipts. Three deliberate mutations were killed:
disabled timeout retry, dropped unknown reservation and permitted changed request.
Original bytes were restored before the full suite. The superseded V1 candidate reproduced four failed and two passing timeout
tests on Python 3.10 in an isolated worktree; that failure log is retained.
Earlier authoring failures and reviews remain under their original identities.

Reproduce without constructing a provider:
`PYTHONPATH=src python evidence/procurement_allocation/procurement_phase2_timeout_recovery_v2/qc/verify_review.py`.
It checks every artifact, source/test pin, all eight cases, 192 offline reference
episodes, contribution and execution contract. Full suite summary: {'tests': 4162, 'errors': 0, 'failures': 0, 'skipped': 268}.

A genuine approval of this exact contribution is required by
`phase2_admission.load_contribution`; no approval file has been created or copied.
Global `aeread errata` remains unavailable on this revision.
