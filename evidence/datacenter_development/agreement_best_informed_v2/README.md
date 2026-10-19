# agreement_best_informed_v2: the best informed policy turn by turn on the v2 confirmatory

A derived analysis computed after the v2 runs. It declares no contrast, and the v2 plan declares none on an
own-information reference. It applies `agreement_best_informed` (the module and its tests are those of
`agreement_best_informed_v1`) to the v2 admitted pack (`agreement_admitted_v2`, 80 worlds, 72 with a deal) and the
two v2 arms against the public firm script:
- `datacenter_agreement_v2_integrator_firm`: 320 plays, two per world and model;
- `datacenter_agreement_v2_client_firm`: 160 plays.

The head-to-head arm has no single best policy. Regenerate with:

    PYTHONPATH=src python -m aeread_families.datacenter_development.agreement_best_informed --pack v2 \
        --out evidence/datacenter_development/agreement_best_informed_v2 --root . --processes 2

- `reports/rows.json`: one row per world and seat (160).
- `reports/summary.json`: the tables below.
- `reports/per_world.csv`: each world's references (plan at the true type, its expectation, the same search told the
  type) and its best and worst play. These replace the grid references of the v2 results note (DC-D-40).

The run asserts three things: every plan replays against the original script, every sealed negotiation replays to its
recorded surplus, and the cached script makes the original's move on sampled states. The deal-world earnings equal
the declared analysis's: integrator Codex 104.5 and Opus 81.4; client 51.3 and 48.9.

| $k a world (deal worlds) | Client seat | Integrator seat |
|---:|---:|---:|
| Best informed policy at the true types | 108.5 (120.6) | 176.7 (196.3) |
| The same search told the type | 108.6 (120.7) | 179.4 (199.3) |
| Opus 5.5 earned / loss by turn, summed | 40.5 / 68.4 | 73.2 / 103.7 |
| Codex (Sol 6.1) earned / loss by turn, summed | 43.7 / 65.0 | 94.0 / 81.2 |
| One-step agreement equals the best, of 80 worlds (seat's information / full) | 17 / 34 | 28 / 34 |
| Plays above "told the type" | 5 of 160 | 2 of 320 |

Against v2's grid references on the deal worlds (own-information 172.3, ceiling 186.7, `price_only` 81.9), this
reference is tighter: 196.3 at the true types and 199.3 told the type. Codex captures about 20% of the
rule-to-reference headroom; Opus captures none. Knowing the other side's type is worth $0.1k (client) and $2.7k
(integrator) a world (DC-D-42).
