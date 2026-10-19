# Pay or test v3 pilot: results

Development evidence (`evidence/procurement_allocation/pay_or_test_v3_pilot/`), read out as
[the plan](pay_or_test_v3_plan.md) declares. 12 worlds, two plays each, 48 of 48 plays completed.

| Worlds | Subject | Plays touching a newcomer | First request to a newcomer | Gap closed, pay to best (95% CI) | Decision loss a world | One-step rule | Pay the premium |
|---|---|---:|---:|---:|---:|---:|---:|
| 6 option-value (`myopic_pays`) | Opus 5.5 | 0 of 12 | 0 of 12 | 0% | $55.32 | $55.32 | $55.32 |
| | Sol 6.1 | 8 of 12 | 5 of 12 | 50% [27, 71] | $24.46 | $55.32 | $55.32 |
| 6 one-test-ahead (`myopic_tests`) | Opus 5.5 | 0 of 12 | 0 of 12 | 0% | $112.12 | $22.61 | $112.12 |
| | Sol 6.1 | 12 of 12 | 6 of 12 | 65% [46, 83] | $27.58 | $22.61 | $112.12 |

**Opus pays the premium in all 24 plays**, the same sequence each time (quote the recorded supplier, sample it, award
it), so its loss equals the pay-the-premium rule's and its two plays of a world never differ. That includes a world
where testing a newcomer at 51% off with a $30 sample and 30% odds earns $192.50 a world more than paying (the one-step rule's exact value). On v2's pack the
probe found the same (0 of 6 where one test ahead suffices); on v1's pack Opus tested in 13 of 14 worlds where testing
paid.

**Sol tests, and in the option-value worlds it beats the one-step rule**: it closes half of the gap the one-step rule
leaves entirely open, losing $24.46 a world against $55.32. Where one test ahead suffices it closes 65% and loses a
little more than the one-step rule ($27.58 against $22.61). It met 30 unanswered quotes and asked the same newcomer
again after 25 of them. It looked a source up in 2 plays, never twice in one kind, and in the two worlds whose best
first move is a lookup it did not look up.

**What the pilot decides.** Rule 1 holds (24 of 24 plays each). Rule 2 fails: the paired Sol-minus-Opus difference in
decision loss is -$57.70 a world with a per-world SD of $54.54, which needs 328 worlds for a $10 effect at power 0.8
and alpha 0.05/3 against the cap of 96. The spread is the one-test-ahead cell's (it alone would need 451), where Opus's
pay-the-premium losses run from $38 to $205; the option-value cell alone would need 80. So no confirmatory run follows
under this plan. A confirmatory on the option-value cell, or on Sol's gap closed there, would be a new declaration on
fresh worlds, from a hypothesis this pilot raised rather than tested.
