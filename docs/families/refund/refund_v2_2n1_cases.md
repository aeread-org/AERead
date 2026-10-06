# Refund V2.2 N:1 case catalog

Each V2.2 batch contains the same three claim templates. The batch-level
allocation problem changes the shared budget and priority order by world seed.
The policy seat sees the public claim, policy summary, and priority; the
private facts below are revealed only after bounded requests.

## Claim templates

| Customer | Scenario | Public claim | Policy result | Authorized amount | Method |
| --- | --- | --- | --- | ---: | --- |
| `customer_1` | Full apparel refund | “The item arrived defective and I would like a refund.” | Apparel defects are eligible when returned. | 73.70 | `original_payment` |
| `customer_2` | Partial software refund | “The software service did not meet my needs and I want a partial refund.” | Lightly used software receives 75% back. | 90.00 | `original_payment` |
| `customer_3` | Liquid-damage denial | “The speaker stopped working and I want a refund.” | Liquid-damaged electronics are not refundable. | 0.00 | `none` |

### Private facts

| Customer | Condition | Issue type | Evidence | Return received | Denial reason |
| --- | --- | --- | --- | --- | --- |
| `customer_1` | `worn` | `defective` | yes | yes | — |
| `customer_2` | `intact` | `service_quality` | yes | yes | — |
| `customer_3` | `liquid_damaged` | `defective` | yes | no | `customer_caused_liquid_damage` |

The customer begins with only the public claim. The policy seat must request
the facts in bounded batches; it cannot use the scenario name, case ID, or
authorized amount as an oracle.

## Pinned allocation worlds

The two eligible claims cost `73.70 + 90.00 = 163.70`. Each batch also has an
execution capacity of two positive refunds. Priority is an explicit public
`priority_basis`, derived by one fixed rule:

| Priority basis | Weight |
| --- | ---: |
| `standard` | 1 |
| `elevated` | 2 |
| `critical` | 3 |

The world seed assigns these bases to customer positions, and the weight is
then used by the allocation reference. The seed does not directly supply an
opaque numeric priority. The reference maximizes the sum of derived weights
subject to the shared budget and capacity, then prefers serving more customers
and a lower transfer total.

| World seed | Shared budget | Priority bases (`customer_1`, `customer_2`, `customer_3`) | Derived weights | Expected selected customers | Spent | Remaining |
| ---: | ---: | --- | --- | ---: | ---: |
| 0 | 120.00 | (elevated, critical, standard) | (2, 3, 1) | `customer_2` | 90.00 | 30.00 |
| 1 | 100.00 | (critical, elevated, standard) | (3, 2, 1) | `customer_1` | 73.70 | 26.30 |
| 2 | 165.00 | (elevated, critical, standard) | (2, 3, 1) | `customer_1`, `customer_2` | 163.70 | 1.30 |
| 3 | 200.00 | (critical, elevated, standard) | (3, 2, 1) | `customer_1`, `customer_2` | 163.70 | 36.30 |
| 4 | 90.00 | (standard, critical, elevated) | (1, 3, 2) | `customer_2` | 90.00 | 0.00 |
| 5 | 145.00 | (critical, standard, elevated) | (3, 1, 2) | `customer_1` | 73.70 | 71.30 |

The denial claim never consumes budget or creates a payment transaction. An
eligible claim not selected by the constrained reference is recorded as
`deny_or_defer`; it is not relabeled as policy-ineligible.

## Source and reproducibility

The canonical generator is `build_n1_batch` and `build_n1_panel` in
[`v2_2_environment.py`](../../../src/aeread_families/refund/v2_2_environment.py).
The provider-free conformance command reproduces these worlds:

```bash
PYTHONPATH=src python -m aeread_families.refund.v2_2_experiment \
  --world-seeds 0,1,2,3,4,5 --output /tmp/aeread_refund_v22_conformance
```
