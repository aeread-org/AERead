# Commercial state calibration v1

This development family measures evidence-grounded commercial-state
reconstruction under **report-only authority**. An analyst must reconcile
time-indexed evidence, classify commercial states, preserve document and
execution boundaries, perform bounded arithmetic, cite evidence, and avoid
declared unsafe claims or actions.

The pilot contains nine sanitized synthetic cases derived from verified
historical business records. Original entities, identifiers, dates, locations,
models, and commercial values are not included. The source originals are not
part of this repository.

## Measurement boundary

This is a deterministic `property_or_answer` family, not an economic-objective
or interactive negotiation family. Every pilot case is report-only and external
actions are unauthorized. The pilot therefore does **not** estimate whether a
model can distinguish report, draft, and execute authority. A future version
must add positively authorized draft and execute cases before making that claim.

All nine cases conservatively share one `independence_cluster_id`. They are
diagnostic probes from one sanitized commercial archive, not nine independent
samples and not an inferential model-comparison set.

## Leakage controls

- Agent observations contain only the prompt, cutoff, authority, and evidence.
- Termination criteria, gold labels, source roles, and failure mechanisms remain
  evaluator-only.
- Evidence identifiers are opaque within each case (`e01`, `e02`, ...).
- The response wire format is strict JSON and rejects free-form narrative,
  unknown fields, wrong types, duplicate tokens, and unsupported labels.
- Hard-gate failures remain separate from component accuracy metrics.

## Provenance boundary

`pilot/source_catalog_private.json` is a sanitized source-role catalog. It is
not audit-grade lineage: it deliberately contains no original paths,
identifiers, or hashes, and it does not establish redistribution rights. The
pack can support internal diagnostic evaluation, but any public release or
scientific provenance claim requires a separately controlled lineage ledger and
rights review.

## Open-weight variance campaign

The frozen development contract is
`configs/commercial_state_openweight_variance_v1.json`. It compares four
model-plus-provider-route profiles—GLM 5.3 Flash, Mistral Small 4, Qwen 3.8
Flash, and MiniMax M3—while holding the AERead harness, public observations,
schema, sampling controls, budgets, retry policy, and scorer fixed. DeepSeek is
not part of this campaign.

Run the gates sequentially. The command resumes passed gates and sealed cells;
it never selectively replaces an existing result:

```bash
PYTHONPATH=src .venv/bin/python \
  -m aeread_families.commercial_state_calibration.campaign \
  --contract configs/commercial_state_openweight_variance_v1.json \
  --run-root runs/commercial_state_openweight_variance_v1 \
  --through provider_free_validation

PYTHONPATH=src .venv/bin/python \
  -m aeread_families.commercial_state_calibration.campaign \
  --contract configs/commercial_state_openweight_variance_v1.json \
  --run-root runs/commercial_state_openweight_variance_v1 \
  --through full_trajectory

PYTHONPATH=src .venv/bin/python \
  -m aeread_families.commercial_state_calibration.campaign \
  --contract configs/commercial_state_openweight_variance_v1.json \
  --run-root runs/commercial_state_openweight_variance_v1 \
  --through variance_pilot
```

Operational artifacts are organized under
`runs/commercial_state_openweight_variance_v1/`, with a separate attempt
subfolder for each gate. The run root is required explicitly and is ignored
by Git; no live model transcript or receipt is written under `docs/`.

Publish a sanitized, PR-ready projection separately:

```bash
PYTHONPATH=src .venv/bin/python \
  -m aeread_families.commercial_state_calibration.publication \
  --campaign-root runs/commercial_state_openweight_variance_v1 \
  --publication-root evidence/commercial_state_openweight_variance_v1
```

The tracked projection includes parsed outputs, typed failures, metrics, cost
qualification, route facts, receipt hashes, and digest-bound fact tables. Raw
provider payloads, full prompts, and complete receipts stay in `runs/`.

Published fact tables live under `tables/`, sanitized transcript projections
under `trajectories/`, receipt projections under `receipts/`, and the readable
campaign result under `reports/`.

The full-trajectory gate contains four cells: one case and one paired seed for
each profile. The variance pilot contains 108 cells: nine cases, three paired
inference seeds, and four profiles. It emits sealed result rows plus
`profiles.csv`, `model_features.csv`, `benchmark_results.csv`, and a digest-bound
`fact_manifest.json`.

Campaign comparisons remain descriptive. Repeated inference seeds estimate
within-case response stability, but all nine cases still share one independent
source-archive cluster. The campaign therefore cannot support confidence
intervals or a population-level winner claim.
