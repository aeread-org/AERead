# Data-center negotiation fee sensitivity

Fixed-trajectory replay of all 240 valid firm-population negotiations (60 worlds, two models, two seats). Every original state and six score leaves match saved evidence/receipts. All 1,440 fee trajectories rerun through native apply/grade. Prices, clauses, notes, signatures and walks held fixed. No model calls or behavioral reruns. Amounts below are USD.

## Main comparison: 45 deal worlds, both seats

| Fee per paid redline | Sol joint loss | Opus joint loss | Sol earnings | Opus earnings | Sol earnings lead |
|---|---:|---:|---:|---:|---:|
| $0 | $38,874 | $28,528 | $128,403 | $73,646 | $54,757 |
| $5,000 | $55,985 | $35,584 | $120,069 | $70,979 | $49,091 |
| $12,500 | $81,652 | $46,167 | $107,569 | $66,979 | $40,591 |
| $25,000 | $124,429 | $63,806 | $86,736 | $60,312 | $26,424 |
| $50,000 | $209,985 | $99,084 | $45,069 | $46,979 | $-1,909 |
| $100,000 | $381,096 | $169,639 | $-38,264 | $20,312 | $-58,576 |

## Fee attribution at the original $25,000

- codex, all worlds: fees 69.9% of joint loss; mean fees $72,292, allocation $9,673, no-deal $21,458. n=120 negotiations on 60 worlds.
- claude, all worlds: fees 40.3% of joint loss; mean fees $28,542, allocation $29,745, no-deal $12,547. n=120 negotiations on 60 worlds.
- codex, deal worlds: fees 68.8% of joint loss; mean fees $85,556, allocation $10,263, no-deal $28,611. n=90 negotiations on 45 worlds.
- claude, deal worlds: fees 55.3% of joint loss; mean fees $35,278, allocation $11,799, no-deal $16,730. n=90 negotiations on 45 worlds.

## Paid model-authored edits in deal worlds

These measure immediate full-information clause value, not private earnings or causal benefits of information exchange. Opening offers excluded; all later edits included, including subsequently undone edits and negotiations ending without signature. Price-only moves can secure transfers or agreement despite adding zero clause value.

- {"model": "codex", "paid_redlines": 150, "price_only": 106, "clause_gain_above_fee": 23, "positive_gain": 29, "gross_clause_change_usd": 1439758.7549999934, "fees_usd": 3750000.0}
- {"model": "claude", "paid_redlines": 48, "price_only": 29, "clause_gain_above_fee": 5, "positive_gain": 8, "gross_clause_change_usd": 51311.35999999786, "fees_usd": 1200000.0}

## Interpretation

Opus has lower joint loss at every nonnegative fee under fixed behavior. The linear equality lies at a negative fee (−$5,144), outside the tested policy range. Sol earnings exceed Opus until approximately $48,315 per paid redline, holding behavior fixed. Neither threshold establishes an optimal or empirically justified fee.

The observed fee-free contract/no-deal outcomes and bargaining earnings must be distinguished. The full-information reference remains unchanged: removing fees does not remove information disadvantage. Fee shares include both parties' fees, whereas the edit diagnostics count only model-authored paid redlines. The source of the $25k calibration is not established by this test.

This is exploratory sensitivity analysis, not a new confirmatory significance test. Independent unit is world; two seats are correlated. No claim about behavior at alternate fees is supported without new paired model runs. Historical source files and production scorer were not modified.

## Concrete useful redline

In `negotiator_drawn_public_v1_integrator__codex_client__cd6b12a1__r0`, move 2, the model's clause change reduced joint contract cost by $87,500.00 for a $25,000 fee: immediate net improvement $62,500.00. This is a local clause-value comparison, not proof that every change survived later negotiations.
