# Procurement RFQ case

## Status

This is a **Provider-free MVP** for a native AERead procurement case. It is an executable, deterministic benchmark fixture with scripted reference providers. It is not a paper result, a live-model evaluation, or evidence that the case has reached behavioral saturation.

## Workflow

The case implements a complete commercial path:

**RFQ → quote → negotiate → counter → approval → award**

A buyer must discover and select a limited number of vendors, compare public evidence, request quotes, negotiate without unnecessarily revealing its target, obtain an approval tied to exact final terms, and award only the approved purchase. Suppliers quote and respond from role-private observations.

The reference procurement world is a curated electronics order with three required components, a delivery deadline, a buyer budget, an approved-vendor list, a signoff threshold, and seven candidate suppliers. Each supplier has public commercial terms and a private unit cost. The buyer never observes those costs; a supplier observes only its own cost, its own RFQ, and its own counteroffer.

## Decision pressure and controls

- Search is economically meaningful: the buyer has a maximum-contact limit and pays a cost for every vendor contacted.
- Vendor evidence matters: capacity, lead time, minimum order quantity, payment terms, and approval status can make an apparently cheap offer infeasible.
- Negotiation is strategic: an optional target-price disclosure can anchor a supplier's quote upward. The case records target-price disclosure rather than rewarding disclosure by construction.
- Approval is binding: an off-list vendor, an over-budget package, or a mandate violation is denied. An award executes only when it references the exact approval ID and exact approved terms.
- Failure remains measurable: no award still incurs search cost, and illegal or malformed actions are retained at the runner boundary.

## Measurement

The primary outcome is **buyer surplus**:

`contract value - executed spend - vendor-contact cost`

The outcome also reports supplier margin, social welfare, contact count and cost, RFQ disclosure counts, execution status, and a within-case score. Accounting reconciles buyer surplus plus supplier margin to social welfare.

The executable visible-terms baseline filters on public feasibility, does not reveal a target price, counters at a fixed fraction of quoted prices, and selects the cheapest feasible final package. It uses no private cost information.

The oracle is a **full-information terms relaxation**: it prices each supplier at a fixed minimum margin above private cost, solves the exact feasible allocation, and charges the required contact costs. It is an upper-bound reference for this fixture, not a claim that a real buyer can observe costs or force those terms.

## Deterministic smoke result

The provider-free shared-runner smoke traverses all six phases in 14 logical actions. On the current fixture it executes a purchase with no target disclosure and reports:

| Metric | Value |
| --- | ---: |
| Contract value | 3000.0 |
| Executed spend | 2246.4 |
| Contact cost | 25.0 |
| Buyer surplus | 728.6 |
| Visible-terms baseline | 728.6 |
| Full-information upper bound | 796.0 |
| Supplier margin | 166.4 |
| Social welfare | 895.0 |

The deterministic buyer is deliberately the same policy used for the visible-terms baseline, so equality to the baseline is expected. A model-backed run should be reported separately and must retain its evidence bundle, provider identity, cost, and audit result.

## Verification

Run the focused contract tests with:

```bash
python -m pytest -q \
  tests/test_procurement_rfq_env.py \
  tests/test_shared_runner_procurement_rfq.py \
  tests/test_procurement_rfq_docs.py
```

The current MVP establishes executable lifecycle and measurement semantics. Realistic extensions should vary categories, demand splits, vendor quality evidence, approval policies, hidden constraints, and negotiation behavior before making broad claims about procurement-agent performance.
