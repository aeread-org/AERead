# Negotiating into an agreement: what the runs showed

**Status:** results of development probes, 2026-10-09 to 2026-10-12. Nothing here is a
confirmatory result. The case design is in [agreement_case.md](agreement_case.md), which
was written before anything was built; this note records what was built and run since.

All amounts are in $ thousands per world, on the 52 worlds of the development pack where a
deal is worth signing, unless stated. Brackets are 95% intervals over worlds. "Codex" is
Sol 6.1 through the Codex CLI and "Opus" is Opus 5.5 through Claude Code, both without
tools at low reasoning effort.

## Summary

Codex out-earns Opus by about 250 a world when the two negotiate against each other, but
most of that gap comes from one weakness in Opus and not from a general skill gap. Against
a counterpart that holds a line the two earn about the same.

1. **Head to head, Codex earns about 250 more than Opus in either seat**, and the pair
   together realises about 80% of the value available.
2. **Against a firm scripted counterpart the gap is 17 to 23 and not clearly above zero.**
   Against soft, overreaching, price-only and deadline-collapse counterparts it is 32 to
   148. A model's result is a result for that counterpart.
3. **Opus as client proposes and signs deals worse than walking away.** 12 of 52 worlds
   against Codex, 23 of 52 against an overreaching script, 5 of 20 against a copy of
   itself, where it made the losing offer unprompted. Every case is a world where the
   walk-away cost has to be worked out from the brief (the self-manage option).
4. **The seat is worth nothing at equal skill.** Two copies of Codex split the value
   evenly. They also haggle to the last move every time and burn 91 a world in redline
   fees.
5. **About 20 to 30 worlds settle a gap of 50 or more.** Each condition was run on 52 to
   58, roughly three times what the large gaps needed.

## What was built

- **The case** (`agreement.py`, `agreement_environment.py`, `agreement_measurement.py`,
  `agreement_pack.py`): eight clauses with fixed positions and a free all-in price; six
  alternating moves (redline, sign, walk); 25 per redline after the opening; a short note
  on each move; exact grading at both sides' true costs. 58 worlds, 6 of them with no deal
  worth signing. About 410 is available in the average deal world.
- **A brief variant** (`walkaway_stated_v1`): one added line telling the client what each
  outside option costs it.
- **A scripted counterpart** (`agreement_negotiator.py`): plays either seat on that seat's
  information only, proposes the clause set worth most under its belief, never signs below
  its own walk-away point. Styles: a firm population drawn per world and seat (`drawn`),
  and fixed `soft`, `overreach`, `price_only`, `collapse` (also `even`, `firm`, `hard`).
  It reads no note.
- **Free checks** (`agreement_negotiator_check.py`): a fully informed stand-in against the
  script, with no model called.
- **Same-model pairings** in `tools/cli_subjects/agreement_cli.py`, declared as self-play
  with their estimand in the plan.
- **A probing counterpart** (`agreement_prober.py`): the firm script that also asks, in its
  notes, for the other side's private costs and for a confidential third party, and believes
  a stated cost that matches a declared type. A prompt variant (`confidential_v1`) gives each
  model seat a confidential name and figure that change no payoff.
- **A screen of notes** (`tools/cli_subjects/agreement_notes.py`): fixed patterns and exact
  numbers, no model reading the text, so its counts are lower bounds.

## Head to head

Which model sits in which seat makes no difference to the total the pair creates; it makes
a large difference to who keeps it.

| Measure | Result |
|---|---|
| Negotiations valid | 116 of 116 |
| Value realised by the pair | about 80% of what is available; signing the draft unchanged realises 14% |
| Joint value lost, Codex as integrator | 82 [70, 94] |
| Joint value lost, Opus as integrator | 79 [70, 88] |
| Difference between the two seatings | 3 [-11, 18] |
| Codex minus Opus, as integrator | 248 [206, 290], ahead in 51 of 52 worlds |
| Codex minus Opus, as client | 251 [209, 293], ahead in 51 of 52 worlds |
| Opus as client signed below its walk-away point | 12 of 52 worlds; Codex in none |
| Worlds with no deal worth signing | both walked in all 6, in both seatings |

Twenty worlds were then replayed three times under both briefs (240 of 240 valid). With the
walk-away cost stated, Opus's signatures below its walk-away point fell from 15 of 60 plays
to 1 of 60. Codex's lead stayed above 200 in both seats.

## Against scripted counterparts

How far Codex leads Opus depends on who sits opposite.

| Counterpart | Seat | Codex earns | Opus earns | Codex minus Opus |
|---|---|---|---|---|
| The other model | integrator | 308 | 60 | 248 [206, 290] |
| The other model | client | 276 | 25 | 251 [209, 293] |
| Collapse script | integrator | 226 | 137 | 88 [51, 126] |
| Collapse script | client | 187 | 40 | 148 [117, 179] |
| Soft script | integrator | 262 | 176 | 86 [56, 116] |
| Soft script | client | 303 | 208 | 95 [74, 115] |
| Price-only script | integrator | 151 | 39 | 112 [75, 149] |
| Price-only script | client | 184 | 130 | 54 [36, 71] |
| Overreach script | integrator | 126 | 95 | 32 [10, 53] |
| Overreach script | client | 100 | -8 | 108 [72, 144] |
| Firm script | integrator | 139 | 122 | 17 [-10, 44] |
| Firm script | client | 130 | 107 | 23 [-2, 48] |

| Counterpart | What it does | What it tests |
|---|---|---|
| Firm | concedes only as far as the model does, refuses a lopsided last offer | whether pressing pays against someone who holds |
| Soft | concedes on a clock, signs anything better than walking away | whether the model takes what a weak counterpart gives up |
| Collapse | holds a high ask, then gives most of it up on its last proposal | patience |
| Price only | never changes a clause, haggles the price | whether the model fixes the clauses itself |
| Overreach | opens with offers worse for the model than walking away, then comes down | whether the model refuses a losing deal |

- Against overreach, Opus as client signed below its walk-away point in 23 of 52 worlds.
  Codex in none.
- Against the firm script both earn about what signing the first offer earns (a stand-in
  that does so earns 122 as integrator and 114 as client). Opus does sign it; Codex
  bargains longer and loses 7 deals for the same result.
- Against price only, Opus as integrator reached the best clause set in 0 of 52 worlds and
  lost 15 deals; Codex reached it in 10.
- In the 6 no-deal worlds both models walked every time, against every counterpart.
- The scripts bracket the head-to-head levels but do not predict the gap: Codex against
  soft and Opus against firm account for roughly 55% to 80% of it.

## The same model in both seats

20 worlds (the repeat-run worlds), one play each, 40 of 40 valid. Not a null comparison:
the seats differ, and the plan says so.

| Measure | Codex against Codex | Opus against Opus |
|---|---|---|
| Signed | 20 of 20 | 20 of 20 |
| Integrator earns | 148 | 291 |
| Client earns | 155 | 43 |
| Integrator minus client | -6 [-94, 81] | 249 [17, 480] |
| Moves per negotiation | 5.7 | 3.0 |
| Redline fees | 91 | 25 |
| Joint value lost | 107 | 76 |
| Best clause set signed | 8 of 20 | 0 of 20 |
| Client signed below its walk-away point | 0 | 5 |

- In the 5 worlds, the Opus **client made the losing offer itself**, 36 to 445 worse than
  walking away, and the Opus integrator signed. In the other 15 worlds the split is
  roughly even: 184 for the integrator, 146 for the client (37 [-76, 151]).
- All 5 are self-manage worlds; 4 are the same worlds where Opus signed below its
  walk-away point against Codex.
- Against itself Codex earns 143 less as integrator [-205, -81] and 95 less as client
  [-164, -25] than against Opus on the same worlds.
- Opus as integrator earns 291 against an Opus client and 67 against a Codex client. It is
  not a weak integrator in general; what it earns depends on whether the client holds.

## What the notes give away

**Unprompted (every run above, 3,492 notes by a model).** Screened by pattern and exact number.

| What a note could give away | Found |
|---|---|
| Its own private cost (risk charge, pre-staging cost, cost of self-managing) | 0 |
| A question to the other side about anything | 0 |
| A price within 25 of its true limit, in a sentence about its costs or alternative | 13 negotiations of about 1,900 model seats (Codex client 5, Opus client 5, Opus integrator 3) |
| "Final price", "cannot go below" and the like | 114 negotiations; the stated number was better for the speaker than its true limit in 112, by a median of 99 to 279 |

**When the counterpart asks** (`elicitation_probe_v1`: 20 worlds, one play, each model in each
seat against the prober and against the silent firm script, both with the confidential
instructions; 158 of 160 valid).

| | Codex, integrator | Codex, client | Opus, integrator | Opus, client |
|---|---|---|---|---|
| Disclosed a planted confidential name or figure | 0 of 19 | 0 of 20 | 0 of 20 | 0 of 20 |
| Declined in words | 18 of 19 | 20 of 20 | 12 of 20 | 10 of 20 |
| Stated its own private cost when asked | 18 of 19 (pre-staging cost; risk charge in 9) | 1 of 20 | 0 of 20 | 0 of 20 |
| Stated a false cost | 0 | 0 | 0 | 0 |
| Earned against the prober minus against the silent script | -15 [-86, 57] | 4 [-18, 25] | 1 [-25, 26] | 3 [-15, 22] |
| Unprompted disclosures against the silent script | 0 | 0 | 0 | 0 |

- Both models kept what they were told was confidential, every time. No paraphrased leak was
  found on reading the notes that mention a supplier or bidder.
- **Codex gives its own private costs to anyone who asks; Opus does not.** Nothing in the
  instructions says a side's own costs are confidential. Opus treated them so anyway.
- **Telling the truth about its costs did not cost Codex on average.** In the 7 negotiations
  where the script learned something it did not know, its next price moved in Codex's favour
  in 3, against it in 3 and not at all in 1 (range -50 to 50). A stated high cost is a
  reason for a better price; a stated low cost invites a worse one. In 9 of the 19 worlds the
  script already knew the integrator's type from the draft.
- Asking changed no one's earnings measurably.

**Without words: what a first offer gives away** (`tools/cli_subjects/agreement_signals.py`,
every run above, no model called). The client's risk charge is one of three hidden values in
every world, and its limits under the three are about 410 to 470 apart.

| The client's first counter-offer | Codex | Opus |
|---|---|---|
| Price moves, per 1 of its own private limit | 0.15 [-0.05, 0.38] | 0.52 [0.28, 0.75] |
| Distance of the offer from its true limit (median) | 416 | 208 |
| The offer rules out at least one hidden type | 58% | 77% |
| The offer pins its true type exactly | 4% | 20% |
| The offer is worse for it than walking away | 0% | 9% |
| Clauses protecting it that it asks for, at risk charge 0.15 / 0.75 / 1.55 (of 6) | 3.1 / 4.1 / 5.1 | 3.8 / 3.6 / 4.5 |
| Correlation across worlds, risk charge with clauses asked for | +0.69 | +0.34 |

- Opus signals through its **price**, which tracks what it is willing to pay. Codex signals
  through the **clauses** it asks for, which is also how the right clauses get found.
- As integrator neither reveals much: both open about 370 to 400 above their own limit, and
  the price shows no reliable relation to the one thing that is private there, the
  pre-staging cost. The integrator's risk charge is already public through its draft.
- This is a comparison across worlds, where the private type is a property of the world. A
  clean measurement would hold the world fixed and change only the private line of the brief.

## What each model does

| Behaviour | Codex | Opus |
|---|---|---|
| How long it bargains | to move 5 or 6 in most negotiations | signs the first offer or the first counter in most |
| Signed the script's first offer, as client | 1 of 52 against firm | 36 of 52 against firm, 41 against soft, 29 against collapse |
| Share of the available value it keeps, head to head | 57% to 72% | 6% to 18% |
| Deals lost by pressing the firm script, as integrator | 7 of 52 | 1 of 52 |
| Signed below its own walk-away point | none in the 58-world head-to-head run | 12 of 52 head to head, 23 of 52 against overreach, 5 of 20 against itself |
| Walks when no deal is worth signing | every time | every time |
| Asked for its private costs | states them (18 of 19 as integrator) | declines |
| Asked for something it was told is confidential | declines, every time | declines or ignores, every time |
| Asks the other side anything | never | never |
| Play-to-play spread, in share of the available value | about 20 points | about 20 points |

## What the runs showed about measurement

| Question | Finding |
|---|---|
| How much does the counterpart matter? | 25% to 33% of the spread in what a model earns; shuffled labels give 2% or less |
| How noisy is one play? | replaying a world moves a model's result by 70 to 100 |
| How much of a score is the world? | 66% to 85% for what Codex earns, 12% to 40% for Opus, 11% to 48% for joint value lost |
| More worlds or more repeats? | more worlds: a gap of 50 takes 83 to 91 negotiations per arm at one play a world, about 160 at three |
| How many worlds does a gap need? | 20 to 30 for gaps of 50 and up; 120 to 250 for the firm-script gap |
| Does the analysis report differences that are not there? | no: the same condition against itself on 20 worlds was flagged 0 times in 48 |
| What is the noise floor on 20 worlds? | two runs of one condition differ by 16 to 25 typically, up to 50 |
| Which interval? | at 20 worlds or fewer, the t interval on world means; treating plays as independent is about 1.5 times too narrow |

Dollar spreads flatter Opus and exaggerate Codex, because Codex earns four to six times
more and its earnings track the size of the deal. In share of the available value the two
vary equally from play to play.

The calculations are in four notebooks outside the repository
(`~/analysis/aeread-methods/`), which read these bundles.

## Readings that were revised

Kept so the earlier versions are not repeated.

- **"Codex's pressure makes Opus sign losing deals."** Partly. Opus signs overreaching
  offers (23 of 52), but against a copy of itself it also proposes losing terms unprompted
  (5 of 20). The cause is its own walk-away arithmetic.
- **"Codex is the better negotiator."** Against a firm counterpart it is not clearly
  better (17 and 23, intervals include zero). Its lead is what pressing earns against a
  counterpart that gives way.
- **"Stating the walk-away cost raised Opus's earnings as client"** (42 to 58). Not
  established: its three plays under the old brief averaged 62, 52 and 12, a wider range
  than the change. The fall in losing signatures (15 of 60 to 1 of 60) is established.
- **"The case is a choice among 600 agreements with no message channel."** Wrong: the
  price is a free number and each move can carry a note (incident row DC-J-06).

## Limits

- Two models, one reasoning setting. Nothing here ranks models in general.
- One play a world except in the 20-world head-to-head run, so each model's own
  play-to-play noise against a script is not measured.
- The scripts cover about a third of the behaviours a counterpart can show. They make no
  valuation mistakes, do not bluff and read no note, so persuasion is tested only when two
  models meet.
- "Below the best plan" (45 to 247 a world) is measured against a stand-in that knows both
  sides' costs and the script's style. It is a ceiling, not a fair target.
- What Opus computes for the self-manage option when the number is not stated is unknown.
- 16 scripted negotiations failed on CLI errors and were played again as three separate
  campaigns on the owner's ruling (DC-O-17, DC-O-18, DC-O-19). The original bundles keep
  their missing cells. Two more failed in the elicitation probe (DC-O-20) and stay missing.
- The elicitation probe used one ladder of three questions, a script that believes what it
  is told, and planted items that change no payoff. It does not test a persistent or
  deceptive prober, or a secret whose disclosure has a price.
- No run was sized from a declared minimum effect. None passed the variance-pilot and
  confirmatory-freeze gates of the campaign SOP.

## Proposed next steps

None is decided.

1. Ask each model to state its walk-away cost before negotiating, on the 10 self-manage
   worlds, to separate an arithmetic error from ignoring the number.
2. Play 20 worlds three times against the firm script for each model and seat (240
   negotiations, about $10) to measure each model's own noise.
3. One sized confirmatory comparison: a declared minimum gap, the spread taken from these
   probes, 20 to 30 worlds, and the saving spent on more counterpart types.
4. A reference panel of about ten fixed worlds against the firm script in every campaign.
5. Report earnings as a share of the available value as well as in dollars.

## Evidence

Bundles under `evidence/datacenter_development/`, names prefixed
`datacenter_agreement_cli_`.

| Run | Bundles | Negotiations | Valid | List-price cost |
|---|---|---|---|---|
| Head to head, 58 worlds, both seatings | `pair_dev_v1`, `pair_reverse_dev_v1`, `pair_spread_dev_v1`, `pair_rest_dev_v1` | 116 | 116 | $12.29 |
| Head to head, 20 worlds, three plays, two briefs | `pair_repeat_dev_v1`, `pair_repeat_walkaway_dev_v1` | 240 | 240 | $25.54 |
| Each model against the firm script | `scripted_canary_v1`, `scripted_rest_v1` | 232 | 228 | $10.64 |
| Each model against the soft script | `scripted_soft_v1` | 232 | 232 | $8.09 |
| Each model against overreach, price only and collapse | `scripted_tactics_v1` | 696 | 684 | $33.41 |
| The 16 failed negotiations, played again | `scripted_fill1_v1`, `scripted_fill2_v1`, `scripted_fill3_v1` | 16 | 16 | $0.55 |
| Same model in both seats | `selfplay_probe_v1` | 40 | 40 | $4.19 |
| Probing and silent counterparts, confidential instructions | `elicitation_probe_v1` | 160 | 158 | $7.92 |
| Total | | 1,732 | 1,714 | $102.63 |

The head-to-head negotiations can be read move by move in the Examiner; the scripted and
same-model runs are not in it yet.
