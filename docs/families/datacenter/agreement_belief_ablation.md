# Agreement case: the counterpart's belief update

Does the scripted counterpart's belief update matter? Only where its beliefs move its offers. In this case that is
the integrator script, not the client script. Evidence: `evidence/datacenter_development/agreement_belief_ablation/`
(no model call).

| Counterpart | Moves where the belief had narrowed | Moves a frozen belief changes | Opponent's earnings, updating minus frozen (mean, % of available) | Deals signed, updating vs frozen |
|---|---:|---:|---:|---|
| Client script, vs 7 scripted styles | 0 of 1,175 | 0 | 0.0 | identical |
| Client script, vs told-both-types ceiling | 4 of 158 | 3 | +1.1 | 3 worlds differ |
| Integrator script, vs 7 scripted styles | 458 of 1,278 | 197 (15%) | −3.1 to −12.4 | e.g. 38 vs 50 against an even client |
| Integrator script, vs told-both-types ceiling | 55 of 157 | 14 | −10.6 | 58 vs 64 |
| Recorded v2 arms, client script vs model integrators | 4 of 598 | 1 | not measurable | not measurable |
| Recorded v2 arms, integrator script vs model clients | 109 of 398 | 31 (7.8%) | not measurable | not measurable |

**The client script's belief is inert.** It drops an integrator type only when an integrator offer would have lost that
type money, which almost never happens. Freezing it changes no move against any scripted style, and 1 of 598 moves
against the models. The integrator's own-information reference moves by 0.9% of available surplus.

**The integrator script's belief is not.** A client's offers often rule out risk-charge types, the script then asks for
more, and more deals break down. Freezing it changes 15% of its moves against scripted clients, and 7.8% against the
models' recorded offers. It costs the client 3% to 12% of the available surplus on average, mostly through lost deals:
the script's own earnings fall too in five of the seven styles.

**What this means for the case.** The v2 results say knowing the other side's type is worth under 1% to a seat's best
reply: the case measures little inference. This ablation shows the other direction is live: what a client reveals
through its offers changes what the integrator script asks, and so what the client earns. The update is crude
(elimination, not likelihood) and the earnings effects are against scripts. Whether models' earnings move needs a paid
test: the CF arm's 72 deal worlds against the frozen-belief integrator script, paired by world with v2's CF results.
