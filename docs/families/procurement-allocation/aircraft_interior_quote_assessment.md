# Quoting refurbishment work from photos: can it be an externally verified case?

**Status:** design assessment, 2026-10-28. Nothing is built, declared or run. Source: a call on 2026-10-28 with an
agent-platform partner (machine transcript, not proofread). Each fact about the firm below is the partner's account
and has not been checked against data. The firm is the partner's customer and is not named here.

**Answer: partly.** If the firm's records hold the final cost of each completed job, the case can be built on the
firm's own past jobs. Then one endpoint, cost-estimate error, is scored against what really happened, and the
simulator can be checked against the firm's own estimators before any agent is scored. Whether an agent's *price*
wins more profitable work cannot be verified from the history alone. That needs either price variation in the records
or a live randomized trial. No AERead case is externally verified today: every price, rate and cost in
Procurement, Housing and Data center was set by the authors.

## The setting, as described

The partner's customer is a business-jet interior refurbishment firm that the partner described as
holding nearly all such work in its region. Owners send photos of damaged or worn items (seats, panels, lighting)
and ask for a price. Every aircraft interior is different, so each quote means looking up past jobs and current
material prices by hand. Requests arrive daily. The partner runs a quoting agent for this firm in production, and
offered data, API access to that agent, and free accounts and credits.

## How far it fits this family

The family measures the [value of information before an irreversible commitment](positioning.md). It fits the
family's third question, what evidence authorizes an irreversible act: here the commitment is a binding quote. The information is costly: the estimator can ask for more photos or measurements, or
inspect the aircraft, at the price of time and goodwill. A quote made from the first photos risks underpricing work
whose scope only shows once the panels come off. It does not fit the first question (choosing which of many suppliers
to check): one request is priced, not a field of candidates. It fits the second (when to stop checking) only if no
information action reveals the whole scope; see the design.

The [P0 results](mechanism_p0_results.md) suggest the failure to look for. On worlds screened so that a plan could get
close to the optimum, Opus 5.5 acting directly bought at once in 64% of episodes, and a planning scaffold recovered
about 80% of the loss. Those worlds are about 4% of what the generator produces, and in the unscreened pilot worlds the
scaffold's effect was not distinguishable from zero, so this is a hypothesis to test here, not a prediction. This
setting would test whether that pattern costs real money: does an agent quote straight from the photos when it should have asked a question?

It is the seller's side of procurement, so it is a new case, not a variant of pay or test v3. Pay or test v3 is unchanged.

## Design: worlds are past jobs

| Element | Taken from the firm's records | Simulated |
|---|---|---|
| World | One completed historical job | — |
| What the agent sees first | The original request: photos, text, aircraft type | — |
| Hidden state | The job's real scope and final cost (labour, materials, change orders) | — |
| Information actions | Answers come from the real scope of the job: a requested photo or measurement reveals the items it covers; an inspection reveals more, but not damage that only appeared at teardown (recorded change orders), so no action settles the scope | Fee, delay and customer patience, from records where they exist (question 4), otherwise set by the authors and stated as such |
| Reference data | Past jobs before this one, material price list at that date | — |
| Acceptance of the quote | — | A model of the probability a customer accepts at a given price, fitted to the firm's quotes and outcomes |
| Payoff | Price minus real cost if accepted | Whether it was accepted |

Two baselines run on the same jobs:
- **The firm's estimators:** their real quote, outcome and margin. This is a real human baseline, not a hired panel.
- **The full-information quote:** the price that maximizes expected margin under the acceptance model when the final
  cost is known. Its expected margin bounds the expected margin of any policy in the simulator; it is not a bound on
  any single realized outcome.

## Verification ladder

| Level | What it checks | Data it needs | What it does not establish |
|---|---|---|---|
| 1. Grounded parameters | Scope-surprise rates and the acceptance model come from records, and fees and delays too where recorded; anything set by the authors is listed | Historical requests, quotes, outcomes | That the simulator predicts outcomes |
| 2. Simulator against reality | Score the estimators' own historical quotes inside the simulator. Compare predicted win rate with outcomes on all held-out requests, and predicted margin with realized margin on held-out won jobs, by a rule declared before looking | The same, with jobs split by date | Accuracy for policies unlike the estimators' (e.g. much lower or higher prices) |
| 3. Agent outcome, offline | Cost-estimate error against final cost, on completed jobs. Fully real: the job's cost does not depend on who estimated it | Final cost per completed job | Win and loss: rejected quotes have no final cost, and acceptance at a price nobody quoted is unobserved |
| 4. Agent outcome, live | The agent drafts quotes alongside the estimators (shadow mode). Then, if the firm agrees, a randomized split of requests between agent-priced and estimator-priced quotes | New requests at the firm; consent | — this is the external check of the full endpoint |

Levels 1–3 can run on history. Level 4 is the only full external check, and it is slow. Detecting a 10-point
difference in win rate around 50% needs about 390 requests per arm (two-sided α 0.05, power 0.8). How long that takes
depends on request volume, which is unknown.

## Known threats

- **Selection.** Worlds built from completed jobs are jobs the firm won at its own price. Lost requests have no final
  cost, and they include the jobs where the firm was undercut or overpriced. Report the won-job panel as conditional
  on winning, and fit the acceptance model on all requests.
- **Confounded inspection value.** Estimators chose when to inspect, so the history cannot say what inspecting would
  have revealed on jobs they quoted blind. The answer for those jobs comes from the final scope, which is fine only if
  an inspection would have found everything that later appeared. That assumption must be stated and tested on jobs
  where an inspection was done.
- **Little competition.** With almost no rivals, acceptance may barely depend on price, and an acceptance
  model may not be fittable (question 3). That leaves cost estimation and
  scope risk as the decision. It is still a case, but a narrower one.
- **Images.** The procurement case is text-only. This one needs photos passed to the subject, and an isolation check
  that nothing beyond the request leaks.
- **Data rights.** Evaluation runs privately on the firm's records. Any public release is a synthetic pack fitted to
  them, as discussed on the call.

## Go/no-go: questions for the partner before anything is built

1. How many historical requests exist with photos, the quote sent and the outcome (accepted, declined, no reply)?
   Of the accepted ones, how many have a recorded final cost (labour hours, materials, change orders)?
2. How often, and by how much, did final cost exceed the quote's cost estimate? **If it is rarely and by little,
   there is no information decision to score and the case stops here.** This is the analogue of measured headroom in Gate 1 of the
   [QC standard](../../operations/benchmark_qc.md).
3. Did prices for comparable work vary (across estimators, periods, customers) enough to fit an acceptance model?
4. Are clarifying questions, inspections, their findings, their cost and the time they took recorded per request?
5. How many requests arrive a month? This sets whether level 4 is feasible.
6. Can the records be used privately for evaluation, and can a fitted synthetic version be published?

A rough floor before calling it a case: about 300 requests with outcomes, and about 150 completed jobs with final
cost. The floor should be re-sized from the audit's own variances; it is not a power calculation.

## Next step

A data audit (questions 1–6) on an export of the firm's records, answered with counts before any design work. The
partner asked for a brief listing what the first step needs; the questions above are that list.
