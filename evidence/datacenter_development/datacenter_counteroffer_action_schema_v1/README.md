# Data-center counteroffer action-schema preflight V1

This is the sanitized projection of the first 20-cell broad-versus-dedicated
action-schema panel on one curated land negotiation. Both arms used identical
profiles, prompt text, schema catalogs, and first-request content. The intended
treatment occurred only after a formal public counteroffer.

V1 did not qualify that comparison. Nineteen cells completed and one rate-limit
failure remains excluded. Seventeen included cells produced an invalid opening
action before any counteroffer: each returned a non-null offer ID even though
none existed. Nine also returned null terms; eight returned a terms object. The
two cells that reached and adopted a counteroffer occurred on different paired
seeds, leaving zero exposure-qualified matched pairs.

Treat V1 as an instrumentation finding, not an action-schema effect estimate.
Raw provider records, prompts, terms, free-form text, and complete receipts
remain in the ignored local run directory. This publication retains typed
outcomes, safe first-action shape labels, exclusions, route checks, and source
digests. It supports no population, causal, or model-winner claim.

## Layout migration (2026-09-08)

This bundle was migrated to the kernel publication layout without re-running the family publisher: `publication_manifest.json` now uses the shared `aeread.publication_manifest/0.1` form (dict `artifacts`, `manifest_sha256`, `privacy_boundary`), the per-episode family trace moved from `trajectories/sanitized.jsonl` to `trajectories/episodes.jsonl` byte-for-byte, and the kernel per-action grain (`aeread.sanitized_trajectory_row/0.1`, 26 rows over the 20 published receipts) was added as `trajectories/sanitized.jsonl`. Every other file is unchanged; the original publisher hashes and source digests are carried in `source_bindings`. See `docs/getting-started/reviewing_trajectories.md` §5.
