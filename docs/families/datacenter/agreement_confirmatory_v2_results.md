# Negotiating into an agreement: confirmatory v2 results

**Status:** the declared analysis of [agreement_confirmatory_v2_plan.md](agreement_confirmatory_v2_plan.md) (with its
three amendments), run once on 2026-10-19 after all three arms finished; no interim look. Analysis:
[`evidence/datacenter_development/agreement_confirmatory_v2_analysis/`](../../../evidence/datacenter_development/agreement_confirmatory_v2_analysis/).

## Answer

Sol 6.1 through Codex out-earns Opus 5.5 through Claude Code in both model contrasts and beats the `price_only` rule
as integrator, each found by Holm but none shown to reach its minimum effect (head to head comes closest); Opus's
integrator play earns what the rule earns. On the 72 deal
worlds of `agreement_admitted_v2`, earnings in $k above the seat's outside option, Holm across the four:

| | Contrast | Estimate [95%] | Holm p | Reading |
|---|---|---|---:|---|
| P1 | integrator vs the firm client, Codex − Opus (two plays averaged) | +23.1 [5.4, 40.8] | 0.022 | found; not shown to reach 40 |
| P2 | head to head, Codex − Opus, seat-averaged | +128.8 [96.8, 160.8] | 6.1e-11 | found; lower bound 96.8 just short of 100 |
| P3a | Codex as integrator − `price_only`, same world and client | +22.6 [8.1, 37.1] | 0.008 | found; not shown to reach 40 |
| P3b | Opus as integrator − `price_only` | −0.5 [−17.1, 16.1] | 0.95 | not found |

Against the integrator's references (Section 2, published before the freeze): grid ceiling 186.7, grid
own-information best reply 172.3, `price_only` 81.9; Codex 104.5, Opus 81.4. Both references search asks on a grid,
which misses the client script's exact signing threshold, so they are lower bounds on the values they name: 9 of
Codex's 144 integrator plays earn more than the grid ceiling (by up to 30.2) and 1 of Opus's; 16 and 3 earn more than
the grid own-information value (DC-D-40). The shares of the rule-to-reference headroom (Codex 22% of the grid
ceiling's, 25% of the grid own-information's; Opus none) are therefore upper bounds. No primary uses these references:
P3 subtracts the `price_only` rule, which is exact.

**Corrected references** (branch `codex/datacenter-best-informed`, c12539b5,
`evidence/datacenter_development/agreement_best_informed_v2/`): a turn-by-turn best-informed integrator whose moves add
the client script's exact signing price at its last redline earns 196.3 a deal world at the true charge (202.8 in
expectation over the prior) and 199.3 when told the type, against the grid values 172.3 and 186.7. Against these,
Codex captures 19.8% of the `price_only`-to-reference headroom (19.2% against the told-the-type value) and Opus about
none. They are still lower bounds where a play beats them: 2 of 320 integrator plays exceed the told-the-type value. Opus is not playing the rule: 35 of its 144 plays earn exactly
the rule's amount, against Codex's 39, and both spend about half their redlines on the price alone (109 of 211, 175
of 355).

## Where the money goes

| Arm, pairing | Seat earnings (deal worlds) | Joint value lost | of which no deal / delay | Best agreement signed |
|---|---|---:|---|---:|
| IF, Codex integrator vs firm client | 104.5 | 121.6 | 45.9 / 73.9 | 68 of 144 |
| IF, Opus integrator vs firm client | 81.4 | 51.3 | 9.1 / 40.0 | 80 of 144 |
| HH, Codex integrator vs Opus client | 143.9 vs 42.8 | 116.7 | 26.1 / 68.1 | 13 of 72 |
| HH, Opus integrator vs Codex client | 17.5 vs 174.1 | 111.4 | 24.3 / 74.4 | 25 of 72 |
| CF, Codex client vs firm integrator | 51.3 | 158.8 | 53.6 / 92.8 | 24 of 72 |
| CF, Opus client vs firm integrator | 48.9 | 115.9 | 48.3 / 50.6 | 20 of 72 |

Codex earns more by pushing harder and destroys more of the pie doing it: against the firm client it walks away or
delays into a lost $45.9k and $73.9k a world where Opus loses $9.1k and $40.0k. Head to head Codex takes the larger
share in both seats. The client seat (CF, secondary) separates nothing: Codex − Opus +2.5 [−10.0, 15.0], as DC-D-35
predicts for a seat with little to infer.

## Checks the plan declared

- **Coverage:** 640 of 640 negotiations completed and valid (IF 320, HH 160, CF 160); no world missing from any
  contrast, so the missingness bounds equal the estimates. Every receipt replayed offline from its sealed events
  (`verify`: 640 replayed, 0 failed). $55.41 at list price on subscription logins, 3.0 hours.
- **Isolation (amendments 1 and 2):** every freeze probe and every run probe clean: Codex listed its four built-in
  skills and a neutral working directory; Claude Code reported StructuredOutput only, no MCP server, the default
  output style and a context of about 1,290 tokens.
- **Manipulation check of brief v2:** client signings below the walk-away point: 0 of 80 for either model in HH and in
  CF (v1: Opus 27 of 60). As integrator against the firm client Opus signed below its own outside option twice in 160.
- **Degenerate ground (Gate 1):** a model's two plays of a world ended identically in 47 of 80 worlds for Opus and 28
  of 80 for Codex.
- **Fee sensitivity** (secondary, the recorded actions replayed at another redline fee, so it says what the same moves
  would earn, not how the models would play): at $0 and $12.5k Codex earns more in every seat. At $50k a redline the
  order reverses against the firm counterpart, because Codex redlines more (355 integrator redlines against Opus's
  211): integrator 67.9 against Opus's 69.7, client 1.3 against 22.8. Head to head Codex still earns more in both seats
  at $50k (integrator 116.1 against −12.3, client 127.5 against 2.2). The table is in `analysis.json`.

## What this does and does not show

The integrator seat against a fixed, publicly drawn counterpart measures pricing and exploitation of that counterpart,
not inference (the plan's standing limit: the firm script's first reply reveals the client's charge). Within that,
Codex extracts more than the rule and Opus does not; Codex's extra earnings come with more joint loss. Every
Codex-versus-Opus contrast now runs on isolated subjects; v1's did not (CLI-D-01 to CLI-D-03), so v1 and v2 differ in
subject context as well as in brief, seat and pack, and are not pooled.

**See also.** [The counterpart's belief update](agreement_belief_ablation.md) (2026-10-19, no model call). Freezing the
integrator script's belief changes 7.8% of its moves against the models' recorded client offers, and 15% against
scripted clients, where it costs the client 3% to 12% of the available surplus, mostly in lost deals. The client
script's update is inert.

**Related.** [What the counterpart's belief update changes](agreement_belief_ablation.md): the scripted client's update is inert; the scripted integrator's changes its offers and costs both sides (2026-10-19, offline).
