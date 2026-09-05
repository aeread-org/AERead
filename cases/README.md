# AERead case catalog

This directory is the canonical place to discover benchmark cases. Cases are
grouped first by benchmark family, then by a version or named split so paths
remain stable and comparable results keep their meaning.

| Family | Status | Cases | Notes |
|---|---|---|---|
| Collusion | scored (milestones 1-3) | [`collusion/`](collusion/) | 6-cell repeated Bertrand-logit duopoly pilot with closed-form gold references, four measurement leaves, scripted-policy harness, and offline replay; no live-agent run yet |
| Exchange v1 | scored + specialized | [`exchange_v1/`](exchange_v1/) | Four official v0 cases, diagnostics, and two specialized worlds |
| GovSim | cases + environment (scorer pending) | [`govsim/`](govsim/) | 9 generated cells (3 common-pool-resource scenarios x 3 scripted policies) wrapping a pinned upstream checkout |
| Housing v1 | generated | [`housing_v1/`](housing_v1/) | Deterministic generated worlds; no static JSON fixtures |
| negarena | development | [`negarena/`](negarena/) | Six authored bilateral-negotiation scenarios (buy/sell, ultimatum) over a pinned upstream engine |
| Datacenter development v1 | development | [`datacenter_development_v1/`](datacenter_development_v1/) | Financing, EPC, utility, service, and full-stack amendment negotiation with deterministic cash-flow verification |
| Procurement grounding v1 | development | [`procurement_grounding_v1/`](procurement_grounding_v1/) | One evidence-grounded 231-project sourcing case with a deterministic verifier |
| Procurement allocation v1 | development + confirmatory + targeted holdouts | [`procurement_allocation_v1/`](procurement_allocation_v1/) | Interactive qualification, negotiation, and award under a contribution-margin objective |
| Commercial state calibration v1 | diagnostic pilot | [`commercial_state_calibration_v1/`](commercial_state_calibration_v1/) | Nine sanitized report-authority cases for deterministic commercial-state reconstruction |
| Consent/IR v1 | development | [`consent_ir_v1/`](consent_ir_v1/) | Visible-value multi-party cycle construction with strict individual-rationality checks and an exact same-information optimum |
| tau3 retail | imported base split | [`tau3_retail/`](tau3_retail/) | 114 pinned retail tasks plus provenance files |
| STEER | imported pilot corpus, cases only | [`steer/`](steer/) | 1,595 one-shot MCQA cases (200 per element, capped at availability) across 8 declared elements / 4 taxonomy branches; no scorer yet |

`configs/` remains the home of experiment, treatment, and protocol settings.
Those files tune runs; they are not the canonical case catalog. The former
`configs/exchange_economy/cases_v0` path is retained as a compatibility link to
`cases/exchange_v1/v0` for existing scripts.

To compare agent frameworks on any family, follow the staged pairing, evidence,
and leaderboard protocol in
[`docs/operations/open_harness_testing.md`](../docs/operations/open_harness_testing.md).

Moving a case does not change its content hash. Adding, removing, or editing a
case inside a scored set does, and should therefore land as a new version.
