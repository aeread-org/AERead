# Refund v1.3 cases

Refund v1.3 cases are authored against the versioned disclosure-and-negotiation
contract in [`refund_negotiation_case.schema.json`](refund_negotiation_case.schema.json).
The normative transition semantics are in
[`docs/families/refund/negotiation_state_machine_v1_3.md`](../../docs/families/refund/negotiation_state_machine_v1_3.md).

This directory intentionally contains the authoring contract only. Runtime
generation, the family adapter, and campaign fixtures are follow-on work; no
case is admitted to a run until that adapter validates the contract and emits
the standard shared-runner receipt.

The `dev/` directory contains three reviewed design fixtures: a clean direct
refund, a valid push-back/counteroffer, and an outside-window denial. Their
worked trajectories are documented in
[`docs/families/refund/worked_transcripts_v1_3.md`](../../docs/families/refund/worked_transcripts_v1_3.md).
