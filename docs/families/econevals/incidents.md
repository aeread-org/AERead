# econevals first-light: incident ledger

Every failed attempt at campaign `econevals_glm53_flash_parasail_first_light_v1`,
in one place, so the run can be audited later without reconstructing it from
scratchpad logs that are not in the repository.

Each row is recovered from the sealed attempt root itself
(`runs/econevals/econevals_glm53_flash_parasail_first_light_v1/qualification_attempt_NNN/`),
not from notes. Costs are the sum of every sealed canary probe and case
checkpoint in that root. Attempt roots are never reused: a root that failed
stays sealed as evidence of what failed.

## Attempts

| Attempt | Reached | Failure | Cost (USD) | Cause | Fix |
|---|---|---|---:|---|---|
| 001 | canary rejected | `provider_contract` | 0.00000 | Route seal carried `allow_fallbacks`/`provider_cost_status`; the OpenRouter adapter accepts exactly five metadata fields and rejects anything else before the network. | `b7acb3fc` |
| 002 | canary rejected | `rate_limit` | 0.00000 | Transient 429 on the unscored, zero-cost probe permanently sealed the root, because the canary was write-once. | `07d1f6f1` |
| 003 | case 00 | `SchedulerContractError` | 0.00004 | Agent profile declared `seed: None`; the adapter refuses a diagnostic run whose seed is unstated. **Canary re-probe validated live**: probes 1-3 `rate_limit`, probe 4 admitted. | `8a19f021` |
| 004 | case 00 | `SchedulerContractError` | 0.00004 | GLM returned a generic `submit` instead of `submit_purchase_plan`; the harness treated a first malformed burst as fatal instead of correctable. | `5904bf1a` |
| 005 | case 00 | `SchedulerContractError` | 0.00003 | Response truncated mid-JSON (decode failed at char 910) against a 900-token output budget. | `eb689a4a` |
| 006 | case 00 | `SchedulerContractError` | 0.00004 | Parasail shared-pool 429 with `max_action_attempts: 1` and no retryable conditions, inherited from tau3's profile. | `01bb1a07` |
| 007 | case 00 | `RuntimeError` | 0.00004 | Ran all 100 periods; receipt `invalid_measurement`/`excluded` because GLM submitted `[]` where a mapping is required, in every period. Two defects: the interface never stated the shape, and the campaign aborted on a measurement verdict. | `40b7f08f` |
| 008 | case 01 | `SchedulerContractError` | 0.02551 | Spurious Parasail **404** on an endpoint OpenRouter listed as available, after case 00 scored `ok/included`. Classified `provider_rejected`, deliberately not retryable. | none -- route fault |
| 009 | case 02 | `SchedulerContractError` | 0.02278 | Scheduling case exhausted the harness's corrective rounds; the sealed responses show one round returned an **empty string**, spending a round on silence when `empty_response` is a typed provider condition. | `5b81cab4` |
| 010 | case 00 | `SchedulerContractError` | 0.00004 | Ten attempts against a 429 burst exhausted in ~2 minutes: retry backoff is opt-in through `harness.config`, and with none declared the executor never sleeps. | `93f2f148` |
| 011 | all 6 cases | publish only | 0.09250 | **Execution succeeded**: 6/6 cases `ok/included`, 100 periods each, `exit=0`. Publishing then crashed on `ValidityReport.valid` (the field is `.status`), and the fix could not be applied to this run -- see below. | `d3f0c1` design split |
| 012 | case 00 | `SchedulerContractError` | 0.00003 | Spurious Parasail **404** again, on the first action. Second occurrence after attempt 008. | none -- route fault |
| 013 | case 02 | `SchedulerContractError` | 0.06887 | Sustained 429: ten attempts **with backoff** (~3 minutes of spread) all refused, after two procurement cases scored. | none -- route fault |

Total spent on failed attempts: **0.20989 USD**, of which 0.09250 bought a
complete but unpublishable panel.

These figures were corrected on 2026-09-06 after a question about whether a
429 costs anything. It does not -- a refused call bills nothing, and every
rejected canary probe records `cost_usd 0.0`. But a case killed *after*
running successfully had paid for those periods, and the failure checkpoint
carried no cost field at all, so 0.0635 USD across attempts 008, 009 and 013
was real, sealed in the evidence, and invisible to this ledger: a 44%
understatement. Failure checkpoints now recover the spend from the sealed
evidence (`_sealed_spend`).

## Disposition 2026-09-06: route-availability block

Attempts 012 and 013 failed on the route, not on our code: a spurious 404,
then a sustained 429 that exhausted ten attempts spread over ~3 minutes.
Attempt 011 had already run the identical panel to completion, so the
campaign is not in question; the shared Parasail pool is.

Per the risk-gate V4 precedent this stops here rather than burning further
attempt roots. The identical frozen plan is re-run in a later availability
window. Nothing about the plan, the panel, or the analysis changes -- a
re-run is not a re-tune.

## The freeze defect attempt 011 exposed

`build_campaign_plan` hashed `campaign.py` into the plan's source digests,
and `campaign.py` carries the **publisher** as well as the executor. So a
publisher bug is unfixable for a completed run: publish with the bug and it
crashes, fix the bug and `_verify_plan` rejects the very run the plan
governed. Attempt 011 executed perfectly and cannot be published.

Relaxing the verification rule after seeing the outcome was rejected as the
same move as post-outcome tuning. Instead the freeze now covers **execution
sources only** (`execution_source_sha256`), and the publisher's digest is
recorded in the publication manifest as `publisher_implementation_sha256`,
next to what was executed rather than inside it -- which is where the
datacenter and procurement families already keep it. That re-freezes the
plan, so the panel is re-run rather than retro-published.

## What the failures were, by kind

- **Our contract errors (001, 003, 004, 005, 007-a)** -- five separate ways the
  adapter did not say what the kernel or the provider required. All were
  cheap, because each failed on the first action of the first case.
- **Our operational-policy errors (002, 006, 007-b, 009, 010)** -- the retry,
  backoff, probe and abort policies were inherited from tau3, whose episode
  shape (12 rounds, Arena route) is nothing like this family's (100
  sequential calls per case, shared-pool route). Four of the five were only
  visible against a real route.
- **Route faults (008, 012, and the bursts inside 002/003/010)** -- Parasail's
  shared upstream pool rate-limits in bursts and returned one spurious 404.
  These are not fixable in our code and are recorded, not worked around: a
  404 stays non-retryable so a genuinely misconfigured route cannot hide.

  The 404 has now happened twice (008, 012), so it is a recurring fault
  rather than a one-off. There is a principled middle worth raising rather
  than taking unilaterally: after the admission canary and N successful
  calls on the identical pinned request, a 404 cannot mean "wrong endpoint",
  so a **post-admission** 404 could carry a typed retryable condition
  distinct from a first-call 404. That is the same route-health vs
  route-identity distinction commit `50de3447` drew for preflight.

  **Ruled and implemented 2026-09-06.** The kernel now types a rejection that
  arrives after the same profile's pinned route has already answered as
  `provider_rejected_after_route_proven`, and econevals lists it among its
  retryable conditions. A FIRST-call rejection is untouched and still fails
  fast, because a wrong model id must not retry ten times behind a backoff.

## Two failures that would not have failed loudly

Worth separating from the list above, because a passing run could have
carried them:

1. **Nondeterministic replay divergence (scheduling).** Upstream renders a
   Python `set` into its failure message (`stable_matching_environment.py:22`),
   and set order is not stable across processes, so the tool-replay
   cross-check compared two strings with identical content and disagreed --
   sometimes. Caught by a dry run, fixed at the bridge boundary (`5904bf1a`).
2. **Half-executed periods.** The harness validated tool calls while
   executing them, so a burst rejected partway left tool effects the
   environment never scored. Fixed by validating a period as a unit before
   any call runs (`5904bf1a`).

## Cross-family findings

Two of these are not econevals problems and are logged here only because
this campaign is where they surfaced:

- **`initial_state` call form** (`018b66b4`): the kernel called the hook with
  a keyword in the replay path and positionally in the scheduler. Nine of the
  eleven external adapters name that parameter `cell`, so **no external
  adapter could produce a replayed receipt**. Blocks #91, #92 and #93 equally.
- **Write-once canary** (`07d1f6f1`): already documented in
  `docs/families/procurement-allocation/design_review.md` after it sealed two
  attempt roots there. It sealed two more here (001, 002) before the fix, and
  the fix then saved roots 003 and 010 on live 429 bursts.

## The in-period loop's own attempts (tool_loop_v2)

| Attempt | Reached | Failure | Cost (USD) | Cause | Fix |
|---|---|---|---:|---|---|
| 001 | case 00 | `SchedulerContractError` | 0.0012 | the harness forbade mixing read-only calls with the submit in one step -- **stricter than the environment**, which only requires the submit to be last. GLM gathers and submits together, got bounced, and never converged in 12 rounds | permit multi-step without mandating it |
| 002 | case 00 | cost ceiling | 0.1827 | $0.0614 for 78 periods against v1's $0.0109 for 100; the ceiling was sized from the old shape | ceilings sized from measurement (#130) |
| 003 | case 01 | `submit_tool_must_be_the_final_call` | 0.1093 | GLM returned the submit **twice** in one step; the validator recorded only the LAST occurrence, so the first sat mid-list in the accumulated action and the environment rejected the period | reject a second submit in a step |
| 004 | case 03 | 400, context length | 0.2754 | executor doubles `max_output_tokens` on every `length` retry, uncapped: 2,400 became 1,228,800, larger than the model's context window | stop declaring `length` retryable (#131) |
| 005 | case 00 | killed | 0.0000 | machine memory watchdog | -- |
| 006 | case 01 | killed, then `EvidenceIntegrityError` | 0.2940 | killed mid-case, then resume tried to append to the partial event log | move a killed case's evidence aside; a failed checkpoint still seals the root |
| 007 | case 01 | `response_not_object` | 0.1067 | `output_tokens` 2,400 at exactly the cap with `output_text ""` -- the model spent the whole budget on reasoning, ten empty retries handed the environment a null action | budget covers reasoning **plus** answer: 6,000 |
| 008 | case 00 | killed | 0.0000 | machine memory watchdog, third time | paused; see below |

### The shared cause

All three are the same mistake in different clothes: **the validator did not
reproduce the environment's contract.** Once it was stricter (001), once it
was sized against the wrong shape (002), once it checked a property of the
last element instead of the whole burst (003).

`parse_action` is the specification. A harness-side validator exists only to
reject early, with feedback, in exactly the cases the environment would
reject -- no more and no less. Every divergence in either direction costs a
case: too strict and the model is bounced for something legal, too loose and
the environment rejects a period after the work is done.

### What the loop bought

Attempt 003's case 00 is the measurement that justifies the whole exercise.
Same model, same case, same route:

| | v1 (blind submission) | v2 (in-period loop) |
|---|---|---|
| inclusion | **excluded**, malformed submission | **included** |
| gate leaf | -- | **1.0** |
| objective (workers supported) | -- | **6.07** |
| cost | $0.011 | $0.099 |

Under v1 five of six cases scored `gate = 0.0`, and the published write-up
said those numbers measured the adapter rather than the model. This is the
confirmation: nothing about GLM changed, only whether it could see what it
had looked up before committing.

## Paused 2026-09-07: machine memory, not the campaign

Attempts 005, 006 and 008 were killed by the host's memory watchdog, not by
anything in the run. At the time of the third kill the machine's largest
consumers were desktop applications, not this work:

| process | RSS |
|---|---|
| ChatGPT.app (node) | 3,092 MB |
| Antigravity IDE | 757 MB |
| Safari | 301 MB |
| claude sessions | ~505 MB combined |

A six-case econevals panel runs ~1 hour and holds a bridge subprocess plus
an evidence store the whole time, so it is a reliable victim whenever the
machine is otherwise loaded. Retrying into that costs an attempt root each
time and proves nothing.

**Resume when the machine is quiet:**

```
ATTEMPT=012 zsh <scratchpad>/run_econ_resilient.sh
```

The resilient driver makes progress monotonic: completed cases keep their
checkpoints and are skipped, and an interrupted case has its partial evidence
moved aside and restarts clean. A kill costs one case, not the panel -- unless
the driver itself is killed, which is what happened to attempts 010 and 011.

**Why it keeps dying.** Not the campaign. The host kills long background
tasks under memory pressure, and the pressure is external: ChatGPT.app alone
held 3.1 GB at the last kill, against ~300 MB per Claude session. A six-case
panel needs an uninterrupted hour. Closing that application, or running the
driver from a terminal outside this session, is the fix.

**Configuration is now complete and correct**, and every defect found along
the way is fixed:

| what | value | why |
|---|---|---|
| in-period tool loop | on | upstream feeds tool results back within a period |
| `max_output_tokens` | 4,000 | modest; truncation handled by retry, not headroom |
| `length` retryable | yes | needed, because a truncated-and-empty response is labelled `length` |
| length-retry growth | capped 8x / half context | #131, fixed in the kernel |
| duplicate submit | rejected | the environment rejects the whole period otherwise |
| killed-case resume | evidence moved aside | partial event logs cannot be appended to |

Nothing about the plan changes; the identity, the panel and the analysis are
frozen. What is already established and does not need re-running:

- The in-period loop is correct and paper-faithful, verified offline (200
  calls over 100 periods, every period seeing tool results before it
  submitted).
- It changes the measurement: `procurement.basic.0` scored **gate 1.0,
  objective 6.07** under the loop in attempts 003, 004 and 007, where the
  blind v1 shape produced an excluded, malformed submission.
- It is also genuinely variable: the same case came back excluded in
  attempt 006. One sample per case, unseeded route.

## Terminal state 2026-09-07: one case the model cannot complete

Attempt 012 ran detached (outside the harness's task table, which is what
had been killing earlier attempts) and scored **three of six cases**:

| case | inclusion | cost |
|---|---|---|
| `procurement.basic.0` | included | $0.0984 |
| `procurement.basic.1` | included | $0.1048 |
| `scheduling.basic.0` | included | $0.0943 |
| `scheduling.basic.1` | **operational failure** | $0.0635 |

`scheduling.basic.1` fails reproducibly, and not for an infrastructure
reason. In that case GLM 5.3 Flash spends its entire output budget on
reasoning and emits nothing: 16 provider calls, **12** with
`finish_reason: "length"` and empty text, every one capped at exactly the
declared 4,000 tokens. The same behaviour appeared at 6,000 and at 12,000 --
the model expands to fill whatever it is given -- and the kernel's length
escalation cannot help, because a harness may lower its budget but never
raise it (#131).

So the pipeline has no recovery, and the panel cannot complete under the
frozen plan, which aborts on the first operational failure.

### The change I am not making

There is an obvious way to finish: reclassify "the model never produced a
parseable action" from an **operational failure** to an **invalid
measurement**. It is even arguably correct -- it is the same distinction
already drawn for an excluded receipt, that a verifier rejecting the model
is not a broken pipeline -- and a model that cannot act has failed the task
rather than broken the harness.

It is not being made here, because it would be a change to the campaign
contract adopted *after* seeing which case it would rescue, by the person
whose run it rescues. That is the shape of post-outcome tuning even when the
reasoning is sound. It belongs to whoever owns the contract, decided on its
merits and applied to every family.

Until then this family reports three scored cases out of six and says why.


## attempt_013 — the effort hint was delivered and ignored

`reasoning_effort` was lowered from `low` to `minimal` on the reasoning that
the model was spending its whole output budget thinking and returning nothing,
and that headroom demonstrably did not help (identical failure at 2,400, 6,000
and 12,000 tokens). The run reached `scheduling.basic.1` and failed there
again, `SchedulerContractError: response_not_object`.

**The hint was delivered.** The sealed `provider_call_started` payload carries
`request.reasoning_effort = "minimal"`. This was checked rather than assumed,
because the alternative explanation -- that the parameter never reached the
wire -- would have pointed at a different defect entirely. The response is
`finish_reason: "length"`, `output_tokens: 4000`, `output_text: ""`, with the
full budget sitting in the `reasoning` field. The model reasoned to the cap
under an explicit instruction not to.

What it was reasoning about is worth recording, because it is not pathological:
the case asks the agent to infer a stable matching from blocking pairs given no
preference lists, and the sealed reasoning is a competent attempt at exactly
that. This is a hard instance, not a confused model. It thinks until the budget
is gone because nothing tells it to stop.

**The isolated probe did not predict this.** All three effort settings answered
a period-0 observation cleanly in 51-177 tokens. The runaway needs the
mid-episode state -- four prior attempts in the observation -- that the probe
did not have. A probe that omits the accumulated history does not test the
failing condition, and this one was reported as inconclusive at the time rather
than as support.

Disposition: hypothesis disproven, `reasoning_effort` alone is not a remedy.
The next mechanism is `reasoning.max_tokens`, which the kernel already wires
from `profile.reasoning.token_budget` and which this family had left `None`.
An effort is a hint; a cap is a cap.

## judgment — attempt_013 changed a frozen control without changing identity

Recorded against myself. `CLAUDE.md` says a changed frozen control requires a
new campaign identity, never a rerun in place. The reasoning condition is a
frozen control, and attempt_013 changed it from `reasoning_low_v1` to
`reasoning_minimal_v1` while keeping `campaign_id =
econevals_glm53_flash_parasail_tool_loop_v2`, which is a rerun in place.

Nothing from v2 was published, so no published bundle mixes the two
conditions, and the attempt roots are separate directories -- the damage is
contained. It is logged anyway, because the rule exists to stop exactly the
reasoning that produced this ("it is only a knob, and the run is not published
yet"), and a contained violation that goes unrecorded is how the uncontained
one becomes defensible.

Corrected forward, not backward: the token-budget run takes a new identity,
`econevals_glm53_flash_parasail_reasoning_capped_v3`. v2's three scored cases
remain v2's and are not pooled with v3's.

## attempt_014 — the cap and the hint cannot both be declared

Declaring `reasoning.effort` and `reasoning.token_budget` together produced an
OpenRouter 400 on the first provider call: *"Only one of "reasoning.effort" and
"reasoning.max_tokens" can be specified"*. The kernel permits the combination
-- its reasoning-block builder documents "an effort, a token budget, or both"
-- so this was accepted at authoring time, sealed into a campaign plan,
admitted, and only rejected when a request was actually sent. Filed as #133.

Cost $0.00: the rejection precedes billing. The expensive part was not the
money but the sealing -- one operational-failure checkpoint closed the run root
and the `_reasoning_capped_v3` identity had to be retired rather than reused,
because an identity must not name two declarations. v4 declares the cap alone.

That is the right shape anyway. The hint is the control that was just shown not
to work; there is nothing to preserve by keeping it alongside the cap.

## attempt_015 — the cap worked, and the bundle it produced could not be published

The reasoning cap did what the effort hint could not. `scheduling.basic.1`, the
case that had failed every prior attempt, ran all 100 periods and reached the
exact optimum: 0 blocking pairs against v* = 0, gate 1.0. Across the case, 100
of 101 provider calls finished `stop` and one finished `length` (and retried),
against 12 of 16 truncating empty under the uncapped condition. All six cases
were included, 100 periods each, $0.4376 of a $1.30 ceiling.

Three defects surfaced in getting that result out, and the panel was re-run
because of the third.

**The publisher reported success without publishing.** `main` checked
`--execute` before `--publish-to`, so a publish-only invocation -- which is
exactly how the driver spells it -- printed a plan digest and returned 0
having written nothing. `publish exit=0` in the run log meant nothing at all.
A completed 6/6 panel sat unpublished with no error anywhere to say so. The
publish branch now precedes the plan-digest branch.

**The driver published to the previous campaign's directory.** The `--publish-to`
path still named `tool_loop_v2` after the identity moved on. Caught only
because the first defect meant nothing was written; had the publisher worked,
v4 results would have landed in v2's bundle.

**The plan restated the reasoning condition instead of deriving it, and the two
statements disagreed.** `campaign.py` carried a literal `reasoning_effort:
"low"` in its route block and in its admission canary, while `live.py` declared
the condition the panel actually ran. So the published plan advertised effort
"low" for a panel that ran with no effort and a 1,500-token cap, and -- the
substantive half -- the canary proved the route under "low" with no cap before
the panel executed under something else. A route admitted under one reasoning
condition does not attest a panel run under another.

The six measurements were real and the receipts are sound. The bundle still
could not stand, because published evidence that names a frozen control it did
not use is not evidence of what it claims. v4 was retired unpublished and the
condition hoisted into a single `REASONING_DECLARATION` that the harness, the
plan and the canary all read. v5 re-runs it, ~$0.44.

Worth naming the pattern, since it has now cost two campaign identities: every
one of these is a control that was written down twice. #133 is the same shape
one level up -- the kernel permits a pair of controls no provider accepts.

## attempt_016 — the cap was ignored too, and the real ceiling was somewhere else

v5 re-ran the same six cases under a single derived reasoning declaration.
`scheduling.basic.1` failed again, `response_not_object`, after passing under
v4 with an identical wire configuration. The fix was not a fix; v4 was a
sample from a distribution.

`reasoning_token_budget = 1500` was present on every call -- checked in the
sealed requests -- and reasoning still ran past 10,000 characters. So this
route honours neither `reasoning.effort` (attempt_013) nor
`reasoning.max_tokens` (attempt_016). Both were declared, both were sent, both
were discarded. The reasoning declaration now states no control at all, since
declaring one the provider ignores puts a condition in published evidence that
did not hold.

**What was actually binding.** Ten calls stopped at exactly 4,000 output tokens
while the sealed requests said 8,000, 16,000 and 32,000. `harness.py` clamps
every request to `profile.sampling.max_output_tokens` -- a harness may lower
its budget, never raise it -- so the kernel's length escalation was recorded
and then discarded. A direct probe on the same route returns 8,000 tokens for
an 8,000 request, so the provider was never the limit. Filed as #134: the
receipt states a budget that was not sent, which is why three attempts went
looking for the problem in the model.

**Why 4,000 was too small, which is not what it looked like.** Replaying one
failing observation gave reasoning lengths of 949, 1,275, 1,296, 1,639, 2,935
and 8,254 characters across identical calls. The distribution is heavy-tailed,
not long. Most calls fit; the tail does not, and a call whose reasoning fills
the budget returns empty. That is also why the isolated probes kept coming back
clean and were reported as inconclusive rather than as evidence of a fix -- a
handful of draws from a distribution whose tail is the failure will usually
miss it.

v6 raises the output budget to 12,000 and declares no reasoning control.

**Correction to the record.** Two things stated earlier in this file are wrong
and are left standing above rather than edited away. "Headroom does not fix
that" was based on failures at 2,400, 6,000 and 12,000 that were themselves
clamped, so headroom was never actually tested. And attempt_013's write-up
called the reasoning cap "the remaining mechanism", which assumed the provider
honours it; it does not.

## attempt_018 — headroom was finally tested, and the original note was right

v6 raised the output budget 4,000 -> 12,000 on the reasoning that the earlier
"headroom does not fix it" observations had all been clamped and so never
actually tested. They were clamped. The conclusion was still correct.

At 12,000, `procurement.basic.0` -- the case that had passed every previous
attempt, under every configuration -- failed. Twenty-six of thirty-two calls
returned empty at `finish_reason: length`, each having filled the entire
12,000, with reasoning running to 34,000-55,000 characters. At 4,000 the same
model reasons to roughly 10,000 characters. It expands to occupy whatever it is
given.

So headroom buys nothing and costs in proportion: attempt_018 spent $0.4144 to
fail a case that attempt_016 failed for $0.0558. The budget is back at 4,000.

**Correction, and this one is mine.** The attempt_016 write-up above says the
earlier headroom failures "were themselves clamped, so headroom was never
actually tested", and treated that as reason to expect the raise to work. The
clamping was real (#134) but the inference was not: the original v1 note --
"it expands to fill what it is given" -- had already described the behaviour
correctly from direct observation, and I discounted a correct empirical claim
because I had found a mechanism that could have explained it away. Finding a
plausible alternative cause is not the same as disproving the stated one.

**Where this leaves the family.** On this pinned route there is no remaining
lever. `reasoning.effort` is discarded (attempt_013, verified in the sealed
request). `reasoning.max_tokens` is discarded (attempt_016, likewise). The
kernel's length escalation is clamped to the profile ceiling before it reaches
the wire (#134), so `length` retries only re-roll sampling. And the profile
ceiling itself is not a lever, because reasoning grows to meet it.

What remains is a property of the route, not of the harness: GLM 5.3 Flash on
Parasail fp8 emits no action for a fraction of these observations, and that
fraction is a draw rather than a fixed set of cases -- `scheduling.basic.1`
passed under v4 and failed under v5 on an identical wire configuration, and
`procurement.basic.0` passed everywhere until it did not.

Two honest ways forward, and the choice is not the runner's to make: measure a
route that honours a reasoning control, or keep this route and treat a
no-action episode as typed missingness with a declared episode-level retry
budget. The second changes what the panel measures and needs to be declared
before it is run, not after seeing which cases it rescues.

## attempt_020 — the ceiling is not a lever, established across four values

v8 raised the output ceiling to 24,000, sized from the calls in attempt_019
that produced usable actions: they needed 4,521-7,070 tokens, so 4,000 sat
below all of them. That reasoning was correct about the successes and wrong
about the failures, because the failures scale with the ceiling as well. At
24,000, ten of twenty-four calls filled the entire budget and returned empty.
The run reached period 5 of 100 in an hour at $0.1467 -- roughly $3 and twenty
hours per case -- and was stopped rather than left to hit the cap on its own.

The ceiling has now been run live at 4,000, 6,000, 12,000 and 24,000. The
failure survives all four. Raising it buys a few more successes and makes every
failure proportionally more expensive in both money and time. The declaration
returns to 4,000 and the cost ceilings to $0.20/$1.30, because 4,000 is the
cheapest way to fail, not because it works.

**The record on this point, in order, since I got it wrong twice.** The v1 note
said the model "expands to fill what it is given". I set that aside once on the
grounds that those observations were clamped (#134), and again on the grounds
that a declared 32,000 call had stopped at 6,165 tokens. The first was a real
mechanism that did not license the inference; the second was a true observation
about the calls that succeed, generalised to the ones that fail. Both times the
original claim was better supported than the argument against it, and both
times the way to find out was a live run that cost money.

**Terminal state for this family on this route.** Six cases, three levers, four
ceiling values, and no configuration in which the panel reliably completes.
`reasoning.effort` is discarded by the route. `reasoning.max_tokens` is
discarded. The output ceiling changes the price of failure, not its rate. What
remains is a property of GLM 5.3 Flash on Parasail fp8: for a fraction of these
observations it emits no parseable action, and the fraction is a draw rather
than a fixed set of cases.

The best evidence the family has produced is
`econevals_..._reasoning_capped_v4/attempt_015`: 6/6 cases, 100 periods each,
$0.4376, `scheduling.basic.1` at the exact optimum. It is unpublished because
its plan named a reasoning condition it did not run and its canary admitted a
configuration the panel never used -- both since fixed, neither fixable
retroactively for that bundle.

Publishing a panel from here requires a decision that is not the runner's:
measure a route that honours a reasoning control, or declare episode-level
typed missingness with a retry budget in advance. The second is defensible; it
is not defensible chosen now, by me, with the failing cases already known.

## v9 attempts 021-022 — the control I declared discarded is the control that works

Three consecutive attempts (019, 021, 022) failed `procurement.basic.0`, a case
that had never failed before. The three share one thing: they are the only
configurations that sent no `reasoning` block at all, because attempt_016's
write-up concluded the route discards reasoning controls and that declaring one
would state a condition that did not hold.

That conclusion was wrong, and measuring it takes one table:

| `procurement.basic.0` | calls | median reasoning | finish |
|---|---|---|---|
| with `reasoning.max_tokens: 1500` (v5) | 100 | **31 chars** | 100 × `stop` |
| no reasoning block (v9 att021) | 7 | 11,703 chars | 7 × `length` |
| no reasoning block (v9 att022) | 21 | 12,174 chars | 18 × `length` |

Same case, same route, same 4,000-token ceiling. With the block the model
reasons in tens of characters and never truncates; without it, in tens of
thousands and mostly does.

**How the error was made.** The claim "this route discards `reasoning.max_tokens`"
came from one observation: a `scheduling.basic.1` failure where the 1,500
declaration was present on every call and reasoning still ran past 10,000
characters. That observation is real and still stands. The mistake was
generalising it from the one case that overruns to the route as a whole. The
control is a suppressor, not a hard cap: easy observations obey it by a factor
of several hundred, a hard one can overrun it. Reading a soft control off its
single failure and concluding it does nothing is how a working treatment gets
removed.

The cost of that error was three panel attempts and a public claim on #107 and
#134 that had to be retracted. It also explains the two-path anomaly reported
on #134 without needing two paths: calls differ in how much reasoning the
observation provokes, not in which budget reached the wire.

v10 restores the declaration. The residual `scheduling.basic.1` overrun is
unchanged and remains the family's real constraint.

## v10 attempt_022 — published, 6/6

`evidence/econevals/econevals_glm53_flash_parasail_panel_v10/`, plan
`193b8e10167d0e28`, publication `d3504e43e85f31af`. Six planned, six completed,
six included, zero excluded, zero operational failures, canary admitted.
$0.4276 against a $1.30 ceiling.

| case | objective | v* | gate |
|---|---|---|---|
| procurement.basic.0 | 17.988 | 81.312 | 1.0 |
| procurement.basic.1 | 4.217 | 20.289 | 1.0 |
| scheduling.basic.0 | 0.000 | 0.000 | 1.0 |
| scheduling.basic.1 | 0.000 | 0.000 | 1.0 |
| pricing.basic.0 | 35.088 | 41.661 | 1.0 |
| pricing.basic.1 | 13.009 | 26.421 | 1.0 |

Both scheduling cases reach the exact optimum: zero blocking pairs against
v* = 0. Every gate passes, so all six are genuine submissions rather than
admissions by default -- which is what separates this from `first_light_v1`,
where `gate = 0.0` measured blind submission.

The declared reasoning condition matches the wire: all 111 provider calls on
`scheduling.basic.1` carried `effort=None, token_budget=1500`, and 100 of 107
completions finished `stop`. That check exists because the v4 bundle failed it
-- its plan named a condition it did not run -- and it is worth running on any
bundle before publishing it.

**Attempt disclosure.** This is panel attempt 022, the second attempt under
v10. Attempt 021 failed at `procurement.basic.0` on an upstream Parasail 429
after exhausting ten retries; it reached period 82 of 100 with 82 of 82 calls
finishing `stop`, so the failure was congestion, not the model. Both attempt
roots are kept in the run tree.

The selection here is over attempts, not cases: the panel is re-attempted whole
and no case is ever rerun on its own. Ten campaign identities preceded this one
and every failure is recorded above.

## 2026-09-10, panel v11 (the deliberating arm)

| Campaign | Attempt | Outcome | Cost (USD) | Disposition |
|---|---|---|---:|---|
| `panel_v11` | 001 | aborted on the first case: the bridge could not import upstream | 0.0219 | sealed; the identity is re-attempted as 002 after re-provisioning |
| `panel_v11` | 002 | aborted on the first case: one action exceeded the declared 180 s timeout | 0.1124 | sealed; the arm is **gated on a wall-time decision**, see E-O-15 |

### O — Operational failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| E-O-14 | `panel_v11` attempt 001 admitted its canary (464 output tokens, the deliberating condition confirmed live) and then died on the first case: `econevals bridge op 'procurement_evaluate' failed (ModuleNotFoundError): No module named 'econ_evals'`. Two independent faults in the local provisioning, neither in the adapter: the bridge interpreter had been orphaned by a Homebrew Python upgrade -- its `sys.prefix` resolved to the framework rather than the venv, so its own site-packages (with `gurobipy`, `numpy`, `pandas`) was off the path -- and the pinned upstream checkout had been emptied, 0 Python files where govsim's neighbouring checkout still had 108 | the campaign's own abort on case 0 | $0.0219 of provider spend on a case that could never have completed, and one campaign identity attempt | interpreter rebuilt from `tools/econevals_bridge/requirements.txt`; upstream re-cloned and verified at the pinned commit `e1f2a40f` (43 Python files) before use. Attempt 002 runs the same identity. **Worth a preflight:** the campaign spends on the model before it ever exercises the bridge, so a provisioning fault is discovered at the first tool call rather than at startup. A provider-free bridge call before the canary would have caught both faults for nothing |

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| E-O-15 | with the bridge restored, `panel_v11` attempt 002 admitted its canary and died on the first case with `harness 'econevals_json/1.0' exceeded 180.0s`. The sealed evidence says why: under the unconstrained condition this task draws a **median of 3,323 reasoning tokens per action and a maximum of 12,000** -- the whole completion ceiling -- against ~260 for a TERMS-Bench negotiation turn. The 2026-09-06 note in `live.py` measured the same thing in characters (~12,000) and drew the same conclusion; this is that finding in tokens, with the timeout as the proximate cause rather than truncation | the campaign's own abort on case 0 | $0.1124, and a second attempt of the same identity | **the arm is implemented and gated, not abandoned.** A 100-period case at 1-3 minutes per action is 2-5 hours, so the panel is 12-30 hours of serial wall time. The campaign SOP says to estimate serial wall time before launching and stop if it exceeds the operational limit; the estimate says stop, so the decision is the owner's rather than mine. What makes it a wall rather than a dial is R-D-01: this route offers ~13 reasoning tokens or ~3,300 and nothing in between, so there is no intermediate setting that would buy deliberation at a tenth of the latency |
