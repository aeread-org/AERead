# Provider recovery: exact review package

Status: ready for human QC, not executed. Zero new provider calls, zero model
observations. The two prior stopped attempts remain immutable and are not pooled.

Contribution digest: `9ba4adfd8cdcf9e9a3996830e225136d138179f7618668f76b33ed23263d9191`.
Execution contract digest: `9287428d63f30345dd131acccbafef7c71f9cc26cc728f07802f8c295fd932ef`.

Review [the operational recovery](../../../../../docs/families/procurement-allocation/phase2_provider_recovery.md)
and `contribution_contract.json`. Changes preserve original provider exception
messages privately, export only verified hashes, and carry both prior attempts'
settled spend and unknown-charge reservations into every budget check.

The same full 16-row pilot gates the 48-row confirmation. Model/provider route,
buyer prompts, world/economic/scoring rules, seeds, retry policy and analysis are
unchanged. Both prior attempts remain failed. Provider recovery is not established;
another 429 might stop this attempt, but the adapter's error message will survive.

The same combined $0.45 ceiling now starts at $0.0311531355 accounted:
$0.0260186355 settled plus $0.0051345 reserved. $0.4188468645 remains.

Observed validation: 48 focused tests passed; the full provider-free suite passed
with counts and upstream skips in logs/XML. The 64-episode fixture campaign and
two identical publication audits are software checks, not model observations.
All three deliberate mutations were killed: lost message, dropped prior reserve,
and public message leak. Original source bytes were restored before the full suite.

Reproduce with:
`PYTHONPATH=src python evidence/procurement_allocation/procurement_phase2_provider_recovery_v1/qc/verify_review.py`.
This checks source/schema/test/file digests, all eight cases, the 192 reference
episodes and four offline policies, both prior publication identities, and the
retained mutation checks. No provider is constructed.

A real approval of this new contribution digest is required by
`phase2_admission.load_contribution`. Old approval records are not copied.
No new `human_qc_approval.json` exists. Global `aeread errata` is unavailable
on this revision; these are scoped QC and incident records.
