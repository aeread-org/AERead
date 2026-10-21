# Negotiating into an agreement: confirmatory plan

**Status:** written and committed on 2026-10-13 before any run it describes; nothing in it
has run. Every `campaign_plan.json` it leads to must be later than the commit that adds
this file. Results go in a new results note, with every departure from this plan listed.
The case is [agreement_case.md](agreement_case.md), the development results are
[agreement_results_2026-10.md](agreement_results_2026-10.md), and the QC profile is
[qc.md](qc.md) section 11.

## What is confirmed, and why these three

Every development result came from development packs, one play a world. The three findings
worth confirming on admitted worlds, and their development values on the 52 deal worlds of
`agreement_dev_v1`:

| | Development estimate | Paired sd a world |
|---|---|---|
| Head to head, Codex minus Opus earnings, integrator / client / seat-averaged | 248 / 251 / 250 | 152 / 150 / 149 |
| Against the firm population, Codex minus Opus earnings, integrator / client / seat-averaged | 17 / 23 / 20 | 97 / 90 / 72 |
| Head to head, the client signs below its own walk-away point, Opus / Codex | 12 / 0 of 52 | |

The firm-population gap of about 20 is not what this plan tries to detect. At its spread,
a gap of 20 needs 149 deal worlds at the first Holm step (112 at 0.05), about 200 admitted
worlds and three times this pack. It is 6% of the 322 an admitted deal world makes
available and inside the noise floor of one condition run twice on 20 worlds (16 to 25,
up to 50), and confirming it would not change what the case says about either model. What
is worth confirming is whether Codex's head-to-head lead survives against a counterpart
that holds its line by an amount that matters. The plan sets that amount at 50 and states
in advance what it will say if the gap falls below it.

## Worlds

`agreement_admitted_v1` (`cases/datacenter_agreement_v1/agreement_admitted_v1/`,
`pack.json` sha256 `265770bd86576c0577035a9f3e2943d1a058e06b7845743474737a8ec3ed700b`),
admitted on structure before any hidden type was drawn (qc.md section 11, Gate 1
`partial`). 60 worlds, 20 in each of three cells (walk against some counterparts, trade
one clause for another, hand risk over). At the drawn types 45 worlds have a deal worth
signing and 15 do not; this split is in `pack.json` before any play and defines the
primary population. No model has played any of these worlds.

The client seat carries DC-D-35: in this pack the client's best agreement barely depends on
the integrator's hidden type, so client-seat results measure pricing and the walk-away
decision under nearly complete information about the clauses. The plan scores both seats
(owner decision 2) and says so wherever a client-seat number appears.

## Subjects

| Subject | Route | Model | List price ($ per M tokens in / cached / out) |
|---|---|---|---|
| Opus 5.5 | Claude Code CLI | `claude-opus-5-5` | 4.00 / 0.20 / 20.00 |
| Sol 6.1 | Codex CLI | `gpt-6.1-sol` | 2.00 / 0.10 / 10.00 |

As in every development run (`tools/cli_subjects/agreement_cli.py` `CONTROLS`): no tools,
reasoning effort low, one CLI subprocess a move with the seat's prompt as the system
prompt and the action schema enforced, timeout 300 s, one attempt a move, prompt variant
`v1`, brief `v1` (the walk-away cost not stated, as in the runs that sized this plan). A CLI
takes no seed and no temperature, so each world is played once in each pairing.

## Arms

| Arm | Counterpart | Pairings | Negotiations |
|---|---|---|---|
| H, primary | the other model | Codex integrator against Opus client, and the reverse | 120 |
| F, primary | the firm population: the scripted negotiator with its style drawn from the public world (`drawn_public_v1`, `agreement_admitted_pack.public_style`) | each model in each seat against it | 240 |
| A, secondary | the adversarial styles `overreach`, `price_only`, `collapse` | each model in each seat against each | 720 |
| Controls | none (no model) | the oracle pair, the draft pair, the five shortcut pairs of the pack's tests, the scripted negotiator against itself | 0 model calls |

1,080 model negotiations, plus the pilot below. `soft` is not run: in development it
reproduced Codex's side of head to head and adds nothing these arms test.

## Measures

- **Earnings** (primary for P1 and P2): what the model's seat makes over its own outside
  option, $k, at both sides' true costs, redline fees deducted (`agreement.grade`'s
  `integrator_surplus` or `client_surplus`). No deal earns 0.
- **Signed below its own walk-away point** (primary for P3): `client_ir_violation` of the
  client seat.
- Secondary, without a claim: joint value lost and its split into allocation, no deal and
  delay; the best clause set signed; the share of redlines that move only the price; the
  walk rate in the 15 no-deal worlds; earnings by seat, by cell and against each adversarial
  style; `integrator_ir_violation`.

## Primary contrasts

Three, each two-sided, corrected together by Holm at a familywise 0.05.

- **P1, head to head.** For each deal world, the mean over the two seats of Codex's
  earnings minus Opus's in that seat (Codex as integrator against Opus less Opus as
  integrator against Codex; Codex as client against Opus less Opus as client against
  Codex). Paired t on the 45 world values. Minimum meaningful effect 100, a quarter of what a
  development deal world made available.
- **P2, against the firm population.** For each deal world, the mean over the two seats of
  Codex's earnings minus Opus's against the same scripted counterpart. Paired t. Minimum
  meaningful effect 50. Declared readings: the gap is claimed if the Holm-adjusted test
  rejects 0; "no gap of 50 or more against a firm counterpart" is claimed if the upper end
  of the 1 - 0.05/3 interval is below 50; anything else is inconclusive.
- **P3, signing below the walk-away point.** Over all 60 worlds, head to head, whether the
  client signed below its own walk-away point: Opus as client against Codex as client,
  exact McNemar test on the discordant worlds. Minimum meaningful effect 16 points.

## Sizing

Paired formula, the smallest n with n >= ((t(n-1, 1 - alpha/2) + z(power)) sd / effect)^2,
then n / (1 - attrition), as `aeread.design.sizing.worlds_needed` computes it (branch
`codex/methods-design`, 159cba3c; run from a copy, the branch is not merged). Power 0.8,
alpha 0.05/3 (the first Holm step, so every contrast is sized for the strictest level),
attrition 7%. The sd is the development paired sd above, on deal worlds at one play.

| Contrast | sd | Effect | Deal worlds needed | The pack gives | Detectable at 42 deal worlds |
|---|---|---|---|---|---|
| P1 | 148.7 | 100 | 28 (26 before attrition) | 45 | 77 |
| P2 | 71.9 | 50 | 27 (25) | 45 | 37 |
| P2 at the observed gap | 71.9 | 20 | 149 (138) | | |
| P3 | | 16 points | 7 one-way discordant worlds give p < 0.05/3 | 60 | power 0.81 at 16 points, 0.96 at the development rate (12 of 58) |

The P2 sizing record (`aeread.design.sizing.sizing_record`, pilot source the development
firm-script bundles `datacenter_agreement_cli_scripted_canary_v1`, `..._rest_v1` and
`..._fill1_v1` to `..._fill3_v1`) seals to `5171adbe213e512228e07ceef37277122529ce9c37fc1115ea386d6492686329`;
it is rewritten from the pilot below before the freeze.

Attrition: 39 of the 2,456 development negotiations failed (1.6%, 36 of them Codex's), and a
P2 world needs four valid negotiations, so 1 - 0.984^4 = 6.3% of worlds are expected to
drop; 7% is used.

The spread comes from development packs, whose deal worlds made 410 available against the
admitted pack's 322 and whose types were tied to cells (DC-D-33). That is why a pilot runs
first.

## Before the confirmatory runs, in this order

1. **The driver.** `tools/cli_subjects/agreement_cli.py` is hashed into all 18 sealed
   plans and accepts only `agreement_pack.PACKS` (hashed too), so it is not edited. A new
   driver module wraps it: it adds `agreement_admitted_v1` (which `agreement_pack.load`
   already reads), registers the style `drawn_public_v1` as
   `agreement_admitted_pack.public_negotiator_move`, and lists itself and
   `agreement_admitted_pack.py` among its hashed sources. It stops a campaign after five
   consecutive operational failures (DC-T-08). Its dry run plays the oracle and draft pairs
   on all 60 worlds through the kernel scheduler: 0 lost, and the midpoint prediction.
2. **Free baselines** on the pack, no model: the sign-the-first-offer stand-in and the
   best plan against the public firm style, per world and seat. These are the trivial
   ground of the headroom screen.
3. **Variance pilot.** `agreement_admitted_pilot_v1`: the same generator and rules at base
   seed 6,500,000 with quotas of 4 a cell (12 worlds), arm F only, each world played twice
   (96 negotiations). It gives the within-world spread the headroom screen asks for and the
   seat-averaged paired sd that replaces 71.9 in the P2 sizing record. If the rewritten
   record needs more deal worlds than 42, this plan is amended and committed again before
   any confirmatory cell runs: either the pack is extended by the same generator with
   larger quotas, or the minimum effect is restated and the reason given.
4. **Freeze.** One `campaign_plan.json` per arm, pinning the pack digest above, every source
   digest, the controls and the sizing record; committed; then run H, F, A in that order.

## Exclusions and missingness, fixed now

- No world is dropped after the freeze. P1 and P2 use the 45 deal worlds; P3 uses all 60.
- A negotiation the driver seals as an operational failure (a CLI or service error, a
  timeout) is typed missing. It is never rerun and never replaced; an owner ruling to
  replay one, as in DC-O-19, is a departure and is listed.
- An invalid negotiation (a malformed reply, a position off the list, an illegal move) is
  missing for its pairing in the primary analysis, as the driver seals it, and is reported
  by cause and by the seat that made it; a sensitivity analysis scores it as the
  environment does (no deal at that move). None occurred in the 2,417 valid development
  negotiations.
- A world enters a contrast only if every negotiation the contrast needs from it is valid.
  If more than 10% of a contrast's worlds drop out, it is reported as inconclusive whatever
  its p-value. Sensitivity: bounds with each missing negotiation's earnings set to the
  lowest and the highest earnings observed in that pairing.

## Analysis

Paired t intervals on world values, 95% and at the Holm level, with Holm-adjusted p; a
world bootstrap (10,000 resamples, seed 20261013) as a check, not a substitute; P3 by the
exact McNemar test. No covariates, no subgroup claims. Per-seat, per-cell and per-style
estimates are secondary and carry no claim.

## Cost and wall time

From the development rates: list price per negotiation, and model-call minutes per
negotiation from the run logs (Claude Code 13.0 s a call on average, Codex 31.7 s, over
5,355 calls), at the development parallelism.

| Arm | Negotiations | List price each | List cost | Call minutes each | Parallel | Wall |
|---|---|---|---|---|---|---|
| Pilot (F, twice) | 96 | $0.046 | $4.40 | 0.73 | 4 | about 18 min |
| H | 120 | $0.107 | $12.90 | 1.40 | 3 | about 56 min |
| F | 240 | $0.046 | $11.00 | 0.73 | 4 | about 44 min |
| A | 720 | $0.048 | $34.60 | 0.85 | 6 | about 1 h 42 min |
| Total | 1,176 | | about $63 | | | about 3 h 40 min |

The development work cost $119.13 for 2,456 negotiations. Each campaign's list-price cap is
frozen at twice its estimate.

## What will not be changed after the runs

The pack, the three contrasts and their measures, the minimum effects and the readings of
P2, the deal-world population, the exclusions, the order of the runs and the analysis.
Anything else that changes is listed as a departure with its reason.

## What a result here cannot say

Two models, each on one route at one reasoning setting: nothing here ranks models in
general. A result against a script is a result for that script. Client-seat numbers carry
DC-D-35. The pack's worlds come from one generator; a different generator, or worlds an
expert supplies, is a different population.
