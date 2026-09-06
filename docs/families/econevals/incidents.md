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
| 008 | case 01 | `SchedulerContractError` | 0.01051 | Spurious Parasail **404** on an endpoint OpenRouter listed as available, after case 00 scored `ok/included`. Classified `provider_rejected`, deliberately not retryable. | none -- route fault |
| 009 | case 02 | `SchedulerContractError` | 0.02164 | Scheduling case exhausted the harness's corrective rounds; the sealed responses show one round returned an **empty string**, spending a round on silence when `empty_response` is a typed provider condition. | `5b81cab4` |
| 010 | case 00 | `SchedulerContractError` | 0.00004 | Ten attempts against a 429 burst exhausted in ~2 minutes: retry backoff is opt-in through `harness.config`, and with none declared the executor never sleeps. | `93f2f148` |
| 011 | all 6 cases | publish only | 0.09250 | **Execution succeeded**: 6/6 cases `ok/included`, 100 periods each, `exit=0`. Publishing then crashed on `ValidityReport.valid` (the field is `.status`), and the fix could not be applied to this run -- see below. | `d3f0c1` design split |
| 012 | case 00 | `SchedulerContractError` | 0.00003 | Spurious Parasail **404** again, on the first action. Second occurrence after attempt 008. | none -- route fault |
| 013 | case 02 | `SchedulerContractError` | 0.02151 | Sustained 429: ten attempts **with backoff** (~3 minutes of spread) all refused, after two procurement cases scored. | none -- route fault |

Total spent on failed attempts: **0.14639 USD**, of which 0.09250 bought a
complete but unpublishable panel.

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
  route-identity distinction commit `50de3447` drew for preflight. Until it
  is ruled on, the disposition stays: re-run the identical frozen plan.

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
