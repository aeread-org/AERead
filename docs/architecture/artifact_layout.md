# Run and publication artifact layout

**Status:** normative for new writes; legacy run trees remain readable.

AERead uses three top-level roots with non-overlapping meanings:

| Root | Git policy | Purpose |
|---|---|---|
| `runs/` | ignored | Canonical local execution state, including plans, event logs, provider payloads, receipts, gate attempts, and derived working files. |
| `evidence/` | tracked | Sanitized, immutable publication bundles selected for review or reporting. |
| `work/` | ignored | Non-benchmark scratch such as rendered documents and meeting-note processing. |

Generic `output/` and `outputs/` roots are forbidden. A command that executes a
benchmark accepts `--run-root`; a command that publishes a review bundle accepts
`--publication-root`. Legacy flag aliases may remain temporarily for callers,
but documentation and new code must use the canonical names.

## Canonical execution hierarchy

One shared-runner execution is stored as:

```text
runs/<campaign-or-workspace>/
  <run_id>/
    run_plan.json
    tasks/
      <task_id>/
        attempts/
          <episode_attempt_id>/
            events.jsonl
            artifacts/
            evaluation_receipt.json
```

The caller may use `runs/` itself as the run root for a one-off execution, or
`runs/<campaign_id>/executions/` when one campaign owns several run plans.
Campaign gate histories and summaries live beside `executions/`, not inside a
task directory.

`PlanCell` remains the internal schema name for a planned task. User-facing
paths, exports, and analysis use `task` consistently. An attempt is retained
because retries and operational failures must remain observable.

Provider/model calls are append-only events inside `events.jsonl`. They do not
receive mutable source directories. The report projection turns each started
call and its terminal event into one row of `model_calls.csv`.

## Canonical publication hierarchy

Each selected campaign or run publishes one self-contained bundle:

```text
evidence/<publication_id>/
  README.md
  publication_manifest.json
  tables/
    runs.csv
    tasks.csv
    model_calls.csv
    profiles.csv
    model_features.csv
    benchmark_results.csv
    fact_manifest.json
  trajectories/
    trajectory_index.csv
    archive.jsonl
    selected/
  receipts/                 # sanitized projections only
  reports/                  # human-readable summaries and QC decisions
  qc/                       # admission or qualification records
  ERRATA.md                 # derived sidecar, present only when an erratum selects this bundle
```

A smaller diagnostic publication may omit grains it never produced, but it
uses the same directory names for the artifacts it does contain. It must not
fabricate empty tables to look complete.

Two directories under `evidence/` are not publications. `evidence/errata/`
holds one sealed `ERR-YYYY-MM-DD-NNN.json` per finding recorded after
publication, flat and append-only; `evidence/errata_register/` is the derived
`tables/` + `reports/` view of which bundles each erratum touches. Both are
specified in the [errata standard](../operations/errata.md). An `ERRATA.md`
sidecar is derived from them and never listed in the bundle's manifest, so a
finding can be attached to published evidence without touching its seal.

The publication is a digest-bound projection, not a replacement for the local
`RunPlan`, sealed event chain, or `EvaluationReceipt`. Paths recorded in its
manifest are relative to the publication root, and operational failures remain
visible rather than becoming zero scores.

## Relational contract

The report tables preserve one explicit hierarchy:

```text
runs.run_id
  -> tasks.(run_id, task_id)
       -> model_calls.(run_id, task_id, call_id)
       -> trajectories.(run_id, task_id, episode_attempt_id)
```

Profiles and model-feature facts join through `profile_id`; typed benchmark
results join through `(run_id, task_id, episode_attempt_id)`. A campaign may
contain multiple runs, but no table silently promotes campaign, run, task,
attempt, or call rows to interchangeable statistical units.

## Compatibility boundary

The reader accepts the earlier
`<run_id>/<task_id>/<episode_attempt_id>/` source layout so sealed historical
runs remain replayable. All new writes use the labeled `tasks/` and `attempts/`
levels. If both layouts exist for the same identity, loading fails as ambiguous
instead of guessing.
