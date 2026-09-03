# Open-harness testing and leaderboards

**Status:** Housing V1 is executable end to end. Other families must pass the
family-readiness gates below before a paid comparison.

This protocol measures the effect of the agent harness while holding the case,
model route, prompt, action schema, inference seed, budgets, and retry policy
fixed. It produces a separate leaderboard for each case family. It does not
combine unlike family scores into a universal scalar.

All campaigns follow the machine-checkable
[experiment campaign SOP](experiment_campaign_sop.md). This page supplies the
harness-specific treatment and readiness rules; the SOP owns promotion,
confirmatory freeze, and canonical fact-table reporting.

To measure opponent-model, opponent-policy, seat-composition, cross-play, or
self-play effects while holding the harness fixed, use the separate
[multi-agent model interaction protocol](../research/multiagent_experiment_design.md).

## Reproduce the Housing comparison

Install the benchmark and the pinned optional harness packages:

```bash
python -m pip install -e '.[dev,harness-bakeoff]'
```

Run the provider-free contract tests before spending money:

```bash
python -m pytest -q \
  tests/test_shared_runner_housing.py \
  tests/test_housing_harness_bakeoff.py \
  tests/test_housing_harness_leaderboard.py
```

Set `OPENROUTER_API_KEY`, then run a one-world qualification for AERead and
LangChain. Use a disposable run directory for this gate:

```bash
PYTHONPATH=src python -m aeread_families.housing.harness_bakeoff \
  --run-root runs/housing-harness-gate \
  --world-count 1 \
  --master-seed 20260831 \
  --arms aeread_minimal_chat_v1 langchain_provider_strategy_v1
```

Run smolagents as a separate full-trajectory gate because its internal agent
loop can make many model requests for one AERead action:

```bash
PYTHONPATH=src python -m aeread_families.housing.harness_bakeoff \
  --run-root runs/housing-smolagents-gate \
  --world-count 1 \
  --master-seed 20260831 \
  --arms smolagents_tool_calling_agent_v1
```

Run LangGraph as its own one-world qualification before adding it to the paired
panel. This condition uses one explicit graph node, provider-native structured
output, and no tools, memory, subagents, or framework-owned retries:

```bash
PYTHONPATH=src python -m aeread_families.housing.harness_bakeoff \
  --run-root runs/housing-langgraph-gate \
  --world-count 1 \
  --master-seed 20260831 \
  --arms langgraph_structured_output_v1
```

After qualification, run the paired panel. AERead and LangChain rotate first
position across worlds to reduce ordering effects:

```bash
PYTHONPATH=src python -m aeread_families.housing.harness_bakeoff \
  --run-root runs/housing-harness-panel \
  --world-count 3 \
  --master-seed 20260831 \
  --arms aeread_minimal_chat_v1 langchain_provider_strategy_v1
```

The command writes sealed per-cell results and a digest-bound `summary.json`.
Repeating the exact command resumes only rows whose result digest verifies. If
the route is rate-limited, keep the failed cells as operational missingness;
do not rerun only the lower-scoring arm or turn failures into zero quality.

Build the machine-readable, CSV, and Markdown leaderboard from the completed
paired artifact:

```bash
PYTHONPATH=src python -m aeread_families.housing.harness_leaderboard \
  --bakeoff runs/housing-harness-panel/summary.json \
  --report-prefix runs/housing-harness-panel/reports/leaderboard
```

Use `--admission <artifact.json>` only when that single-action admission
artifact has the same model revision, provider route, reasoning setting, and
action schema as the full panel. Admission rows appear in a separate table and
never enter the full-trajectory rank.

The checked-in dated evidence is an exploratory development comparison, not a
population-level winner claim. Its three-world paired interval crosses zero.

## Add another case family

### 1. Confirm family readiness

Register the exact family version through `PluginRegistry`. The plugin must
implement all hooks in `REQUIRED_FAMILY_PLUGIN_HOOKS`:

```text
validate_payload, initial_state, phases, eligible_actors, observe,
parse_action, legal, step, terminal, outcome, build_scorer,
build_reference_providers, generator
```

Before adding any external harness, prove that a scripted provider can execute,
finalize, seal, and replay one case without hidden-state leakage. If a legacy
runner exists, define and pass a field-by-field parity specification first.

Current shortest paths in this repository are:

| Family | Starting point | Required work before ranking harnesses |
|---|---|---|
| Procurement grounding V1 | `src/aeread_families/procurement_grounding/runner.py` | Reuse its registered plugin and one-step action schema; add paired profiles and the common result exporter. |
| tau3 retail | `src/aeread_families/tau3_retail/` | Preserve the declared `ToolRuntime`, tool-effect evidence, terminal database parity, and upstream scorer components. |
| Exchange V1 | `src/aeread/exchange_v1/runner.py` | Port the selected case set to the shared family-plugin boundary and close legacy/shared parity before a harness leaderboard. |

### 2. Freeze the comparison contract

Create one profile per harness. Across profiles, keep these fields identical:

- requested and canonical model revision;
- provider, quantization, region or endpoint policy, and price catalog;
- system prompt and phase-specific output schemas;
- temperature, top-p, reasoning effort, and maximum output tokens;
- action, token, cost, timeout, and tool budgets;
- retry ownership, retryable conditions, attempt count, and backoff policy.

Only the harness identity, harness package/version, and unavoidable
framework-owned serialization should vary. Record those differences explicitly
in the resolved `RunPlan`.

For multi-phase families, populate `output_schema_by_action_schema`. A single
global schema is not valid when phases accept different actions.

### 3. Pair worlds and inference

Use the same case IDs, world seeds, replicate indices, and inference-seed base
for every harness. Set `request_seed_source` to `paired_cell_v1`; the runner
derives request seeds from `(base seed, world seed, replicate)` rather than the
harness condition. Rotate execution order by world. Do not let one harness
always run first or always run during warm cache/provider conditions.

### 4. Admit capabilities before execution

Register every harness in `HarnessRegistry` and declare its
`HarnessRequirements`. Resolve the run plan against the provider's declared
capabilities before a live call. Structured-output harnesses require
`structured_output`; tool-loop harnesses require native tools and must dispatch
world effects only through `ToolPort`.

A framework that performs its own hidden retries, tool effects, or subagent
calls is a different treatment. Either disable those behaviors or declare and
measure them as a separate harness condition.

### 5. Use staged gates

Map this family qualification into the shared campaign gates and run in order:

1. provider-free scripted execution and replay;
2. three single-action calls per harness to validate serialization and schema;
3. one complete trajectory per harness;
4. the predeclared paired panel for admitted harnesses only.

Do not promote a framework from the single-action table to the main leaderboard
until it completes a full trajectory under the same contract.

### 6. Persist complete evidence

For every planned cell, retain either a sealed result or a typed operational
failure. Successful cells must bind the receipt hash, relative evidence root,
model-route verification, provider-reported usage/cost completeness, framework
version, retry count, and family score. Public summaries must not contain API
keys, account identifiers, raw provider error payloads, or machine-local paths.

If a framework fails after paid internal calls, report captured usage as a
lower bound and mark the failing action's billing unknown. Never report unknown
cost as zero.

### 7. Build a family-native leaderboard

Rank only harnesses that complete the entire paired panel with verified routing
and complete cost telemetry. Use the family's declared primary outcome as the
first ordering key. Show reliability, wall time, tokens, model calls, cost,
retries, and failures as separate columns. Cost may break an exact quality and
reliability tie, but do not create an arbitrary weighted composite.

Use the world or case cluster, not individual actions, as the uncertainty unit.
Report the paired difference and interval next to the observed rank. Keep
incomplete and failed harnesses visible but unranked, and keep single-action
qualification in a separate table.

Examples of valid family-native primary metrics are the procurement 0–100
deterministic score, tau3's declared terminal/scorer result, or Exchange's
within-tier pooled AER. Their numeric values are not comparable across families.

### 8. Add regression tests

At minimum, cover:

- exact harness and provider capability admission;
- identical paired request seeds across harness conditions;
- phase-specific output-schema selection;
- private evaluator state absent from harness observations;
- tool-call claims reconciled with kernel-recorded effects;
- failed actions represented as missingness with unknown or lower-bound cost;
- result digest verification before resume;
- leaderboard exclusion for incomplete, unverified, or tampered inputs; and
- replayed family outcome and score equality with the sealed receipt.

The shared runner supplies the experiment and evidence machinery. The family
adapter remains authoritative for state transitions, legality, terminal
outcomes, references, and score interpretation.
