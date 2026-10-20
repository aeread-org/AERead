# The counterpart's belief update: what it changes

**Question** (owner, 2026-10-19). A counterpart that updates beliefs only matters if its beliefs change its offers.
Does the agreement case's scripted negotiator's update change anything?

**Method.** Each v2 deal world (72) is played twice, with the counterpart's belief updated as written (it drops every
type of the other side that would have lost on an offer that side made) and frozen at the declared odds, against each
opponent in turn. Earnings are in percent of the world's available surplus, updating minus frozen. The second check
replays every recorded v2 negotiation against the script. Evidence: `evidence/datacenter_development/agreement_belief_ablation/`.

| Counterpart | Opponents | Worlds where its moves differ | Joint value, updating minus frozen | Recorded v2 moves a frozen belief changes |
|---|---|---:|---:|---:|
| Scripted client (the integrator arms' counterpart) | seven scripted styles | 0 of 72, every style | 0.0% | 1 of 598 |
| | told-both-types stand-ins and the grid best reply | 1 to 3 of 72 | under 1.1% for each side | |
| | the integrator's own-information best reply | | +0.9% to that reply | |
| Scripted integrator (the client arm's counterpart) | seven scripted styles | 13 to 28 of 72 | −4.3% to −23.6% | 31 of 398 |
| | stand-ins and the grid best reply | 0 to 42 of 72 | −5.0% to −16.0%; ceiling −9.5% | |

**Reading.**

- **The scripted client's update is inert.** Against every scripted style its moves are identical either way. Against
  the stand-ins it changes a move in at most 3 of 72 worlds. On the recorded negotiations it changed 1 move in 598. This
  matches the v2 finding that knowing the other side's type is worth under 1% of the available value: there is
  nothing for the client's belief to act on.
- **The scripted integrator's update changes its offers, and costs both sides.** With its belief updated, joint value
  falls in every pairing and more deals fail. Against the even style 34 worlds end without a deal against 22 frozen;
  against the told-both-types ceiling, 14 against 8.
- **Why is a hypothesis, untested:** the elimination rule narrows the integrator onto client types the real client is
  not, so it asks prices the real client will not sign.

**What it means for the redesign.** A counterpart that updates beliefs matters only where its beliefs move its offers,
and here that happens only on the integrator's side, where the update as written destroys value rather than reading the
other side. A redesigned counterpart needs a declared likelihood model, so its posterior is a reading of the history
rather than an elimination rule, and a check like this one before any model plays it.
