# T1: one call-outcome contract for every model call

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5 and is decided in [issue #316](https://github.com/aeread-org/AERead/issues/316); a ruling is recorded here with its date and source.

**Summary.** Six components decide what happened on a provider call (the clients, the executor's response and failure paths, the harness port, the receipt classifier, the spend reader), and they disagree: a probe of 18 outcome classes across the kernel's five client paths finds 31 divergences, some of which change which cells are measured. Ticket-by-ticket fixes each set a local rule, and the rules do not compose. The direction is one contract: every call recorded once at three levels, filled by one classifier from what each client can actually observe, under fixed precedence and billing rules, and rolled out by version so no frozen identity changes meaning. The theme ruling asks whether this contract governs all call-outcome work; seven issue-level decisions below then fill its open cells.

## 1. Problem and root cause

**Root cause.** No single specification says, for each kind of call outcome, what is recorded, whether it is billed, who writes its terminal, whether it may be retried, and whether it counts as model behaviour or as operational missingness. Each client and executor branch decides for itself.

| Symptom | Where it shows | Evidence |
|---|---|---|
| The same malformed answer is scored on one client, repaired on another, excluded on a third | #267, #135 | design row 1 [run] |
| A usage-less 429/5xx is booked as an exact `$0`, contrary to the 2026-10-21 ruling | #248, #291, #226 finding 7 | design row 3 [run] |
| Usage in an error body is dropped | #250 | design row 4 [run] |
| One call gets two terminals; event and record disagree | #249, #254 | design rows 8, 9 [run] |
| An interrupted call has two record shapes, one of which can vanish | N6, PRV-D-06 | design row 11 [read] |
| The same quota state is a different outcome per CLI subject | N2, RN-T-06 | design row 12 [run] |
| Exclusion reasons follow attempt history, not the cause that ended the cell | receipt `failure_class` | design row 13 [read] |
| Family-owned clients follow none of the kernel's rules | Refund, datacenter, housing, procurement | design row 14 [read] |

Section 1.2 of the design shows why per-ticket fixes have not converged: three rules on missing usage are in force at once.

## 2. Direction

- **Three record levels:** the call (what was observed, the bill, the content), the attempt (what policy did with it), and the cell's terminal cause (what ended the cell). The receipt reads the terminal cause.
- **One classifier, fed only by observable facts.** What a client cannot observe is `unknown`, never assumed. A fixed precedence decides the condition.
- **Billing rules:** a valid provider cost stands; token completeness is recorded separately; no usage is `unknown` unless the call was provably not sent or a charge witness exists; spend says what each cost source contributed.
- **One terminal writer per call**, one interruption shape, cancellations never swallowed.
- **A conformance test** reads the outcome table as data and drives every kernel client, the one-call harness and the real family clients through every observation.
- **Versioned rollout:** new plans carry the contract version in their identity; absent-version records are read as today, with one named exception.

Not recommended: continuing per ticket (rules keep diverging), or applying the contract to frozen plans in place (a sealed contract would gain new behaviour).

## 3. Scope

In scope: clusters G03, G06, G07, G17; #248 (part 1 F2 and parts 2-4), #249, #250, #253/#291, #254, #267, #102 (tool-dispatch intents), #135's open call-typing parts, #311; notes N2, N3, N6; rows RN-T-06, HL-O-08 (typing part), PRV-D-06/07; #226 findings 2, 6, 7.

Tracked here but not a contract row: #130 (cluster G32), an unexplained billed-input divergence that is still an investigation.

Out of scope: which responses stay measured and which may be replaced (retry estimand N1), ceilings, halt and launch gates (T2); pin granularity and replay identity (T3); the erratum for already-published truncated rows, #265, and publication fields (T4); failure taxonomy and attribution vocabulary (#264).

## 4. Already decided

- [owner] #248 part 1 ruling, 2026-10-21: same-attempt re-send of an unknown-progress HTTP failure only with trusted evidence that nothing executed; any other recovery is a declared, bounded treatment; every call and its original failure stay visible.
- [owner] #135: completed, non-truncated malformed output is model behaviour, with no invented repair; billed failed calls keep provider-reported usage and cost.
- [owner] #152: truncated and unparseable output is `length` on every client and never scored.
- [owner] #101 and #102: one terminal per started call, attempt or tool invocation; every tool-dispatch intent gets a disposition.
- [on behalf] #223/#235: `provider_choice_error`, retryable only where a profile names it.
- [merged] #232 (402 is `account_fault`, halt rule), #247 (streamed-path typing), #291 CI repair (optional cache breakdown).
- Kernel landing order: #246 (merged), #291, #292, #293; #248 after its part-1 repairs.

## 5. Theme ruling requested

**Does one versioned call-outcome contract govern every model call, with the tickets above implementing its rows?**

| Option | Rule | Consequence |
|---|---|---|
| **A. Adopt the contract** | The [design](T1_call_outcome_design.md) is the specification. Each ticket implements rows of its table. Behaviour changes ship only under T1-D5's versioning | One meaning per outcome on every client. Changes to measured cells and spend are listed in advance (design section 5) and reach new identities only |
| B. Continue per ticket | Each PR sets its own local rule | Little up-front work; the divergences in section 1 persist and keep reappearing |
| C. Adopt, applied to all runs at once | As A, but frozen plans also change | Honest at once; frozen identities change meaning, contrary to the sealed-contract rule |

Sub-questions:
- (a) May step 1, a conformance test that records today's divergences and changes no behaviour, start before D1-D7 are ruled?
- (b) Do the family-owned clients (Refund `GeminiProviderClient`, datacenter `ParameterCompatibleOpenRouterClient`, housing and procurement wrappers) come under the contract, or stay as declared divergences until each family re-freezes?

**Recommendation:** A; yes to (a); for (b), bring them under the contract when their family next re-freezes, and record them as declared divergences until then.

## 6. Issue-level decisions that follow

All seven are drafted with options in [T1_call_outcome_decisions.md](T1_call_outcome_decisions.md). Reply citing the id.

| Id | Question | Recommendation | Blocks |
|---|---|---|---|
| T1-D1 | What execution witness permits a same-attempt re-send? | None yet; the predicate ships returning false | #248 F2 beyond the inert default |
| T1-D2 | Charge witness, usage-less calls, legacy usage-less failures | Zero only when provably not sent or witnessed; otherwise `unknown`; legacy usage-less failures re-qualified by the reader | spend claims, budget stops, #250 |
| T1-D3 | Is the call record the wire fact, with policy on the attempt? (#254) | Yes | step 2 |
| T1-D4 | Content typing: truncated complete JSON, reasoning-only, refusal and filter, answers without usage | Never scored; `reasoning_only`; `refused`/`filtered`; measured only when the served model is verified | #267, HL-O-08, #226 finding 2 |
| T1-D5 | How do changes reach frozen plans; how are unversioned records read? | Versioned; absent means legacy | every behaviour-changing step |
| T1-D6 | The form of a declared recovery treatment | A dedicated, bounded declaration, for new identities | #248 F2 beyond inert, T2 |
| T1-D7 | Quota typing and CLI precedence | Permanent quota only on an explicit signal; stdout JSON first; spawn failure is not sent | N2, RN-T-06, #286 |

Decider for all seven: Chenyu.

## 7. Delivery

| Step | Content | Depends on |
|---|---|---|
| 0 | Owner's order: #291 with its branch-review fixes, then #248 part 1 (F1, admission, F2 inert under T1-D1) | landing order |
| 1 | Conformance test, no behaviour change | (a) above |
| 2 | Three record levels, single terminal writer, tool-intent dispositions, one interruption shape, cancellation-safe wait | T1-D3, T1-D5 |
| 3 | Content typing and precedence on Arena, Responses, CLI adapters and the one-call harness; Arena rescue removed | T1-D4, T1-D5 |
| 4 | Billing rows, #250, N6, cost source, legacy re-qualification | T1-D2, T1-D5 |
| 5 | Recovery declaration, named attestations if any, CLI refusal typing, family clients | T1-D1, T1-D6, T1-D7 |

Each step is one kernel PR with a non-author approval, run against the merged families. Owner of the work: Zeyu.

## 8. Not verified

- Responses cells were probed with constructed SDK objects, not live responses.
- Family-owned clients were read, not probed; econevals' own failure register was not re-read.
- That replay never re-issues provider calls is verified for the kernel path only.
- Rows 11 and 13 and cancellation during backoff were read, not run.
