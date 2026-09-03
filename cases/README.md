# AERead case catalog

This directory is the canonical place to discover benchmark cases. Cases are
grouped first by benchmark family, then by a version or named split so paths
remain stable and comparable results keep their meaning.

| Family | Status | Cases | Notes |
|---|---|---|---|
| Exchange v1 | scored + specialized | [`exchange_v1/`](exchange_v1/) | Four official v0 cases, diagnostics, and two specialized worlds |
| Housing v1 | generated | [`housing_v1/`](housing_v1/) | Deterministic generated worlds; no static JSON fixtures |
| Datacenter development v1 | development | [`datacenter_development_v1/`](datacenter_development_v1/) | Financing, EPC, utility, service, and full-stack amendment negotiation with deterministic cash-flow verification |
| Datacenter development terms v1 | diagnostic case packs | [`datacenter_development_terms_v1/`](datacenter_development_terms_v1/) | Report-only agreement-state grounding: synthetic, sanitized archive, public SEC, open-weight bridge, and paired clause-mechanism packs |
| Datacenter counteroffer adoption v1 | nested diagnostic | [`datacenter_counteroffer_adoption_v1/`](datacenter_counteroffer_adoption_v1/) | Exact written-counteroffer adoption at land, land plus power, and land plus power plus EPC depth on one pinned project |
| Datacenter counteroffer salience v1 | paired mechanism diagnostic | [`datacenter_counteroffer_salience_v1/`](datacenter_counteroffer_salience_v1/) | Full written counteroffer versus redundant public field-delta annotation on one pinned land negotiation |
| Datacenter counteroffer affordance v1 | paired mechanism diagnostic | [`datacenter_counteroffer_affordance_v1/`](datacenter_counteroffer_affordance_v1/) | Re-emit a formal written counteroffer versus accept the same offer by public ID |
| Datacenter counteroffer action schema v1 | paired mechanism diagnostic | [`datacenter_counteroffer_action_schema_v1/`](datacenter_counteroffer_action_schema_v1/) | Shared multi-action schema versus a dedicated acceptance-only post-counter schema |
| Procurement grounding v1 | development | [`procurement_grounding_v1/`](procurement_grounding_v1/) | One evidence-grounded 231-project sourcing case with a deterministic verifier |
| Procurement allocation v1 | development + confirmatory holdout | [`procurement_allocation_v1/`](procurement_allocation_v1/) | Interactive qualification, negotiation, and award under a contribution-margin objective |
| Commercial state calibration v1 | diagnostic pilot | [`commercial_state_calibration_v1/`](commercial_state_calibration_v1/) | Nine sanitized report-authority cases for deterministic commercial-state reconstruction |
| Consent/IR v1 | development | [`consent_ir_v1/`](consent_ir_v1/) | Visible-value multi-party cycle construction with strict individual-rationality checks and an exact same-information optimum |
| tau3 retail | imported base split | [`tau3_retail/`](tau3_retail/) | 114 pinned retail tasks plus provenance files |

`configs/` remains the home of experiment, treatment, and protocol settings.
Those files tune runs; they are not the canonical case catalog. The former
`configs/exchange_economy/cases_v0` path is retained as a compatibility link to
`cases/exchange_v1/v0` for existing scripts.

To compare agent frameworks on any family, follow the staged pairing, evidence,
and leaderboard protocol in
[`docs/operations/open_harness_testing.md`](../docs/operations/open_harness_testing.md).

Moving a case does not change its content hash. Adding, removing, or editing a
case inside a scored set does, and should therefore land as a new version.
