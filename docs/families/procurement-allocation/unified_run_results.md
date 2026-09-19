# Unified regret campaign: observed execution

The implementation and offline admission are complete. The live pilot passed,
but the frozen confirmation is **ineligible after an upstream HTTP 429**. There
is no confirmatory effect estimate or confidence interval. The failed attempt
has not been retried or combined with replacement rows.

| Stage | Observed evidence |
|---|---|
| Integration | PR #146 merged at `488301fcc4090ce5e918e3fbe3a3cfb54aec2b54`; guarded regret, synthetic shortcut falsification, sample noise, and continuous admission share one new campaign identity |
| Provider-free validation | Before paid execution: 3,712 passed. Final handoff suite, including reporting fixes: 3,716 passed, 265 skipped, 2 expected failures; unavailable upstream fixtures remain skipped. Measurement source pins remained unchanged during live execution |
| Offline admission | 96 candidates × 12 environment seeds × 2 policies = 2,304 outcomes; 16 admitted, first six selected |
| Route and pilot | Two canaries admitted; 24/24 pilot trajectories completed and replayed; 168 provider calls including canaries; $0.083486106 recorded |
| Frozen confirmation | 36 planned cells: 15 completed and replayed, one operational failure, 20 unattempted; 99 provider requests dispatched, one without settled billing |
| Review export | All 39 completed pilot/confirmatory receipts replayed again; failed receipt verified as an exclusion with no scores; manifests and source bindings checked; credential/account/raw-provider field scan clean |

The route was `z-ai/glm-5.3-flash`, pinned to Parasail revision
`z-ai/glm-5.3-flash-20260826`. The original frozen confirmation hash is
`78fc2662849ca1bbba26e0ed8469643d2e65b256ff48d82c788cda56eea627c4`.

The failed control cell used environment/inference seed 39002 in world
`d8e1ab9b171752c9c9f656bd66afd807578ca07bcfb2c6de42f2f720c8e59418`.
The sealed provider error identifies a temporary rate limit in Parasail's shared
pool. No provider substitution, selective retry, or score imputation occurred.

## Billing and missingness

Across both stages, 267 provider requests were recorded. Settled charges total
**$0.1320779295**. The unresolved request retains a **$0.0023634** reservation,
so charges plus that reservation total **$0.1344413295**, leaving
**$0.2155586705** within the combined $0.35 ceiling.

The raw runner failure record reports zero usage cost. That is not independent
proof of a zero provider bill. The sanitized review matches its request hash
to the unresolved campaign billing entry and reports its actual cost as null,
while retaining the runner-reported value separately. The original raw row and
receipt remain unchanged. Unattempted cells are separate from failed executions.

## What the pilot supports

Both arms made eligible awards in all 12 pilot cells. Mean regret was $32.90 for
control and $29.44 for treatment. These are pilot descriptions, not a confirmed
treatment effect. The paired world-difference SD was $6.27; the declared
meaningful effect was $11.66. Under the stated normal-world-effect sensitivity
model, simulated planning power was 0.994 with a Monte Carlo lower bound of
0.98697. This conditional calculation passed the planning gate; it does not
establish population power or rescue the incomplete confirmation.

These are six curated synthetic markets. Five selected markets have a public
lead-time/quality relationship in one direction and one in the other; the panel
is not a balanced sample of production markets. Pilot variance combines
environment and inference variability. No real supplier readiness or purchasing
decision follows from these results.

## Review and reproduction

- [Measurement rule](../../../src/aeread_families/procurement_allocation/runner.py): `continuous_promotion_rule` rejects invalid accounting, missing pairs, unreplayed receipts, and unverified treatment awards before computing a world-bootstrap interval.
- [Execution review](../../../evidence/procurement_allocation/procurement_allocation_unified_regret_v1_execution/): inspect the 15/1/20 status split, null effect/interval, request-linked unknown billing, and frozen-plan hash.
- [Updated failure register](../../../evidence/procurement_allocation/procurement_allocation_failure_register/reports/failure_register_2026-09-19_v2.json): 19 bundles, 66 reports, 665 executed rows, 20 unattempted cells, two operational failures, and 287 measured violations. Its two operational costs remain unknown.

The [run plan](unified_run_plan.md) gives reproduction commands. The exporter
does not construct a provider. Its manifest binds every exported artifact,
source-row digest, billing-file digest, measurement source pin, and exporter
implementation hash. The older failure-register snapshots are retained; the V2
QC manifest records the coverage, unknown-cost, and unattempted-cell corrections.

All 39 completed economic outcomes also replay from the tracked case files and
public action traces alone. This check does not need private provider storage:

```sh
PYTHONPATH=src python - <<'PY'
import json
from pathlib import Path
from aeread_families.procurement_allocation.continuous_campaign import economic_world_id, episode_case
from aeread_families.procurement_allocation.regret_decomposition import replay_action_trace
cases = [json.loads(p.read_text()) for p in Path('cases/procurement_allocation_v1/continuous_candidates_v2/opaque').glob('*.json')]
worlds = {economic_world_id(c): c for c in cases}
root = Path('evidence/procurement_allocation/procurement_allocation_unified_regret_v1_execution/reports')
checked = 0
for phase in ('pilot', 'confirmatory'):
    for row in json.loads((root / f'{phase}.json').read_text())['rows']:
        if row['status'] != 'completed':
            continue
        case = episode_case(worlds[row['world_id']], row['environment_seed'])
        outcome = replay_action_trace(case['payload'], row['action_trace'])['outcome']
        for key in ('contribution_margin_usd', 'upper_bound_usd', 'regret_to_upper_bound_usd', 'feasible', 'feasible_award', 'completed_kits', 'violations'):
            assert outcome[key] == row[key], (row['case_id'], key)
        checked += 1
print(checked)  # observed: 39
PY
```

Completing a new confirmation requires a separately declared execution identity
and an explicit infrastructure-retry policy. The user decision on changing the
single-confirmation rule is pending; the [recovery proposal](unified_recovery_proposal.md)
states the fresh seeds, retry boundary, inherited evidence, and remaining budget.
The current failed identity stays sealed.
