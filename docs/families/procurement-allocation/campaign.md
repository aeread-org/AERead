# Procurement allocation campaign

## Purpose

`procurement_allocation_v1` tests whether a buyer can turn provisional marketplace
listings and natural-language supplier exchanges into a valid order decision. The
buyer must obtain formal offers and exact-variant sample evidence before awarding,
then balance service, landed cost, quality, refund recovery, and working capital.

This is an `objective_reference` family. The terminal contribution margin is compared
with a deterministic full-information upper bound that is charged for every quote,
sample, and negotiation action required to reach its award. Constraint-only refund
tests and claim-grounding tests remain separate verifier families.

## Grounding boundary

The six-case variance panel is anchored to the component-family priority matrix in
`cases/procurement_grounding_v1/dev/procurement_grounding_231_projects.json`. That
snapshot covers 231 projects and 1,156 BOM rows. It is used only to choose relevant
component families and preserve their observed project/BOM counts.

Supplier names, prices, MOQs, capacities, lead times, quality observations, return
terms, and negotiation limits in the allocation cases are synthetic experimental
variables. The grounding snapshot itself says displayed prices are not verified
quotes and project BOMs are not production truth. The allocation cases therefore do
not claim current supplier availability or commercial authority.

## Declared case variance

| Case | Component-family pair | Primary decision pressure |
|---|---|---|
| `deadline_cost` | ESP32-S3 + SSD1306 OLED | Cheap late supply versus costly on-time supply |
| `quality_refund` | SHT30 + BH1750 | Unit cost versus verified yield and refund recovery |
| `moq_capacity_split` | tactile switch + KY-040 | MOQ, capacity, and multi-supplier allocation within ten actions |
| `working_capital` | DS3231 + ESP32-S3 | Prepay discount versus longer payment terms |
| `variant_substitution` | protected TP4056 + MOSFET driver | Cheap near-match listings versus exact variants |
| `service_defer` | KY-023 + SSD1306 OLED | Thin service-feasible award versus the explicit defer option |

Each case has a distinct world seed and BOM signature. Three inference seeds per case
produce 18 declared trajectories. Replicates within one case measure stochastic
reliability; they are not counted as additional independent procurement cases.

## Blinded label/order invariance campaign

`cases/procurement_allocation_v1/blinded_v3/` is a paired mirror of the six-case
panel. It preserves each objective, policy, interaction budget, substantive listing
claim, private supplier term, world seed, and deterministic full-information upper
bound. The intervention replaces suggestive supplier identifiers and names with
deterministic opaque identifiers and deterministically changes listing order.

The v3 campaign uses the same three inference seeds, model route, and Minimal Chat
harness as the v2 baseline. Rows pair by case slug and inference seed. This tests
whether procurement behavior is sensitive to semantic hints such as `value`,
`express`, or `exact`, or to presentation order. It does not add six independent
economic worlds and is not a population estimate.

A result is eligible for publication when all 18 baseline and all 18 blinded rows
are present, completed, receipt-replayed, and paired; the model route and harness
match; and each observed upper bound is invariant. Model performance is not an
eligibility gate: a lower blinded score is a valid sensitivity finding. Operational
failure, missing pairs, changed economics, or digest mismatch blocks qualification
and must not be converted into a procurement score.

## Artifact contract

- Executable inputs live under `cases/procurement_allocation_v1/`.
- Raw plans, model events, receipts, replay state, and resumable results live under
  ignored `runs/`.
- Sanitized review projections live under `evidence/<publication_id>/` and retain
  source and implementation digests.
- This document explains design and interpretation; it is not benchmark evidence.

The campaign holds Minimal Chat fixed as transport and tests the model, not one
harness against another. Completed trajectories must replay exactly. Provider errors
remain typed operational missingness and never become zero-margin procurement scores.
