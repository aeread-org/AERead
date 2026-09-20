# Phase 2 v1: stopped operational pilot

Live model evidence: 16 pilot episodes, 16 independently re-audited receipts,
11 malformed-action failures, one profitable control award, four trap deferrals.
The operational gate failed. All 48 confirmatory episodes remain unexecuted;
there is no confirmatory plan digest and no treatment-effect claim.

Total settled API spend, including two unscored canaries: $0.0099593505 from
27 requests. No unresolved billing reservations or performance retries.

All 11 failed outputs satisfy the provider's nullable superset JSON schema
but omit an action-specific required value: message (9), proposal (1), fields (1).
The common prompt did not enumerate these requirements. This is an observed
interface failure; it does not identify economic reasoning quality.

The exact canonical actions are in qc/action_format_diagnosis.json. Provider
reasoning, prompts, observations, raw payloads and account metadata are excluded.
Receipt/event/file hashes bind this view to the ignored local raw records.

Reproduce the raw audit at source revision
1bae6714ff8b31fea8d28d5e9207e99c302cc4ff with tools/publish_procurement_phase2_pilot.py
from this publication commit. No provider is instantiated by the exporter.
The original offline admission bundle and stopped attempt remain immutable.
Any action-format repair uses a separate campaign identity and review.
