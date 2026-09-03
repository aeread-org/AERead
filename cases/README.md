# AERead case catalog

This directory is the canonical place to discover benchmark cases. Cases are
grouped first by benchmark family, then by a version or named split so paths
remain stable and comparable results keep their meaning.

| Family | Status | Cases | Notes |
|---|---|---|---|
| Exchange v1 | scored + specialized | [`exchange_v1/`](exchange_v1/) | Four official v0 cases, diagnostics, and two specialized worlds |
| Housing v1 | generated | [`housing_v1/`](housing_v1/) | Deterministic generated worlds; no static JSON fixtures |
| Datacenter development v1 | development | [`datacenter_development_v1/`](datacenter_development_v1/) | Financing, EPC, utility, service, and full-stack amendment negotiation with deterministic cash-flow verification |
| Procurement grounding v1 | development | [`procurement_grounding_v1/`](procurement_grounding_v1/) | One evidence-grounded 231-project sourcing case with a deterministic verifier |
| Procurement allocation v1 | development | [`procurement_allocation_v1/`](procurement_allocation_v1/) | Interactive qualification, negotiation, and award under a contribution-margin objective |
| Commercial state calibration v1 | diagnostic pilot | [`commercial_state_calibration_v1/`](commercial_state_calibration_v1/) | Nine sanitized report-authority cases for deterministic commercial-state reconstruction |
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
