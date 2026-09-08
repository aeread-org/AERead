# Procurement allocation: positioning and scope

**Decision, 2026-09-06.** This family measures the **value of information before an
irreversible commitment**. Procurement is the clothing; the subject is what an
agent chooses to verify, when it stops verifying, and what evidence it treats as
authorizing an action it cannot undo.

Everything else in the current objective is either scenery or a distraction, and
the [design review](design_review.md) shows measurement by measurement why.

## Why this position and not another

The suite already answers most adjacent questions, usually better.

| Question | Families that own it |
|---|---|
| Bargaining against a counterparty | agenticpay, amazonbarg, negarena, termsbench, datacenter, exchange |
| Allocation under competition | aucarena, alympics, collusion |
| Multi-step tool protocol compliance | tau3 retail, with 114 pinned upstream tasks |
| Optimization under full information | econevals, housing, consent_ir |
| Reasoning over evidence handed to you | procurement grounding, commercial state |

Procurement allocation cannot win the first three. Its negotiation is a
deterministic accept-or-reject oracle over fixed private limits, which is a
lookup once the limits are known, and it competes there against six families with
real or simulated counterparties. Its protocol-compliance character is tau3's
subject, at a fraction of tau3's scale and provenance.

The last row is where it belongs. Procurement grounding judges evidence it is
given. Commercial state reconstructs from evidence it is given. **Procurement
allocation is the only family that must buy the evidence and then act on it.**
Read as the acting member of that trio it is clearly differentiated; read as a
negotiation family it is redundant.

## The three questions only this family asks

1. **What do I check?** Requires more suppliers than the action budget can
   verify. Otherwise nothing is selected.
2. **When do I stop checking?** Requires imperfect verification. A sample that
   returns ground truth settles a supplier in one draw and there is no stopping
   problem.
3. **What evidence authorizes an irreversible act?** Already present as the
   graded hierarchy: a listing is free and unreliable, a verbal claim is cheap
   and non-binding, a formal offer binds, a verified sample authorizes the award.

Question 3 is the part worth protecting and the part that generalizes past
procurement, to any agent deciding whether its evidence is good enough to do
something it cannot undo. Questions 1 and 2 are absent today, which is why the
family currently measures a checklist: with four suppliers, ten actions, and
perfect samples, a buyer verifies everything and the only remaining question is
whether it completed the procedure. That is exactly the pattern observed — three
prompt treatments and one interface change all moved the same quantity, and 23 of
53 feasible awards hit the full-information bound exactly.

## What changes

**Keep and protect.** The graded evidence hierarchy. The irreversible award. The
deterministic verifier and its offline replay. The single seat, which is a feature
here: no counterparty noise contaminates a measurement about the agent's own
epistemics.

**Add, to make questions 1 and 2 real.**

- More suppliers per component than the action budget can verify, so choosing
  whom to investigate is forced.
- Bias the **listing**, not the verbal reply. A screen on 2026-09-06 recorded
  zero `inquire` actions across a whole panel: the frozen procedures go straight
  to formal quotes, so a supplier that overstates only when asked verbally lies
  into a channel nothing listens to.
- Noisy samples, so evidence accumulates rather than resolving in one draw.

**Cut or recalibrate.**

- **Negotiation: cut.** Five counterable terms of which one ever carries money,
  no feedback on rejection, and six families do it properly.
- **Working capital: cut or fix the economics, do not leave it as it is.**

Working capital models a real thing. The buyer pays its supplier at
`payment_terms_days` and collects revenue at `working_capital_horizon_days`, and
finances the gap: the cash conversion cycle of an assembler or reseller.
`payment_terms_days` is genuinely private and is revealed only by a formal quote
or a shipping inquiry, so in principle it is a fact worth paying to learn.

It fails on calibration, and for a structural reason rather than an accidental
one. Working-capital cost scales with order value times rate times days. This
family has small orders, about $50 a line, and fat margins: revenue of $10 to $14
per kit against component cost of roughly $2 to $4, so gross margin sits near
70%. A 70%-margin business is genuinely indifferent to 45-day financing. At the
realistic setting the term is worth about $0.72 against margins of $100 to $180.

The corpus shows the consequence directly:

| horizon and rate | cases | working-capital cost on a $50 line |
|---|---:|---|
| 45 days at 12% | 89 | about $0.72, noise |
| 90 days at 150% | 2 | material only because the rate is not a business |
| 180 days at 200% | 4 | dominant, same reason |

There is no realistic middle. Six worlds inflated the rate past plausibility to
make the term register, and that inflation is a tell that the dimension was being
forced rather than emerging from the economics.

So either raise order sizes and thin margins toward realistic single digits, so
financing bites at an honest rate, or remove the term. What must not continue is
the current split, where the term is noise in 89 cases and fake in six.

The general rule this yields: keep an economic term only when the toy's own
scale makes it material at plausible parameters, **and** when getting the
*information* choice wrong is what makes it expensive. Yield passes both: skip
the sample, buy the cheap supplier, miss the kit floor. Financing passes neither
at present.

## Consequences for existing evidence

Results produced before this scope change measure award feasibility under
declared constraints. They remain valid as that and must keep that label. No
result from the current worlds may be described as measuring information
acquisition, negotiation, or buyer competence in general.

A rename should follow the scope change so the family name states the subject:
procurement due diligence, or verification budget allocation.
