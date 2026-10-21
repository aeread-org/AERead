# Pay or test v3: a frozen control that tests, results

Read out as [the plan](pay_or_test_v3_control_plan.md) declares (ec078a59, before any play). Evidence:
`evidence/procurement_allocation/pay_or_test_v3_control/`. OpenRouter charged $0.76 in all.

## Answer

The measured-headroom ground of Gate 1 is not met: 2 of the 20 declared worlds meet it, so the Gate 1 row stays
`partial`. The cause is mostly the control. It tests, but it tests badly, and a control below the screened rules makes
almost every world read trivial (incident P-J-09).

| | Result |
|---|---|
| Phase A (12 development worlds, one play each) | GPT-6 Luna at effort high touched a newcomer in 5 of 12 plays; Gemini 3.8 Flash at high in 0 of 12. The rule selects Luna-high |
| Phase B (20 declared worlds, three plays each) | 60 of 60 plays completed and replayed. Luna-high touched a newcomer in 26 of 60 plays and closed −34% of the pay-to-best gap on average |
| Degenerate (equal decision loss at all three seeds) | 3 worlds: `myopic_pays__2`, `__3`, `__5`; the other 17 vary within the world |
| Trivial (a screened rule worth at least the control's best play) | 18 worlds: the kind-blind shortcut in 14, the one-step rule in 4 |
| Meet the ground | 2 worlds: `myopic_pays__19`, `__20` |

## Reading

The screen asks whether a cheap public rule already does as well as the control. Against a control that loses money
when it tests, the answer is yes almost everywhere. That describes the control, not the worlds. Beside it, and not
declared: Sol 6.1's better play of each world beats every screened rule in 11 of 20 worlds (`__1, 3, 8, 9, 10, 12, 14,
15, 17, 19, 20`). So the worlds leave room over the shortcut for a subject that tests well. This run cannot certify it,
because the frozen control does not test well. A second attempt needs a new plan whose control is first shown to beat
the screened rules on development worlds.
