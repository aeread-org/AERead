# Pay or test v3: the flash models on the declared worlds, results

Read out as [the plan](pay_or_test_v3_flash_plan.md) declares; evidence in `evidence/procurement_allocation/pay_or_test_v3_flash/`.
On the 20 declared worlds, two plays each, each world the mean of its plays:

| | Share of the pay-to-best gap closed | Loss a world | Plays touching a newcomer |
|---|---:|---:|---:|
| Sol 6.1 (Codex), from the confirmatory | 35% [18, 52] | $32.51 | 26 of 40 |
| Opus 5.5 (Claude Code), from the confirmatory | 0% | $51.25 | 0 of 40 |
| Gemini 3.8 Flash | 0% | $51.25 | 0 of 40 |
| GPT-6 Luna | −14% [−21, −7] | $58.10 | 0 of 40 |

Neither flash model touched a newcomer. Shares are means over worlds with the declared 95% t interval. Gemini played the
pay-the-premium rule exactly, ordering 55 units in all 40 plays. Luna also paid the premium, but ordered 50 units where 55
was best in 15 of its 40 plays, about $18.27 more loss each, which is its whole $6.85 a world beyond paying the premium.
Its 25 plays at 55 units lost exactly the pay-the-premium rule's amount. Award checks do not change the total: Luna made
44, one a play plus 4, and Gemini 40; the failure classes move part of the pay-the-premium loss onto them because each
spends an action.

Failure classes (paper branch, `tools/paper/failure_taxonomy/procurement_pay_or_test_v3.py`): Luna $55.42 information
not acquired, $2.16 interaction cost, $0.52 worse terms; Gemini $49.35 and $1.90. The declared rules file an award's
whole loss under information not acquired when the award came before a worthwhile newcomer test, so $6.33 a world of
Luna's worse-quantity loss sits there; split into its timing and terms parts, its worse terms would be $6.85 (P-T-23).
