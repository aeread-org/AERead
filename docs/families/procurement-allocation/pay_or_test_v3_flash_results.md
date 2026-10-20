# Pay or test v3: the flash models on the declared worlds, results

Read out as [the plan](pay_or_test_v3_flash_plan.md) declares; evidence in `evidence/procurement_allocation/pay_or_test_v3_flash/`.
On the 20 declared worlds, two plays each, each world the mean of its plays:

| | Share of the pay-to-best gap closed | Loss a world | Plays touching a newcomer |
|---|---:|---:|---:|
| Sol 6.1 (Codex), from the confirmatory | 35% [18, 52] | $32.51 | 26 of 40 |
| Opus 5.5 (Claude Code), from the confirmatory | 0% | $51.25 | 0 of 40 |
| Gemini 3.8 Flash | 0% | $51.25 | 0 of 40 |
| GPT-6 Luna | −14% [−20, −8] | $58.10 | 0 of 40 |

Neither flash model touched a newcomer. Gemini played the pay-the-premium rule exactly. Luna also paid the premium, but
lost more than that rule: it made 25 award checks, each spending an action ($2.16 a world), its awards came later, and
one award was at a worse quantity. Failure classes (paper branch, `tools/paper/failure_taxonomy/procurement_pay_or_test_v3.py`):
Luna $55.42 information not acquired, $2.16 interaction cost, $0.52 worse terms; Gemini $49.35 and $1.90.
