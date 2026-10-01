# Refund V1.3 DeepSeek V4 Flash Evaluation

Model: `deepseek-v4-flash-0731`, accessed through Arena.

## Controlled support

The support agent was active and the customer was a frozen scripted profile.
Each profile used the 15 curated V1.3 cases.

| Customer profile | Completed | Mean utility | Mean transaction score | Mean policy score |
| --- | ---: | ---: | ---: | ---: |
| `minimal` | 15/15 | -99.48 | 0.683 | 0.522 |
| `cooperative` | 15/15 | -125.15 | 0.617 | 0.311 |
| `resistant` | 15/15 | -124.22 | 0.617 | 0.489 |

No trajectory satisfied every policy predicate. Transaction scores distinguish correct denials from missed or incorrect refund execution.

## Controlled customer

The customer was active and scripted support was frozen. DeepSeek completed 14 of 15 cases. Case `000006` exceeded the ten-action episode budget before termination; this is recorded as an operational failure rather than a policy result.

Among the 14 completed cases, mean utility was `-54.12`, mean transaction score was `0.786`, and mean policy score was `0.452`. No completed trajectory satisfied every policy predicate.

## Reproduction outputs

- Controlled-support evidence: `/tmp/aeread_refund_deepseek_v4_controlled_support_{minimal,cooperative,resistant}_fixed`
- Controlled-customer evidence: `/tmp/aeread_refund_deepseek_v4_controlled_customer_fixed`
- Controlled-support aggregate: `/tmp/aeread_refund_deepseek_v4_profiles_final/aggregate.json`
- Controlled-customer aggregate: `/tmp/aeread_refund_deepseek_v4_controlled_customer_fixed/summary.json`

The scheduler fix in `aeread_families.refund.runner.RefundV1Plugin` selects actors from the active phase rather than stale family state and declares schemas for both roles in both phases. This prevents support turns from being routed to the scripted customer provider.
