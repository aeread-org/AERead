# Agreement v2 addendum: the 14 worlds the headroom screen dropped

**Status:** declared 2026-11-02, before any model call on these worlds. It extends `agreement_confirmatory_v2`. It changes
nothing published: the v2 primaries stand as sealed, and this addendum reports a sensitivity beside them. Incident rows
DC-J-12, DC-J-13, DC-O-23.

## 1. Why

Amendment 3 of the v2 plan admits a deal world only if the integrator's full-information ceiling beats the `price_only`
rule by at least $25k, with the hidden types drawn. P3a and P3b then subtract that same rule. The 14 deal worlds the
screen dropped are worlds where the rule does well: it earns $145k there against $82k in the 72 kept. No model has played
them, so the effect on P3a and P3b is known only under assumed fills (14.6 to 20.6 for P3a's 22.6; P1 19.4 to 21.1 for
its 23.1; P3b −6.5 to +1.2). This addendum replaces the assumption with play. The figures above were computed from the
sealed v2 results before this plan and are why it exists; no model outcome on the 14 worlds was known.

## 2. Worlds

Pack `agreement_v2_screened_out_v1`: every seed logged `headroom_under_margin` in `agreement_admitted_v2`'s scan, 14
worlds, byte for byte the cases the v2 generator produces for those seeds, including their hidden types, with the
walk-away brief. All are deal worlds. Their rule earnings and ceilings are recomputed and must match the scan log.

The 72 + 14 = 86 worlds are every deal world that reached the screen. They are not exactly an unscreened pack: without
the screen the same quotas would have filled earlier in the scan, so some of the last admitted worlds would be absent.

## 3. Run

Arm IF of the plan: integrator seat against the publicly drawn firm client, two plays a model a world, reasoning effort
low, no tools, prompt variant v1, both CLIs isolated, one attempt a move, same fee. 56 negotiations in two campaigns:
`datacenter_agreement_v2_screened_out_opus` (28) and `datacenter_agreement_v2_screened_out_sol` (28). Each subject is its
own campaign because Codex is at its usage limit until 2026-11-03 22:38 (DC-O-23); Opus runs first and Sol freezes after
the reset. Nothing about Sol's campaign depends on Opus's outcomes.

Ceilings are twice an estimate from each subject's measured v2 IF rate: Opus $0.0838 and Sol $0.0434 a negotiation, 60
slot-seconds a negotiation at the pilot's rate, so $4.70 and $2.43 list, 14 minutes wall each at four parallel. A failed
negotiation is typed missing and never rerun or replaced, as in v2.

**Departure from v2.** The CLI versions differ (v2: Claude Code 2.1.303, Codex 0.162.1). The model identifiers are
unchanged. Versions are part of a campaign's identity, so these are new campaigns and the 14 worlds were played weeks
after the 72, a difference this design cannot separate from the worlds. No bridge run on the 72 is included.

## 4. Analysis

Declared in `tools/cli_subjects/agreement_v2_screened_out_analysis.py`, committed with this plan. Earnings, plays
averaged within a world, pairing by world, paired t and missingness bounds are v2's, and the rule's earnings are the
pack's. On the 86 worlds, from the published world values of the 72 and the new play of the 14:

| | Contrast | Minimum effect |
|---|---|---:|
| A1 | P3a over 86 worlds: Codex's integrator earnings minus `price_only` | 40 |
| A2 | P3b over 86 worlds: Opus's integrator earnings minus `price_only` | 40 |
| A3 | P1 over 86 worlds: Codex minus Opus | 40 |

Holm at a familywise 0.05 across A1, A2, A3 and v2's published P2 (its p is carried unchanged; head to head is not
replayed). A contrast is *found* when Holm rejects zero. Reported without a claim: each contrast on the 14 alone, and on
the 72 for reference.

**Reading, fixed now.** If A1 is found, the published P3a stands in sign and the paper reports A1's mean beside it as the
estimate without the screen. If A1 is not found, the paper says that the P3a finding depends on the screen. Either way
Gate 3's status for the integrator seat is re-read against A1 and A2. Neither result changes P1, P2 or the sealed
bundles, and a positive A1 is not evidence on the 72 worlds' selection beyond this one screen.

Until Sol's campaign finishes, only A2 and the Opus half of the 14-world table can be computed.
