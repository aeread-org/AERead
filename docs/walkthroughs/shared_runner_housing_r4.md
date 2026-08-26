# Walkthrough: Housing V1 through the shared runner

The Housing adapter is the first multi-seat, multi-phase economic case to execute through the
generic R1-R4 runner. It preserves the strict environment contract while keeping case semantics
outside the runner kernel.

The environment is `src/aeread/housing_env.py`, the runner adapter and CLI are
`src/aeread/shared_runner/housing.py`, and the provider/evidence boundary is
`src/aeread/shared_runner/execution.py`. Their executable contracts are in
`tests/test_housing_env.py`, `tests/test_housing_market.py`, and
`tests/test_shared_runner_housing.py`.

## End-to-end path

```text
fixed housing_v1 case and generator pin
  -> R1 family, suite, block, sampling, analysis, and agent-profile records
  -> R2 canonical RunPlan and one fixed PlanCell
  -> R3 contact phase: simultaneous isolated tenant observations
  -> R4 phase-specific housing_contact_v1 structured actions
  -> R3 respond phase: controlled landlord sees only its own inbox and private cost
  -> local housing_respond_v1 action creates at most one immutable hold
  -> R3 commit phase: tenants sign or walk only the exact hold_id they observe
  -> environment applies terminal rents, payoffs, allocation, and validity
  -> family outcome records L, B, U, within-case score, IR, and wasted contacts
  -> evidence chain and lifecycle reconciliation audit
```

`HousingV1Plugin` reconstructs the strict `HousingMarket` from the frozen case, snapshots it
between phase transitions, and supplies phase-specific observations, parsers, legality checks,
and transitions. The generic scheduler never imports Housing or branches on `housing_v1`.

## Phase and privacy contracts

Each phase has its own structured-output schema:

| phase | schema | allowed economic act |
|---|---|---|
| `contact` | `housing_contact_v1` | offer on one open listing at one rent, or pass |
| `respond` | `housing_respond_v1` | accept or counter one real offer, or pass |
| `commit` | `housing_commit_v1` | sign or walk one exact immutable `hold_id`, or pass |

Tenant observations contain only that tenant's private values, public board, rejected listings,
and own active hold. A landlord observation contains only its listing, private cost, and offers
addressed to its inbox. Observations are computed from the same pre-phase snapshot before any
action is applied.

The smoke block keeps the landlord controlled by `HousingScriptedLandlordProvider`, which runs
locally. Only tenant observations cross the OpenRouter boundary. The admitted live trace checked
all five external request artifacts: every request had role `tenant` and the synthetic private
landlord cost `1571.68` appeared in none of them.

## Bounds and outcome

The adapter reports distinct measurement objects rather than calling every reference a bound:

- `L = 0`: the feasible no-trade floor.
- `B`: the declared adaptive scripted comparison policy on the same frozen world.
- `U`: exact max-weight bipartite assignment on full-information transferable surplus.
- `R`: realized terminal social welfare from signed holds.
- within-case score: `(R - L) / (U - L)` when `U > L`.

`U` is an allocation relaxation. It does not certify that the runner's partial-information,
bounded-round interaction can attain the same value, and it says nothing about a core rent.
Tenant and landlord payoffs, IR violations, signed rents, and wasted contacts remain separate
diagnostics so a welfare score does not erase distributional capture or execution failures.

## Provider and retry ownership

The live tenant profile pins OpenRouter's DeepInfra route for
`deepseek/deepseek-v4-flash-20260731`, disables fallbacks and SDK retries, and starts with a
512-token output ceiling. The only declared retry condition is `length`. A length retry restarts
the action attempt with a distinct provider call and doubles the output ceiling to 1,024.

The first contact in the admitted trace returned reasoning but no final JSON at the 512-token
ceiling. That billable call was recorded as `provider_call_failed` with its raw usage and cost;
the next declared action attempt succeeded at 1,024 tokens. No provider-owned retry or route
fallback occurred.

## Commands

Zero-cost integration proof:

```bash
PYTHONPATH=src python -m aeread.shared_runner.housing \
  --provider scripted \
  --world-seed 41001 \
  --tenants 2 \
  --listings 1 \
  --rounds 1 \
  --output /tmp/aeread-housing-scripted-smoke
```

Pinned live tenant run with a local controlled landlord:

```bash
export OPENROUTER_API_KEY=...  # set locally; do not commit or print this value
PYTHONPATH=src python -m aeread.shared_runner.housing \
  --provider openrouter \
  --model deepseek/deepseek-v4-flash-0731 \
  --revision deepseek/deepseek-v4-flash-20260731 \
  --world-seed 41001 \
  --tenants 2 \
  --listings 1 \
  --rounds 1 \
  --output /tmp/aeread-housing-deepseek-smoke
```

The CLI writes `run_plan.json` before external work and then emits canonical events and
content-addressed payload artifacts. It prints only identities, outcome, recorded cost, and the
local evidence directory.

## Verified live admission

On 2026-08-26 the pinned live command completed one fixed 2-tenant, 1-listing, 1-round cell.
Tenant 0 offered and signed rent `1700`; the controlled landlord earned `128.32`, tenant 0 earned
`261.22`, and tenant 1 remained unmatched. Realized welfare was `389.54`, equal to both the
adaptive comparison and exact assignment oracle for a within-case score of `1.0`; there were no
IR violations and one wasted contact.

The run made five external calls plus one zero-cost local landlord call. One external contact
attempt hit the declared length ceiling and was retried explicitly. OpenRouter reported 1,314
input tokens, 944 output tokens, and a charged cost of `$0.0002722896`; pinned-price
recomputation gives `$0.00027504`. All 55 event links and payload artifacts verified, and every
started action attempt, provider call, and logical action reconciled exactly once. The non-secret
summary is
[`../evidence/shared_runner_r4_openrouter_deepseek_housing_smoke_2026-08-26.json`](../evidence/shared_runner_r4_openrouter_deepseek_housing_smoke_2026-08-26.json).

## Scientific boundary

This is an instrumentation admission, not a model result for the paper. One fixed world is one
cluster and cannot establish variance, coverage, robustness, model ordering, or saturation.
The equality `R = B = U` on this small case also leaves no baseline-relative discrimination.
A paper run needs the declared case population, multiple independent world clusters, paired
seeds across model conditions, nested replicates, cluster-level intervals, and an explicit
coverage audit. Actions and outcomes remain primary; provider reasoning is only a secondary
diagnostic surface.
