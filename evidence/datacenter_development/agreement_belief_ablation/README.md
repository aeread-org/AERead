# Agreement case: does the scripted counterpart need its belief update?

Development evidence, no claim, no model call. `tools/datacenter/agreement_belief_ablation.py` compares the agreement
case's scripted negotiator with the same negotiator whose belief is frozen at the declared odds. The negotiator's update
drops every type of the other side that would have lost money on an offer that side made. The comparison covers the
v2 confirmatory counterpart (`agreement_admitted_pack.public_style`) on the admitted v2 pack (72 deal worlds of 80),
in both seats.

- `reports/scripted.json`: every world played twice against seven scripted styles, v1's four told-both-types plans,
  the told-both-types ceiling (`best_plan`), and, opposite the client script, the integrator's own-information
  reference. Each seat's earnings are at true costs.
- `reports/recorded.json`: every recorded negotiation of the v2 arms against the script (IF: 320 episodes; CF: 160).
  Each scripted move is rebuilt from the history; all 996 match the record. Each is set beside the move a frozen
  belief would have made.
