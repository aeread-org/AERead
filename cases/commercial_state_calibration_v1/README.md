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
