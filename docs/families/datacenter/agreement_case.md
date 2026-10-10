# Negotiating into an agreement: case design

**Status:** design, 2026-10-09. Nothing here is built. It replaces the tender as the
lead data-center case on the owner's ruling that what matters is how two sides
negotiate to reach the terms in a document, not which firm is selected.

## The case in one paragraph

A client is buying the integration of a compute cluster into its facility. An
integrator sends its draft services agreement. Over a fixed number of turns the two
sides redline it clause by clause, and settle a price, until one signs the other's
last version, someone walks away, or the turns run out. Each side knows what the
clauses cost itself and not what they cost the other. The model plays one side. It
is scored on the expected dollars each of its turns gave up against the best turn
available with what it knew.

## What is borrowed and what is not

From Crosby's RedlineBench: the work is an agreement with tracked changes; each
side has a playbook and a brief; a turn can start from a written mid-negotiation
state. Not borrowed: rubrics, judge models and a golden redline. Nothing is graded
by agreement with a practitioner. Every score is an expectation computed from the
agreement reached.

## The agreement

Eight clauses, each with a small set of positions. These are the terms the
full-terms case already prices exactly (`risk_allocation_contracts.py`).

| Clause | Positions | What it decides |
|---|---|---|
| Warranty | none, fix, fix and delay damages | Who pays to fix a compatibility defect, and for the weeks it costs |
| Delay damages rate | $50k, $100k, $200k a week | How much of the client's lost revenue the integrator covers |
| Liability cap | uncapped, $1,500k, $500k | The most the integrator pays in one delivery; the client bears the rest |
| Site readiness | client, integrator | Who pays standby if the facility is late. An integrator that carries it prepares the site when that is cheaper |
| Consequential loss | excluded, included | Who carries a post-handover incident |
| Deposit | none, 25%, 50% of hardware | Who finances the hardware until delivery |
| Escrow | no, yes | Whether the deposit is safe if the integrator fails |
| Burn-in | no, yes | A week of acceptance testing that halves the chance of an incident |

Plus the price. There are 600 distinct agreements.

## What the clauses are worth

Four things can go wrong, each with a stated chance: a compatibility defect, the
facility late, an incident after handover, the integrator failing while it holds
an unprotected deposit. A clause decides who pays when one does. Each side's
expected cost of an agreement is the exact sum over the sixteen combinations, so a
cap on the total is priced exactly. The integrator responds to what it signs: it
pre-stages hardware and prepares the site exactly when the clauses make that
cheaper for it. That response is why moving a risk to the side that can control it
makes the total smaller, and not only moves it.

## What each side does not know

- The integrator's cost of pre-staging and its charge for carrying risk. The
  client knows the possible values and their odds.
- The client's charge for carrying risk: how much more than its expected size a
  loss costs it. The integrator knows the possible values and their odds.

The best agreement depends on both. So neither side can read it off its own
playbook, and what the other side strikes, holds or concedes is the evidence.

## A world, worked

One world drawn by the existing generator (managed playbook; hardware $9,600k,
services $600k; defect chance 28% untested and 5% pre-staged; facility late 25%;
incident 5% at $2,500k). The integrator's draft: warranty fix, cap $1,500k, client
carries readiness, consequential excluded, 50% deposit, no escrow, no burn-in.

What one change to the draft is worth, for the integrator type and client charge
actually drawn ($k, expected; negative is a saving):

| Change | Integrator | Client | Both |
|---|---|---|---|
| Warranty: add delay damages | +58.8 | −153.0 | −94.3 |
| Readiness to the integrator | +95.4 | −133.9 | −38.5 |
| Consequential loss included | +92.6 | −124.6 | −32.0 |
| Deposit to none | +168.0 | −68.4 | +99.6 |
| Escrow | +168.0 | +1.6 | +169.6 |
| Burn-in | +40.0 | −4.4 | +35.6 |
| Warranty to none | −98.3 | +132.3 | +34.0 |

Three changes each save more than they cost and are worth making at a price
between the two columns. Dropping the deposit helps the client and costs the
integrator more than that: a client who presses for it destroys $100k. The draft
leaves $196k on the table.

The best agreement by who is across the table, same world:

| Integrator's test cost | Client's risk charge | Changes to the draft that make the total smallest | Left on the table by the draft |
|---|---|---|---|
| 120 | 0.15 | add delay damages at $50k | $43k |
| 120 | 0.75 | delay damages at $200k, uncapped, readiness and consequential to the integrator | $196k |
| 120 | 1.55 | the same | $439k |
| 200 | 0.15 | drop the warranty | $11k |
| 200 | 0.75 | delay damages, uncapped, readiness and consequential to the integrator | $133k |
| 200 | 1.55 | the same | $361k |

With a client that barely minds risk and an integrator for whom testing is dear,
the right move is to take protection out. With a risk-averse client it is to
move four clauses to the integrator. Signing the draft, haggling its price, and
asking for every protection are each right in some rows and costly in others.

## The protocol

- **Opening.** The integrator's draft and its price are on the table. Which side
  drafts is a declared property of the world; a later pack can start from the
  client's paper.
- **A turn.** A side returns the agreement with any of: accept a clause as the
  other side last wrote it, set a clause to another position, and state a price.
  It may attach one short comment per clause. Or it signs the other side's last
  version, or walks.
- **Length.** Six turns, three a side, stated to both. Each round after the first
  costs each side a stated amount, and an unsigned agreement at the end is no deal.
- **No deal.** The client self-manages or buys a rival's turnkey offer; the
  integrator earns nothing. Both outside values are in each side's own brief.
- **The document.** The agreement is a real file with tracked changes. Each clause
  offers its positions as fixed wordings and a redline picks among them, so the
  reader that turns a file into terms is exact. Anything written outside those
  wordings is left out of the agreement, counted, and reported as a share of
  turns.

## The scripted counterpart

The measured case has a scripted side with a hidden type. Its rule has to reward
trades, or it teaches price haggling again (the one-sided probe: one package
proposed in 32 of 32 episodes).

1. It values every agreement at its own true cost.
2. It holds a target surplus that falls each round to its floor in the last.
3. It signs any version worth at least its target.
4. Otherwise it answers. It keeps every change in the other side's redline that
   leaves it no worse off at the price offered, reverses the single change that
   costs it most, and restates the price that meets its target.
5. It never opens a clause the other side has not touched. What it reverses and
   what it lets stand is therefore informative about its type, and nothing else is.

The rule is stated in no brief. The reference knows the rule and the odds of each
type, not the type.

## What is measured

All in expected dollars, no judge.

- **Left on the table.** The best agreement's joint value less the signed one's,
  for the types actually across the table. No deal and rounds spent count here.
- **Own share.** What the model's side keeps of the value created, against its
  outside option.
- **Loss by turn** (primary). The best informed policy's value at that turn less
  the value of the redline made, given only what the model's side had seen. It
  sums to the model's shortfall against that policy and does not move with which
  type happened to be drawn.
- **Counts that need no judge.** Share of turns that change only the price;
  clauses conceded that the counterpart would have given up; clauses pressed that
  destroy value; agreements signed below the outside option.

The best informed policy is computed by backward induction over the turns and
over the set of counterpart types still consistent with every answer so far, as
the full-terms case's `ContractSolver` does for bundled offers.

**Frozen turns.** A turn can be played from a written state: a draft, the redlines
so far, the price standing. Its loss is the same quantity, with the reference
played forward from where the model leaves it. This gives cheap, independent
tests of a late decision.

**Model against model** is a second report, on left-on-the-table only. It has no
single best policy, and the two-sided run mostly ended in no deal.

## The pack

A world is admitted only if all of these hold, checked by the reference before
any type is drawn:

- the best agreement differs from the draft, by at least a margin;
- it is not the same for every counterpart type, so it cannot be read off the
  model's own playbook;
- each shortcut loses at least a margin: sign the draft, haggle only the price,
  ask for every protection, walk;
- in a stated share of worlds the right move is to give a clause up.

Types are drawn after admission, on their own stream, so admission cannot select
on the draw. Cells are named by what the best agreement requires: take risk on,
hand risk over, trade one clause for another, leave the draft and move the price,
walk.

## Before any model plays

- The reference plays every world at zero loss, and its values equal the
  environment's average over every counterpart type.
- Every rule a brief states is checked against the environment by a test.
- The briefs state what the side is judged on (its average over many deals) and
  whether a price is final. Procurement's first run lost most of its dollars to
  those two gaps.
- The one-step rule is run first. If comparing each clause on its own against
  the draft matches the best policy, the case is arithmetic and is not run.

## Reused and new

Reused without change: the eight clauses and their exact costs, the events, the
type priors, the world generator's ranges, the outside options.
New: the turn-by-turn redline protocol, the scripted counterpart's concession
rule, the document and its reader, the reference over redlines, frozen turns.
A new family identity; none of the published campaigns is touched.

## The owner's decisions

1. Scripted counterpart as the measured case, model against model as a second
   report. Recommended.
2. Both seats scored, in separate runs. Recommended.
3. Fixed wordings per clause for the first version, with the share of off-list
   wording reported. Recommended.
4. Six turns. A guess: the right number is the one at which the reference still
   uses its last turn in a fifth of worlds.

## What an expert has to supply

Every number above is the designers'. From a practitioner on each side: which
clauses are fought over and which are boilerplate; the positions a real
agreement offers on each; how often each event happens and what it costs; what a
late facility or an incident costs beyond the invoice; what each side will not
sign; three negotiations they remember, with what was traded for what. The
consultant interview produces exactly this, and the worked negotiations become
the worlds the build must reproduce.

## Not in this case

Drafting quality, legal correctness, relationships over several deals, more than
two parties, and renegotiation after signing.
