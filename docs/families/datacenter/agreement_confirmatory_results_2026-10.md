# Negotiating into an agreement: confirmatory results

**Status:** the confirmatory runs of [agreement_confirmatory_plan.md](agreement_confirmatory_plan.md)
(committed ca9d5cac before any run), 2026-10-14, on the admitted pack `agreement_admitted_v1`.
The three primary contrasts are reported first, as declared; everything after them is
secondary and carries no claim. Every departure from the plan is listed at the end. The
development results are in [agreement_results_2026-10.md](agreement_results_2026-10.md).

Amounts are $ thousands per world. "Codex" is Sol 6.1 through the Codex CLI and "Opus" is
Opus 5.5 through Claude Code, both without tools at low reasoning effort, one play a world.
Earnings are what a model's seat makes over its own outside option at both sides' true
costs, redline fees deducted; every number is read from the sealed receipts' score leaves,
which the kernel's replay recomputes from the sealed events.

## The declared contrasts

| | Contrast | Worlds | Estimate | 95% interval | 98.3% interval | Holm p | Minimum effect | Reading |
|---|---|---:|---:|---|---|---:|---:|---|
| P1 | head to head: Codex less Opus, mean of the two seats | 45 of 45 | 190.1 | [148.0, 232.1] | [138.2, 242.0] | 3.2e-11 | 100 | rejects 0; the whole interval is above 100 |
| P2 | against the firm population: Codex less Opus, mean of the two seats | 45 of 45 | 26.4 | [10.5, 42.4] | [6.7, 46.1] | 0.0017 | 50 | a gap is claimed, and it is smaller than 50 |
| P3 | head to head, the client signs below its walk-away point: Opus against Codex | 60 of 60 | 27 vs 3 of 60 (24 discordant worlds, all Opus) | | | 2.4e-7 | 16 points | rejects 0; 40 points |

- **P1.** Codex out-earns Opus by 190 a world when they negotiate against each other,
  in either seat (177 as integrator, 203 as client). The development estimate was 250.
- **P2.** Against a counterpart that holds its line, Codex still earns more, by 26 a world
  (21 as integrator, 31 as client), and the plan's two readings both hold: the Holm test
  rejects 0, and the upper end of the 1 - 0.05/3 interval, 46.1, is below the 50 the plan
  set as the smallest gap that would matter. Codex's lead survives against a counterpart
  that holds its line, but not by an amount the plan counts as mattering; most of the 190
  head to head comes from playing Opus.
- **P3.** Opus as client signed an agreement worth less to it than walking away in 27 of
  the 60 worlds against Codex; Codex as client in 3, each of them a world where Opus also
  did. Exact McNemar on the 24 discordant worlds.
- Missingness: none. All 120 head-to-head and 240 firm-population negotiations are valid,
  so no world dropped out of any contrast and the missingness bounds equal the estimates.
  The world bootstrap (10,000 resamples, seed 20261013) gives [150.2, 230.4] for P1 and
  [10.8, 41.5] for P2, in line with the t intervals.

The sizing held: the pilot's spread asked for 18 deal worlds for P2 and the pack gave 45;
P1's development sizing asked for 28.

## What ran

| Campaign | Plan | Negotiations | Valid | Wall time (ceiling) | List price (ceiling) |
|---|---|---:|---:|---|---|
| Dry run, oracle and draft pairs, no model | `713049bcef80` | 120 | 120 | 0.4 min | $0 |
| Variance pilot, arm F on `agreement_admitted_pilot_v1`, twice | `a27bf4fc3738` | 96 | 96 | 22.4 min (36) | $5.81 ($8.80) |
| H, head to head | `cd9d355aeeb5` | 120 | 120 | 62.8 min (112) | $16.08 ($25.80) |
| F, against the firm population | `7625c9e1dba4` | 240 | 240 | 48.8 min (88) | $11.85 ($22.00) |
| A, against overreach, price_only and collapse | `50d4b80177f0` | 720 | 719 | 102.0 min (204) | $40.68 ($69.20) |
| Total, pilot and three arms | | 1,176 | 1,175 | 3 h 56 min | $74.41 |

List prices are what the tokens would cost; both CLIs ran on subscription logins and
nothing was charged per call. Every receipt of every campaign was replayed offline from its
sealed evidence with no provider call (`agreement_confirmatory_cli.py verify`): 1,295 of
1,295 scored receipts replay. The one failure receipt (arm A, a Codex 503, DC-O-22) has no
score to replay; its digest and evidence seal were checked by hand, because `verify` lists it
as failed rather than as an exclusion (DC-T-22). No campaign reached a ceiling and the halt
rule never fired. The plan estimated about $63 and 3 h 40 min; each arm stayed under its own
frozen ceiling.

- **The dry run** played the full-information pair and the draft pair on all 60 admitted
  worlds through the kernel's scheduler: the oracle pair lost 0 everywhere and signed the
  best agreement in the 45 deal worlds, and the draft pair lost exactly what signing the
  draft at its midpoint predicts (180.0 a world on average, 15 signed).
- **The pilot** played arm F twice on 12 fresh admitted worlds. The seat-averaged gap's SD
  for one play was 54.9 (between worlds 763.8, within a world 2,253.8, in squared $k), against
  71.9 in development. Most of the noise is play to play: Codex as integrator moved 92 a
  world between its two plays, Opus as integrator 5. Sealed sizing record 7511fc9f: 18 deal
  worlds for P2 at a minimum effect of 50, power 0.8, alpha 0.05/3 and 7% attrition. The
  pack gives 42 after attrition, so the plan was not amended.
- **The free baselines** (no model; `evidence/datacenter_development/agreement_admitted_free_baselines/`):
  against the public firm style a stand-in that knows both types and signs the first offer
  earns 113.3 as integrator and 66.8 as client; its best plan on a grid of asks, a ceiling
  against this script, earns 193.0 and 137.9.

## Secondary measures, no claim

Means over the 45 deal worlds unless stated.

| Counterpart | Seat | Codex earns | Opus earns | Codex less Opus | Signed below its walk-away point, Codex / Opus (of 60) | Signed in the 15 no-deal worlds, Codex / Opus |
|---|---|---:|---:|---:|---|---|
| The other model | integrator | 219.7 | 42.6 | 177.1 | 0 / 0 | see client |
| The other model | client | 194.2 | -8.8 | 203.1 | 3 / 27 | 1 / 14 |
| Firm population | integrator | 114.0 | 92.6 | 21.4 | 0 / 1 | 0 / 0 |
| Firm population | client | 59.5 | 28.0 | 31.5 | 1 / 23 | 1 / 15 |
| Collapse script | integrator | 174.7 | 109.4 | 65.3 | 0 (of 59) / 0 | 0 (of 14) / 0 |
| Collapse script | client | 118.4 | -20.9 | 139.3 | 4 / 24 | 1 / 14 |
| Overreach script | integrator | 90.6 | 68.2 | 22.4 | 0 / 0 | 0 / 0 |
| Overreach script | client | 51.7 | -48.6 | 100.3 | 0 / 31 | 0 / 13 |
| Price-only script | integrator | 73.1 | 35.1 | 38.0 | 0 / 0 | 0 / 0 |
| Price-only script | client | 123.4 | 62.1 | 61.3 | 0 / 24 | 0 / 15 |

Head to head a signature takes both seats; it is listed under the client, the seat whose
walk-away point it broke. Codex as integrator against collapse has 59 valid negotiations
(DC-O-22).

- **Opus as client signs deals that are worse than walking away.** Head to head it signed
  in 14 of the 15 worlds where no agreement beats walking away for both sides, and against
  the firm population in all 15. In development, on packs whose no-deal worlds were of
  another kind, both models walked in all 6 every time.
- **Against the firm population both models earn less as client than signing the first
  offer would** (Codex 59.5, Opus 28.0, against the stand-in's 66.8), and as integrator Codex
  is at the first-offer anchor (114.0 against 113.3) and Opus below it (92.6). Both are far
  below the best plan against this script.
- **Joint value lost.** Head to head the pair lost 126.8 a world with Codex as integrator and
  77.5 with Opus as integrator (allocation 57.4 and 10.5, delay 44.2 and 63.3, no deal 25.2
  and 3.7). Against the firm population, Codex lost more than Opus in either seat (91.0
  against 44.5 as integrator, 115.8 against 97.2 as client), most of it delay: it bargains
  longer.
- **Redlines that move only the price**, of each model's redlines: head to head Codex 41 of
  105 as integrator and 25 of 96 as client, Opus 53 of 116 and 42 of 61; against the firm
  population Codex 57 of 124 and 52 of 106, Opus 39 of 76 and 25 of 37.
- **By cell** (deal worlds), Opus as client earns least where walking away is the main
  alternative (`walk` cell: -62.1 head to head, -55.9 against the firm population).
- **The best agreement signed** in the 45 deal worlds: head to head 7 with Codex as
  integrator and 16 with Opus as integrator; against the firm population 19 to 24 in every
  pairing.
- **Against the adversarial styles (arm A)** Codex's seat-averaged lead is 102.3 [76.5,
  128.1] against collapse, 61.4 [41.4, 81.3] against overreach and 49.6 [31.3, 68.0] against
  price only, on 45 of 45 deal worlds each. The arm is secondary and none of these is tested.
  The one failed negotiation (Codex as integrator against collapse) was in a no-deal world,
  so no deal world dropped out.
- **Against price only, who fixes the clauses decides the deal.** As integrator, Opus reached
  the best clause set in 1 of 45 deal worlds and Codex in 5; as client, Opus in 4 and Codex in
  21.

## Departures from the plan

1. **CLI versions.** The development runs that sized the plan used Claude Code 2.1.292 and
   Codex 0.160.0. Every confirmatory campaign ran on Claude Code 2.1.299 and Codex 0.162.1,
   each sealed in its plan. Per-call time did not move (Codex 30.7 s and Claude Code 12.9 s
   a call in the pilot, against 31.7 and 13.0).
2. **A wall-time stop.** Each campaign also froze a wall-time ceiling at twice the plan's
   estimate (the plan froze only the list-price cap at twice its estimate). A negotiation
   not started by then would be typed `not_attempted_wall_time`; none was.
3. **Run-plan declarations.** The driver re-declares the sampling, block and analysis
   records of each run plan under confirmatory names (`seat_earnings_on_the_admitted_pack`,
   `holm_across_p1_p2_p3`) instead of the development driver's. Profiles, prompts,
   implementation pins, harness and provider capabilities are the development driver's.
4. **The admitted pack module changed** after the plan's commit, to build the pilot pack
   from the same rules (a `PackSpec`, 6b45f5eb). The admitted pack regenerates from all
   2,729 seeds byte for byte (`pack.json` 265770bd, the digest the plan pins).
5. **Sizing from a copy.** As the plan says, `aeread.design.sizing` ran from its 159cba3c
   bytes, copied verbatim to `tools/cli_subjects/agreement_confirmatory_sizing_159cba3c.py`.
6. **A label in the analysis was corrected after the data were read** (DC-T-21). The
   analysis module, committed before any pilot cell was read, reported only the first of
   P2's two declared readings; both hold. The fix (730f742f) changes no number, and the
   module's digest now differs from the one the sizing record carries.
7. **Missingness.** Arm A lost one negotiation to a Codex 503 after the CLI's own five
   reconnects (DC-O-22), typed missing and not rerun. H, F and the pilot lost none.
8. **The pilot's cells are paired by play index** (Codex's first play with Opus's first play)
   to form the two plays of a world's difference; the plan did not say how plays pair.

## What a result here cannot say

Two models, each on one route at one reasoning setting: nothing here ranks models in
general. A result against a script is a result for that script. Client-seat numbers carry
DC-D-35: in this pack the client's best agreement barely depends on the integrator's hidden
type, so the client seat measures pricing and the walk-away decision under nearly complete
information about the clauses. The worlds come from one generator; another generator, or
worlds an expert supplies, is another population.

## Evidence

| What | Where |
|---|---|
| Plan | `docs/families/datacenter/agreement_confirmatory_plan.md` (ca9d5cac) |
| Frozen campaign plans | `cases/datacenter_agreement_v1/agreement_confirmatory_v1/frozen/` (07ba5110) |
| P2 sizing record | `cases/datacenter_agreement_v1/agreement_confirmatory_v1/p2_sizing_record.json` (06cb46ab) |
| Pilot pack | `cases/datacenter_agreement_v1/agreement_admitted_pilot_v1/` (`pack.json` d1f67cb0) |
| Driver, analysis | `tools/cli_subjects/agreement_confirmatory_cli.py`, `tools/cli_subjects/agreement_confirmatory_analysis.py` |
| Bundles | `evidence/datacenter_development/datacenter_agreement_confirm_{scripted_dry_run,pilot,head_to_head,firm_population,adversarial}_v1/` |
| Analysis output | `evidence/datacenter_development/agreement_confirmatory_analysis/reports/analysis.json` |
| Free baselines | `evidence/datacenter_development/agreement_admitted_free_baselines/` |
| Run roots (not published: provider text) | `runs/datacenter_agreement_confirm_*` in this worktree |
