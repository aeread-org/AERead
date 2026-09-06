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

## Result, attempt 014 (published 2026-09-06)

6/6 cases completed, 5 included, 1 excluded, **0 operational failures**,
$0.0961 against a $0.40 ceiling, canary admitted on the first probe.

| track | case | inclusion | gate | objective |
|---|---|---|---|---|
| procurement | 0 | excluded | -- | -- |
| procurement | 1 | included | 1.0 | 0.0 |
| scheduling | 0 | included | 0.0 | -- |
| scheduling | 1 | included | 0.0 | -- |
| pricing | 0 | included | 0.0 | -- |
| pricing | 1 | included | 0.0 | -- |

**Do not read this as a model result.** Five of six cases have `gate = 0.0`:
the final submission failed the legality gate, so no objective was scored.
The one case that passed the gate captured zero headroom. Under the
interaction shape described below -- one model call per period, the burst
executed afterwards, no tool result ever visible within the period -- the
agent must submit a valid assignment or price vector blind to everything it
just looked up. A gate of 0.0 under those conditions measures the adapter's
interaction shape, not the model's economic reasoning.

What the panel does establish is the pipeline: live model -> declared tools
-> sealed receipt -> offline replay -> measurement against upstream's own
exact optimum, six times, with no operational failures.

## Fidelity against the original paper (checked 2026-09-06)

Verified against the pinned checkout `sara-fish/econ-evals-paper` @
`e1f2a40`, not from memory.

### The interaction shape differs, and it matters

Upstream runs a multi-turn loop **inside each period**
(`experiments/procurement/run_procurement_experiment.py`):

```python
messages = [{"role": "user", "content": initial_prompt}]
for i in range(max_queries):          # max_llm_queries_per_period = 40
    log, response, completion = call_llm(..., messages=messages)
    messages.append({"role": "assistant", "content": completion["content"]})
    # every tool result is appended to messages before the next call
```

The agent calls a tool, sees the result, and decides what to do next. That
observe -> act -> observe loop is the agentic capability the benchmark
exists to measure.

This adapter makes ONE model call per period and executes the returned burst
afterwards, so the model never sees a tool result within the period -- it
sees the previous period's summary through `get_previous_*` on the next
turn, and must commit its submission blind to whatever it looked up in the
same period.

**Fixed 2026-09-06.** `EconevalsJsonHarness` now loops within the period:
the model issues read-only calls, sees their results fed back, and calls the
submit tool on its own to end the period. Every call across every step
accumulates into one action with the submit last, which is the shape
`parse_action` requires; mixing read-only calls and the submit in one step
is rejected with feedback telling the model to look first and submit after.

Verified offline: 200 model calls across 100 periods, **every period
containing a step that saw tool results before submitting**, receipt
`ok`/`included`. Under the old shape it was one blind call per period, which
is why the first published panel scored `gate = 0.0` on five of six cases.

The panel published from attempt 014 predates this fix and its scores should
not be quoted; a re-run under the corrected shape supersedes it.

### Documented narrower limits

- **Basic difficulty only.** Upstream supports `Basic | Medium | Hard`
  (`run_procurement_batch.py`); the pip-installed gurobipy free license
  silently rejects models past a size cap, so this corpus is Basic. Results
  speak to the easiest tier.
- **Upstream's global-RNG bug**, already worked around: `generate_instance`
  computes `budget` from the global `numpy.random` state rather than the
  passed `RandomState`, so the bridge spawns a fresh subprocess per
  generation. Not our defect; it is why corpus work is slow.

## An unreconciled-claims marker on every sealed receipt

Every econevals receipt published so far carries
`harness_claim_unreconciled` on **all 100 periods**
(`claimed_tool_calls: 2, recorded_tool_calls: 0`). govsim's carry none.

Cause: the kernel's `port.tool_calls_dispatched` counts only tool calls a
provider returns through its **native** tool protocol
(`model_call/harness.py`, `self.tool_calls_dispatched += len(tool_calls)`),
while this harness -- like tau3.retail's -- speaks JSON dialect and
dispatches through the explicit `ToolRuntime`. The reconciliation therefore
compares a claim count against a denominator that is structurally zero for
this harness style.

The evidence itself is sound: every invocation is sealed as
`tool_invocation_started`/`succeeded` and the receipt replays to a matching
digest. What is wrong is the metric, and it is wrong for any family using
this pattern, tau3 included. The honest fix is for the reconciliation to
compare claims against the tool runtime's sealed invocations rather than the
native-protocol counter; that is a kernel change and is left for a ruling
rather than taken here.

