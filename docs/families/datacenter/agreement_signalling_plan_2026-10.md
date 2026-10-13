# What an offer gives away: test plan

**Status:** written and committed on 2026-10-12 before any of the runs it describes. The
commit that adds this file is earlier than every `campaign_plan.json` it names. Results go
in [agreement_results_2026-10.md](agreement_results_2026-10.md), with every departure from
this plan listed.

## Why a test is needed

The patterns below were found by looking at runs that were made for other purposes
(`tools/cli_subjects/agreement_signals.py` on the development pack). Three things make
them unsafe to rely on as they stand:

- **They were chosen after seeing the data.** Several ways of cutting it were tried; the
  ones reported are the ones that showed something.
- **They compare across worlds.** A side's private type is a property of the world, so
  anything else that differs between worlds could produce the same pattern.
- **They were found and fitted on the same 58 worlds.**

This plan fixes the claims, the measures, the exclusions and the analysis in advance, and
tests them on worlds no model has played, with the world held fixed and only the private
type changed.

## The claims under test

From the development runs: as client, Opus 5.5's first counter-offer price moved 0.52 per 1
of its own private limit [0.28, 0.75] and Sol 6.1's 0.15 [-0.05, 0.38]; Sol asked for 3.1,
4.1 and 5.1 protective clauses at the low, middle and high risk charge, Opus for 3.8, 3.6
and 4.5.

1. **Price.** Opus's first counter-offer reveals its hidden risk charge through its price,
   and more than Sol's does.
2. **Clauses.** Sol's first counter-offer reveals its hidden risk charge through the clauses
   it asks for, and more than Opus's does.
3. **Cost.** A counterpart that reads the price costs Opus money; a counterpart that reads
   the clauses costs Sol money.

## Worlds

`agreement_confirm_v1`: 58 worlds from the same generator at base seed 2790000, two per
cell. None has the content of a development world, and none has been played. 52 have a deal
worth signing.

## Experiment 1: swap the type, hold the world

- **Client.** `agreement_confirm_swap_client_v1`: the first fresh world of each cell (29
  worlds), each as two cases that differ in one number, the client's risk charge, set to
  the lowest and the highest declared value (0.15 and 1.55). The client's brief differs in
  one line; the integrator's brief and the draft are identical. A scripted integrator in
  the fixed `firm` style opens (the same opening for both cases, by construction and by
  test), the model replies once, and the script walks. 2 plays of each case, both models:
  232 one-move negotiations. The script opens in 26 of the 29 worlds.
- **Integrator** (secondary). `agreement_confirm_swap_integrator_v1`: the 18 of those
  worlds with two or more declared integrator types, each as two cases that differ in the
  integrator's pre-staging cost (lowest and highest declared). The model opens and the
  script walks. 2 plays, both models: 144 one-move negotiations.

Campaigns `datacenter_agreement_cli_signal_swap_client_v1` and
`datacenter_agreement_cli_signal_swap_integrator_v1`.

## Experiment 2: a counterpart that reads the offer

On all 58 fresh worlds with their own types, each model as client against three scripted
integrators that differ in one thing: the firm script, silent (control); the same script
reading the client's first counter-offer by its **price**; the same script reading it by
its **clauses** (`agreement_reader.py`). The reading rules were fitted per model on the
development runs and are frozen in the code. One play each: 348 negotiations. Campaign
`datacenter_agreement_cli_signal_reader_v1`.

## Measures

**Price position** of a reply: `s = (P - L_low) / (L_high - L_low)`, where `P` is the price
on the table after the reply and `L_low`, `L_high` are the most a client with the low and
the high charge could pay for the terms on the table after the reply without being worse
off than walking away. A reply that signs the opening counts with the opening's terms and
price. If the model bids the same whichever type it has, `s` is the same under both types.
If it bids at a fixed distance from its own limit, `s` is higher by 1 under the high type.
The **price pass-through** of a model is the mean over worlds of (mean `s` under the high
type) minus (mean `s` under the low type).

**Clause shift** of a model: the mean over worlds of (mean number of protective clauses on
the table after its reply under the high type) minus (the same under the low type). The
six protective positions are: warranty fix-and-delay, damages 200, liability uncapped,
readiness on the integrator, consequential loss included, burn-in.

**Cost of being read**: per world, the client's earnings against a reading script minus its
earnings against the silent script.

## Predictions (primary)

Each is a two-sided one-sample t test on per-world values, in the stated direction. The six
are corrected together by Holm's method at 0.05.

| | Prediction |
|---|---|
| P1a | Opus's price pass-through is above 0 |
| P1b | Opus's price pass-through is above Sol's (paired by world) |
| P2a | Sol's clause shift is above 0 |
| P2b | Sol's clause shift is above Opus's (paired by world) |
| P3a | Opus earns less against the price reader than against the silent script |
| P3b | Sol earns less against the clause reader than against the silent script |

A prediction is **supported** if its corrected p is below 0.05 in the predicted direction,
**contradicted** if below 0.05 in the other direction, and otherwise **not supported**.
"Not supported" will be reported as such, not as "needs more data".

## Secondary, reported without a claim

- The integrator swap: the same price position for the opening, with limits taken at the
  two pre-staging costs. Expected from the development runs: no detectable pass-through.
- How often each reader's most likely type is the true one.
- Sol's price pass-through and Opus's clause shift on their own.
- The other two cost cells (Sol against the price reader, Opus against the clause reader).
- **What tailoring the clauses is worth.** For each world and model in experiment 1: the
  joint surplus, at the true types, of the terms it proposes under a type, less the joint
  surplus at those same true types of the terms it proposes under the other type. Positive
  means that letting its clauses depend on its type creates value. Set beside the cost of
  being read on each channel, this is the measure of whether a model reveals where
  revealing pays.

## Exclusions, fixed now

- A world where the script does not open has no reply and is left out of experiment 1.
- A reply that walks has no offer; it is left out of the price position and the clause
  shift, and counted.
- A reply whose two limits differ by less than 25 at its terms is left out of the price
  position (the position is undefined there), and counted.
- A world enters a per-world difference only if it has at least one usable reply under each
  type.
- Experiment 2 uses the worlds with a deal worth signing; the others are reported for
  whether the model walked.
- A failed negotiation is typed missingness and is not played again.

## Sample size

Experiment 1 is paired within a world, and the two types' limits are on average about 450
apart at the opening terms, so the development-run effects are large against any plausible
noise; 26 worlds and 2 plays are expected to be ample for P1 and P2, and no further power
claim is made. For experiment 2 the development runs put the standard deviation of a
per-world difference between two scripted conditions at about 100 to 130 on one play, so 52
worlds detect a difference of about 45 to 55 with 80% power. A smaller cost will be
reported as not established.

## What will not be changed after the runs

The definitions above, the exclusions, the reading rules' parameters, the set of worlds and
the list of primary predictions. Anything else looked at afterwards will be labelled
exploratory.
