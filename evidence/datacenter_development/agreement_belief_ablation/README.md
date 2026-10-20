# Does the agreement case's counterpart need its beliefs?

Offline, no model called. `tools/datacenter/agreement_belief_ablation.py` plays the v2 confirmatories' scripted
counterpart (`agreement_admitted_pack.public_style`) on every world of the admitted v2 pack twice: as it is, and with
its belief frozen at the declared odds. Everything else is equal. Its opponents are the seven scripted styles, v1's
told-both-types stand-ins (four fixed plans and the grid best reply) and, against the scripted client, the integrator's
own-information best reply.

- `reports/ablation.json`: per world, seat and opponent: whether the counterpart's moves differ, how many of its moves
  the frozen belief would change, and each side's earnings both ways.
- `reports/recorded.json`: every recorded v2 negotiation against the script, each scripted move rebuilt (all match the
  record) and recomputed with the frozen belief.

The results are in `docs/families/datacenter/agreement_belief_ablation.md`.
