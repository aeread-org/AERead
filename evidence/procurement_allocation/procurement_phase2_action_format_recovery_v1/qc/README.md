# Action-format recovery: exact review package

Status: ready for human QC, not executed. This package contains zero recovery
model observations and zero recovery provider calls. The original failed pilot
remains immutable and is excluded from any future effect estimate.

Contribution digest: `2aad8f21431d39fc18b5c6fd18418d43244e3399192714eefcb2dd08f6f821aa`.
Execution contract digest: `5f7978315aabebc74dba9c6397200a8c65fcfd56c93c7abc0c970880b08fbcec`.

Review [the scoped repair](../../../../../docs/families/procurement-allocation/phase2_action_format_recovery.md)
and `contribution_contract.json`. Both arms now receive explicit required-field
instructions and matching schema descriptions. The verifier, worlds, economic
rules, route, seeds and analysis are unchanged. The nullable wire schema is still
subject to parser validation; improved live compliance has not been demonstrated.

The recovery includes the full 16-row pilot, then the 48-row confirmation only if
its gates pass. The original $0.0099593505 is carried forward against the same
combined $0.45 ceiling, leaving $0.4400406495. No extra spending ceiling is requested.

Observed local checks: 42 focused tests and the full provider-free suite passed.
See the logs/XML for counts and upstream-dependent skips. The 64 fixture episodes
are software checks, not model performance. Eleven original invalid outputs remain
rejected; one-field parser counterfactuals do not rescore or replace those outcomes.

Reproduce this bundle with:
`PYTHONPATH=src python evidence/procurement_allocation/procurement_phase2_action_format_recovery_v1/qc/verify_review.py`.
The script verifies file digests, source pins, test results, all 8 cases, the 192
reference episodes and all four offline policies. No provider is constructed.

A genuine approval of this new contribution digest is required by
`phase2_admission.load_contribution`. The old approval is not copied or relabelled.
No recovery `human_qc_approval.json` exists. Global `aeread errata` is unavailable
on this revision; these are scoped evidence and incident records only.
