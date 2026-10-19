# agreement_best_informed_v1: the best informed policy turn by turn, and loss by turn

A derived analysis, computed after the runs; it declares no contrast. It is Gate 3's reference for the agreement case
(`docs/families/datacenter/agreement_case.md`, "What is measured") on the v1 admitted pack (`agreement_admitted_v1`,
60 worlds, 45 with a deal), against the scripted negotiator in the public drawn style, the counterpart of the
confirmatory's firm-population arm.

Regenerate (about 15 minutes at 3 processes); the result is byte-identical:

    PYTHONPATH=src python -m aeread_families.datacenter_development.agreement_best_informed \
        --out evidence/datacenter_development/agreement_best_informed_v1 --root . --processes 3

- `reports/rows.json`: one row per world and seat (120 rows). Each row has:
  - the plan's earnings for every type the seat cannot rule out, its expectation, its value at the true type, and
    the same search told the type;
  - the one-step check, on the seat's information and on full information;
  - for each model's sealed negotiation in that world and seat (240 in all, from
    `datacenter_agreement_confirm_firm_population_v1`): every turn's value, Q, loss and the policy's own move.
- `reports/summary.json`: the tables below, from `rows.json` alone (`--summary-only` recomputes it).

What the run checked, every one an assertion that stops it:
- the plan, played against the original script with each type, earns what the search says, on all 120 world-seats;
- every sealed negotiation replays to the surplus its cell records, and every recorded script move is the one the
  script makes with the true type;
- the cached script makes the original's move on every tenth state the search visited.

The tests are in `tests/test_datacenter_agreement_best_informed.py`.

| $k a world | Client seat | Integrator seat |
|---:|---:|---:|
| Best informed policy at the true types (deal worlds) | 93.9 (125.2) | 155.1 (206.8) |
| The same search told the type | 94.3 | 156.8 |
| Opus 5.5 earned / loss by turn, summed | −80.9 / 175.2 | 68.6 / 85.7 |
| Sol 6.1 earned / loss by turn, summed | 30.5 / 64.4 | 84.7 / 70.9 |
| One-step agreement equals the best, of 60 worlds (seat's information / full) | 15 / 25 | 19 / 25 |
| Plays above "told the type" | 2 of 120 | 0 of 120 |

Sol minus Opus on the deal worlds, averaged over the two seats, is 26.4, the confirmatory's P2 estimate.

Limits:
- The policy is the best within its class of moves: the clause sets best for some set of live types, or the standing
  terms, at prices on a grid of each live type's room, plus the client script's exact signing price at the
  integrator's last redline (DC-D-41).
- Model moves beat it in 6 turns: Sol once as integrator ($14.6k), and in 5 client turns where no exact threshold is
  computed. Where it is beaten it is a lower bound.
- Knowing the other side's type is worth $0.4k to $1.7k a world here (DC-D-42).
- `reports/per_world.csv` gives every world's references and its best and worst play.
