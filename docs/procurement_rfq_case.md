# Procurement RFQ case

## Status

The original **Provider-free MVP** is now supplemented by a versioned coupled-world generator, native Gemini support, and shared-runner typed receipts, replay, batching, and paired analysis. It is not a paper result or evidence that the case has reached behavioral saturation. One earlier Gemini smoke verified the integration; a provider-free panel rehearsal is not a live-model evaluation.

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

The oracle is a **full-information terms relaxation**: it prices each supplier at a fixed minimum margin above private cost and maximizes net buyer surplus over feasible vendor subsets and integer allocations, jointly accounting for contact charges and the contact limit. It retains no trade as a zero-valued option. It is an upper-bound reference for the controlled supplier policy, not a claim that a real buyer can observe costs or force those terms. Legal realized surplus can be negative after unsuccessful search.

The verifier family is `objective_reference`, evaluation class `deterministic`, reference kind `objective_upper_bound`. The six-phase environment enforces contracts and approval; the measurement layer separately reconciles economics and references. Completed cells are included only through sealed typed receipts and state-and-score replay.

## Generated panel and run gates

`procurement_rfq_coupled_worlds_v1` varies quantities, prices, deadlines, financial slack, vendor IDs, and directory order. Every generated world retains forced split capacity, a late vendor, an off-list vendor, and an incompatible-MOQ alternative. Feasibility is constructed from world truth; seeds are not filtered by model or baseline outcomes. Categories and counterparty policy remain a narrow synthetic electronics grammar.

`python -m aeread.shared_runner.procurement_experiment --output /path/to/new/output` defaults to an offline 100-world, two-scripted-condition, three-repeat rehearsal. Live `admission` and `sample` modes require explicit distinct Gemini thinking efforts, a fresh `--master-seed`, and a total recorded-spend limit. The inspected default offline worlds cannot enter the live panel. The sample additionally requires six verified native-Google admission cells on disjoint worlds. Admission spend counts toward the total limit. The batch stops after an episode crosses its recorded-cost threshold, so it is not a provider-side hard billing cap; recorded unknown billing stops further execution.

Both conditions use the same worlds and per-world/per-repeat inference seeds. Analysis averages repeats within each world and resamples whole worlds. Interrupted or unreconciled attempts are not silently rerun, operational exclusions are not scored as zero, and incomplete panels are not labeled complete. See [the preflight walkthrough](walkthroughs/procurement_panel_preflight.md) for the current result and remaining approval gate.

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
