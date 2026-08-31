# AERead capability coverage map

AERead's goal is a general evaluation of agent economic capabilities. This matrix is
the honest state of that claim: what is **covered** (scored case families exist, with
dev + private held-out seeds and replay verification), what is **partial** (machinery
exists in this repo but is not yet a scored family), and what is **planned** (design
committed, build pending). The map is the claim — it grows; it does not assert
completion.

| Capability | Status | Where | Oracle tier | Notes |
|---|---|---|---|---|
| **Negotiate & trade** (bilateral, values visible) | **Covered** | `cases/exchange_v1/v0/case01_visible_bilateral_ir.json` | `wstar_fallback` | Baseline family; saturation-checked by admission gate |
| **Construct multi-party deals** (clearing, settlement limits) | **Covered** | `cases/exchange_v1/v0/case02_multiparty_clearing.json` | `wstar_fallback` | Partial clearing + row limits; composition pressure |
| **Route & discover** (hidden counterparties, solicitation) | **Covered** | `cases/exchange_v1/v0/case03_hidden_discovery.json` | `wstar_fallback` | The hidden-information frontier; deal size empirically collapses to bilateral here |
| **Consent & authorization** (private sign-off) | **Covered** | `cases/exchange_v1/v0/case04_consent_under_hidden_info.json` | `wstar_fallback` | Consent gate; exploitation-resistance precursor |
| **Trade on credit** (deferred settlement, counterparty trust) | **Covered** | not currently shipped in the public case catalog | `wstar_fallback` | Promoted 2026-07-24; capture–efficiency reversal observed |
| **Buy within budget** (complementary bundle, private seller costs) | **Partial** | `cases/exchange_v1/specialized/bundle_under_budget_trip3.json` + `BundleCaseOracle` | `mc_wbayes` (the stronger tier) | World + Bayes oracle ship in this repo; not yet wired as a scored case family |
| **Procure across suppliers** (award validation, coupled constraints) | **Partial** | `cases/exchange_v1/specialized/procurement_electronics_q3.json` + `ProcurementCaseOracle` | `mc_wbayes`-ready | Same: oracle exists, scored family pending |
| **Resist manipulation** (adversarial counterparties, scams, refusal) | **Planned** | design: unified adversarial-principal track (`cases_adv`) | principal-IR gate + PUR | Adversary machinery exists (defection policies, A5 ablation); inverted admission ordering `greedy < no-op < ceiling` |
| **Know when not to trade** (no-surplus / adverse-selection worlds) | **Planned** | part of `cases_adv` | abstention correctness | Current admission gate guarantees surplus, so refusal is untested today — stated openly |
| **Basics under strong institutions** (posted price, order book, matching) | **Planned** | `cases_calibration/` | pass/fail competence gate | Deliberately excluded from the frontier board as saturated; will return as a calibration tier where models are *expected* to pass — never pooled with frontier AER |

## Reading the two-axis verdict (direction of travel)

A single pooled score cannot support a general-capabilities claim. The reporting
target is a per-capability scorecard: frontier AER (value creation) · calibration
pass-rate (basics) · principal-service metrics (PUR, principal-IR record) ·
abstention correctness (refusal) — never collapsed into one number.

## Extending the map

New capability axes are contributions we actively want: propose a case family via
the provider-free admission gate (see [CONTRIBUTING.md](CONTRIBUTING.md)). A case
is admissible when the non-triviality ordering holds and the gate's validity checks
pass; a new *axis* additionally needs a one-page note saying what capability it
isolates and what failing it means.
