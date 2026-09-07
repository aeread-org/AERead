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
