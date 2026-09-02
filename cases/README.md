# AERead case catalog

This directory is the canonical place to discover benchmark cases. Cases are
grouped first by benchmark family, then by a version or named split so paths
remain stable and comparable results keep their meaning.

| Family | Status | Cases | Notes |
|---|---|---|---|
| Collusion | environment pilot (cases + environment only) | [`collusion/`](collusion/) | 6-cell repeated Bertrand-logit duopoly pilot with closed-form gold references; scorer lands in a later milestone |
| Exchange v1 | scored + specialized | [`exchange_v1/`](exchange_v1/) | Four official v0 cases, diagnostics, and two specialized worlds |
| Housing v1 | generated | [`housing_v1/`](housing_v1/) | Deterministic generated worlds; no static JSON fixtures |
| Procurement grounding v1 | development | [`procurement_grounding_v1/`](procurement_grounding_v1/) | One evidence-grounded 231-project sourcing case with a deterministic verifier |
| tau3 retail | imported base split | [`tau3_retail/`](tau3_retail/) | 114 pinned retail tasks plus provenance files |

`configs/` remains the home of experiment, treatment, and protocol settings.
Those files tune runs; they are not the canonical case catalog. The former
`configs/exchange_economy/cases_v0` path is retained as a compatibility link to
`cases/exchange_v1/v0` for existing scripts.

To compare agent frameworks on any family, follow the staged pairing, evidence,
and leaderboard protocol in
[`docs/open_harness_testing.md`](../docs/open_harness_testing.md).

Moving a case does not change its content hash. Adding, removing, or editing a
case inside a scored set does, and should therefore land as a new version.
