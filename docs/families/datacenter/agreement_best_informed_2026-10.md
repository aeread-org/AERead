# The agreement case's best informed policy turn by turn, and what it shows (2026-10-19)

The design's primary measure, loss by turn against a best informed policy
([agreement_case.md](agreement_case.md), "What is measured"), was the piece of Gate 3 still missing from every
Data-center result ([qc.md](qc.md), Gate 3). It is now built:
- module: `src/aeread_families/datacenter_development/agreement_best_informed.py`;
- run: on the v1 admitted pack against the public firm script, the counterpart of the confirmatory's
  firm-population arm;
- evidence: `evidence/datacenter_development/agreement_best_informed_v1/`.

It is a derived analysis computed after the runs. It changes no declared result.

## What was built

- **The policy.** For either seat, it uses what that seat knows: its own costs, the declared odds of the other
  side's types, and the script's rule and style. It never reads the other side's true type.
  - The script is deterministic given its type, so the live types at a turn are exactly those whose script would
    have made every script move so far.
  - The policy is computed by backward induction over the turns and the live types, as the design asks.
- **Its moves.** Walk, sign, or redline to a candidate clause set at a candidate price:
  - the candidate clause sets are the agreement worth most in expectation to every non-empty set of live types,
    and the standing terms;
  - the candidate prices are the seat's break-even moved toward each live type's limit by shares 0.2 to 1.0.
  This class contains `agreement_own_information`'s. Restricted to that module's moves, the search reproduces its
  values exactly.
- **Loss by turn.** A model's turn is charged V(state) − Q(state, move): the policy's expected earnings from that
  turn, less the expected earnings of the move made followed by the policy, over the types still live.
- **The one-step check.** Does setting each clause to its best position judged alone against the draft reach the
  best agreement?
- **Speed.** The original script hashes the whole world in its cost caches: 266 ms a move, 381 s a world for one
  seat (DC-T-23). `FastNegotiator` caches by agreement and type and leaves every rule to the original's code. A test
  holds it to the original's moves, and every plan is replayed against the original script.

## What it shows

| $k a world | Client seat | Integrator seat |
|---|---:|---:|
| Best informed policy at the true types (deal worlds) | 93.9 (125.2) | 138.6 (184.8) |
| The same search told the type | 94.3 | 139.8 |
| Opus 5.5 earned / loss by turn, summed | −80.9 / 175.2 | 68.6 / 68.4 |
| Sol 6.1 earned / loss by turn, summed | 30.5 / 64.4 | 84.7 / 54.3 |
| One-step agreement equals the best, of 60 worlds (seat's information / full) | 15 / 25 | 19 / 25 |

- **The losses are bargaining losses, not inference losses.** Knowing the other side's type is worth $0.4k a world
  to the client and $1.1k to the integrator at the true types (DC-D-37), so the case barely measures inference on
  this pack, in either seat.
- **Where each model loses.**
  - As client, Opus signs the integrator's opening offer at once in 34 of 60 worlds, and those first moves cost it
    $206k each on average. Its first turns lose $139k on average.
  - Sol as client loses most on its second turn ($50k); as integrator, on its third ($76k).
  - Opus as integrator loses most on its second turn ($75k).
- **The case is not arithmetic.** Choosing each clause alone reaches the best agreement in only 15 to 25 of the 60
  worlds, depending on what is known, so clauses interact. The design's condition for running the case holds.
- **The reference can be beaten.** It is the best within its class, not over every agreement and price. Model moves
  beat it in 11 turns: Sol in 8 (6 as integrator, $118k in total; 2 as client, $23k) and Opus in 3 as client ($95k).
  Where it is beaten it is a lower bound (DC-D-38).
- **Consistency.** Every sealed negotiation replays to its recorded surplus. Sol minus Opus on the deal worlds,
  averaged over the two seats, is +26.4, the confirmatory's P2.

## What it leaves open

- Widen the class where models beat it (DC-D-38).
- Admit worlds only where the other side's type is worth a margin to this policy, if the case is to measure
  inference (DC-D-37).
- Compute loss by turn on the v2 confirmatory after it runs, as a separate descriptive analysis: v2 declares no
  contrast on its own-information reference.
