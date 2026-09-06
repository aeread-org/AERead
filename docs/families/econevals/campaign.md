# econevals first live campaign (issue #90)

Campaign id `econevals_glm53_flash_parasail_first_light_v1`: one unscored
admission canary plus a six-case panel, two cases from each of the three
tracks, on the pinned OpenRouter GLM 5.3 Flash / Parasail fp8 route with
fallbacks disabled. Sequential, publish-only, `$0.40` hard ceiling.

Why this family first: econevals is the matrix's **pipeline validator**. Its
objective leaves are scored against an exact optimum that upstream's own
solvers compute -- gurobipy for procurement, scipy for pricing -- rather
than a reimplementation of ours, so a live panel exercises the same shape
procurement's oracle does: model -> declared tools -> sealed receipt ->
offline replay -> measured headroom against a known-correct reference.

## What the panel does and does not claim

Every case is the pinned corpus case, unmodified: payload, `pins.max_steps`
and content digest are the ones the corpus admission gate reproduces
byte-for-byte from the `(track, difficulty, seed)` triple. An early draft
capped periods through the agent budget to fit the ceiling; the dry run
showed that raises `SchedulerContractError` rather than terminating
cleanly, so it would have manufactured failed receipts instead of short
trajectories. The period ceiling is the case's own `max_steps`.

Two limits the results must be read against.

- **The route does not enforce seeds** (`seed_enforced: false` in the
  admission capability vector). Despite `temperature 0`, the same case gives
  different verdicts across attempts: `econevals.procurement.basic.0` was
  `ok/included` in attempt 008 and `invalid_measurement/excluded` in
  attempt 009. This panel is one sample per case and is not reproducible by
  re-running; it is a pipeline proof, not an estimate.
- **The objective leaf's horizon is the final submitted allocation**, so a
  single malformed last period discards an otherwise complete 100-period
  trajectory. That is the declared design, but combined with the point
  above it makes the measurement fragile in a way worth revisiting before
  any comparative claim is built on this family.

An excluded receipt is a measurement outcome, not an operational failure:
the pipeline ran, the episode sealed, and the verifier judged the model's
own submission invalid. The campaign records inclusion per case and only
stops when a receipt fails to finalize at all.

## Defects this campaign surfaced

The adapter had milestones 1-3 (corpus, environment, measurement, scripted
harness, replay) but no live path, so nothing had ever resolved a run plan
or sealed a receipt for it. Building one surfaced twelve defects. Four
would have produced misleading evidence rather than clean failures; two
reach well beyond this family.

| # | Defect | Reach |
|---|---|---|
| 1 | Kernel called `plugin.initial_state(family_case, run=None)` in the replay path but positionally in the scheduler. Nine of eleven external adapters name that parameter `cell`, so replay raised `TypeError` for every one of them. Only tau3 exercised the path in tests, and tau3 names it `run`. | **kernel**; unblocks 9 adapters |
| 2 | Transient 429 on the unscored, zero-cost canary permanently sealed the attempt root, because the canary was write-once. | **campaign contract**; already documented in procurement's design review |
| 3 | `EconevalsScorer` had per-attempt methods but no once-per-episode finalizer, so the kernel could not call it. | econevals (issue #74) |
| 4 | Manifest declared no `scoring.reference_provider_ids`, while the leaves cite seven implementations. The resolver rejects a pin nothing references; the receipt rejects a cited implementation that is not pinned. | econevals |
| 5 | Route seal missing `canonical_model` and price caps; the adapter accepts exactly five metadata fields. | econevals |
| 6 | Agent profile declared no inference seed; the adapter refuses a diagnostic run whose seed is unstated. | econevals |
| 7 | Upstream renders a Python `set` into its scheduling failure message (`stable_matching_environment.py:22`). Set order is not stable across processes, so the tool-replay cross-check failed **nondeterministically**. | econevals; upstream is pinned, so canonicalized at the bridge |
| 8 | Harness validated tool calls while executing them, so a burst that went bad halfway left tool effects the environment never scored. | econevals |
| 9 | Output budget of 900 tokens truncated a real procurement burst mid-JSON (decode failed at char 910). | econevals |
| 10 | Neither the observation nor the submit tool's schema stated the argument's required shape, so GLM submitted `[]` where a mapping is required, in all 100 periods. Scoring that would have measured our omission, not the model. | econevals |
| 11 | An empty turn was treated as a malformed answer, spending a corrective round on silence, when `empty_response` is a typed provider condition the executor's retry already covers. | econevals |
| 12 | Retry backoff is opt-in through `harness.config`; with none declared the executor sleeps not at all, so ten attempts fired back-to-back into one 429 burst. Inherited from tau3's Arena profile; procurement's scaffold always set it. | econevals; same finding as housing `d78a1bc8` |

## Operating notes

The bridge spawns a fresh subprocess per upstream call by design: upstream's
generator reads the **global** numpy RNG, so a long-lived process does not
reproduce instances byte-for-byte. That makes a 100-period case take roughly
seven minutes offline, and a six-case panel about an hour.

Parasail serves GLM 5.3 Flash from a shared upstream pool that rate-limits
in bursts and has also returned a spurious 404 for an endpoint OpenRouter
listed as available. A 404 classifies as `provider_rejected` and is
deliberately **not** in the retryable set: making it retryable would hide a
genuinely misconfigured route. When a burst is sustained, the disposition is
the risk-gate V4 precedent -- seal the audit and re-run the identical frozen
plan in a later availability window.
