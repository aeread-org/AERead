# Source package layout

**Status:** normative for new source files.

AERead separates the shared execution kernel from benchmark-family code. The
source tree uses the same run, task, and model-call vocabulary as the artifact
and research schemas, while preserving a strict dependency direction.

```text
src/
  aeread/
    shared_runner/
      run/                 # plans, campaign gates, contracts, publication, filesystem layout
      task/                # scheduling, execution, tools, receipts, evaluation
      model_call/          # harness contracts and provider-facing adapters
      analysis/            # fact projections, parity, paired statistics
      schemas.py           # cross-level authoring contracts
      measurement.py       # typed measurement contracts
      quality.py           # reusable QC contracts
      registry.py          # family and harness registration
  aeread_families/
    housing/
      environment.py
      runner.py
      qc.py
      case_sweep.py
      model_sensitivity.py
      population_campaign.py
      backend_campaign.py
      harness_bakeoff.py
      harness_leaderboard.py
    <other-family>/
      environment.py
      runner.py
      ...
```

## Ownership rules

1. `shared_runner` contains only behavior that can serve more than one family.
2. A benchmark family owns its environment, prompts, policies, scorer adapter,
   QC implementation, campaign drivers, and family-specific reporting.
3. Families may import the shared runner. The shared runner must not import a
   family, including Housing.
4. `run`, `task`, and `model_call` are execution responsibilities, not three
   interchangeable statistical units. A run resolves tasks; a task owns one or
   more attempts; model calls are append-only events within an attempt.
5. Cross-family analysis belongs in `shared_runner.analysis`; a leaderboard or
   report that assumes Housing fields belongs in `aeread_families.housing`.

## Stable identities versus import paths

Some sealed records contain versioned component IDs that resemble historical
Python module paths. Those values are experimental identities, not instructions
to import from the old location. They remain stable when a source-only move
would otherwise change an admitted profile or invalidate published evidence.
New implementation references use the canonical package path unless a frozen
contract explicitly requires an existing component ID.

## Adding a case

Add case data under `cases/<family>/` and executable family behavior under
`src/aeread_families/<family>/`. Add to `shared_runner` only when at least two
families need the same contract or mechanism and its API contains no
family-specific vocabulary.
