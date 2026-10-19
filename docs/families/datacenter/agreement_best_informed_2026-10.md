# The agreement case's best informed policy turn by turn, and what it shows (2026-10-19)

The design's primary measure, loss by turn against a best informed policy
([agreement_case.md](agreement_case.md), "What is measured"), was the piece of Gate 3 still missing from every
Data-center result ([qc.md](qc.md), Gate 3). It is now built and run on both confirmatory packs against the public
firm script:
- module: `src/aeread_families/datacenter_development/agreement_best_informed.py`;
- v1: the admitted pack (`agreement_best_informed_v1/`);
- v2: the admitted pack, firm-client and firm-integrator arms (`agreement_best_informed_v2/`).

Both are derived analyses computed after the runs. They change no declared result; v2 declares no contrast on an
own-information reference.

## What was built

- **The policy.** For either seat, it uses what that seat knows: its own costs, the declared odds of the other
  side's types, and the script's rule and style. It never reads the other side's true type.
  - The script is deterministic given its type, so the live types at a turn are exactly those whose script would
    have made every script move so far.
  - The policy is computed by backward induction over the turns and the live types, as the design asks.
- **Its moves.** Walk, sign, or redline to a candidate clause set at a candidate price.
  - Clause sets: the agreement worth most in expectation to every non-empty set of live types, and the standing
    terms.
  - Prices: the seat's break-even moved toward each live type's limit by shares 0.2 to 1.0.
  - At the integrator's last redline, also the highest price at which the client script still signs. It is read from
    the script's rule (sign when the offer is worth at least `least` of the surplus it believes there is) and kept
    only if the script, asked, signs (DC-D-38).
  This class contains `agreement_own_information`'s. Restricted to that module's moves, the search reproduces its
  values exactly.
- **Loss by turn.** A model's turn is charged V(state) − Q(state, move): the policy's expected earnings from that
  turn, less the expected earnings of the move made followed by the policy, over the types still live.
- **The one-step check.** Does setting each clause to its best position judged alone against the draft reach the
  best agreement?
- **Speed.** The original script hashes the whole world in its cost caches: 266 ms a move, 381 s a world for one seat
  (DC-T-23). `FastNegotiator` caches by agreement and type and leaves every rule to the original's code. A test holds
  it to the original's moves, and every plan is replayed against the original script.

## What it shows

$k a world. The deal-world value is in brackets.

| | v1 client | v1 integrator | v2 client | v2 integrator |
|---|---:|---:|---:|---:|
| Best informed policy at the true types | 93.9 (125.2) | 155.1 (206.8) | 108.5 (120.6) | 176.7 (196.3) |
| The same search told the type | 94.3 | 156.8 | 108.6 | 179.4 (199.3) |
| Opus 5.5: earned / loss by turn, summed | −80.9 / 175.2 | 68.6 / 85.7 | 40.5 / 68.4 | 73.2 / 103.7 |
| Sol 6.1: earned / loss by turn, summed | 30.5 / 64.4 | 84.7 / 70.9 | 43.7 / 65.0 | 94.0 / 81.2 |
| One-step agreement equals the best (seat's information / full), of all worlds | 15 / 25 of 60 | 19 / 25 of 60 | 17 / 34 of 80 | 28 / 34 of 80 |
| Plays above "told the type" | 2 of 120 | 0 of 120 | 5 of 160 | 2 of 320 |

- **The losses are bargaining losses, not inference losses.** In every seat and pack, knowing the other side's type is
  worth $0.1k to $2.7k a world at the true types (DC-D-37). v2's headroom screen admitted worlds on room over
  `price_only`, not on the value of the other side's type.
- **Where each model loses.**
  - As integrator, both models lose on their late turns: Opus on its second and third ($78k and $98k a turn in v2),
    Codex on its third ($94k).
  - As client in v1, Opus signed the integrator's opening offer at once in 34 of 60 worlds, and those first moves cost
    it $206k each. v2's client brief, which states the walk-away point, cut its first-turn loss to $42k, and it no
    longer signs below walking away.
- **The case is not arithmetic.** Choosing each clause alone reaches the best agreement in only 15 to 34 of the worlds,
  so the design's condition for running the case holds.
- **The reference is tighter than the grid ones it replaces.** At the integrator's last redline, the grid prices had
  stopped short of the client script's signing threshold, so model moves "beat" the reference: 6 turns in v1 ($118k) and 15
  in v2 ($410k). With the exact threshold, one integrator turn beats it in v1 and two in v2.
  - On v2's deal worlds it gives 196.3 at the true types and 199.3 told the type, against the grid's own-information
    172.3 and grid ceiling 186.7 (DC-D-40). Codex's capture of the rule-to-reference headroom is therefore 20%, not
    the 22% to 25% the grid values gave.
  - Seven client-seat plays still beat it across both packs, where no threshold was added. It remains a lower bound
    there.
- **Consistency.** Every sealed negotiation replays to its recorded surplus. The deal-world earnings equal the declared
  analyses': v1's Sol − Opus is 26.4; v2's integrator earnings are 104.5 and 81.4, and client 51.3 and 48.9.

## What it leaves open

- The client seat's last redline (move 4) has no exact-threshold candidate yet: the integrator script can still sign,
  redline or walk after it, so its signing price needs a search rather than a formula.
- If the case is to measure inference, admit worlds only where the other side's type is worth a margin to this policy
  (DC-D-37).
