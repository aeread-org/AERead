# Reviewing a published trajectory

This guide is for anyone asked to review trajectories that AERead has
published — a collaborator, an external reviewer, or a future you. It covers
what a published trajectory is, how to verify it mechanically, and what a
human reviewer is actually being asked to judge.

The companion to this page is [Submitting an agent](submissions.md); that page
is for people *producing* runs, this one is for people *checking* them.

## 1. What you are looking at

A published trajectory is a **sanitized projection** of a local campaign run.
It lives under `evidence/<campaign_id>/` and always has the same shape:

| Path | What it holds |
|---|---|
| `README.md` | Campaign intent, what was excluded, and whether the run supports any ranking claim |
| `trajectories/sanitized.jsonl` | One record per episode: parsed model output, typed failure, metrics, route and usage facts |
| `receipts/projections.jsonl` | One record per `EvaluationReceipt`: scores by leaf, inclusion status, replay level |
| `tables/benchmark_results.csv`, `tables/model_features.csv`, `tables/profiles.csv` | Canonical fact tables the paper reads from |
| `tables/fact_manifest.json` | SHA-256 of every table and the contract that produced them |
| `publication_manifest.json` | SHA-256 of every published file plus the publisher's own implementation hash |

Two things are deliberately **not** there: raw provider payloads and prompts
(they stay in the ignored local `runs/` directory), and the evaluation receipts
themselves (only their projections). Every sanitized record carries a
`source_receipt_sha256` that binds it to the authoritative local receipt, so a
published number can always be traced back without exposing provider-account
metadata.

Read the campaign `README.md` first. If it says the run is *diagnostic* or that
all cases share one source cluster, then the run does **not** support a model
ranking, and no amount of reading the tables changes that.

## 2. Mechanical checks (run these before forming an opinion)

None of these need an API key. They confirm the bundle is what it claims to
be; they say nothing about whether the measurement is meaningful.

**Digest binding.** Every file in `publication_manifest.json.files` must hash
to its listed `artifact_sha256`, and `tables/fact_manifest.json` must hash to
`source_fact_manifest_sha256`. A bundle that fails this was edited after
publication and is not reviewable.

```bash
python - <<'EOF'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
manifest = json.loads((root / "publication_manifest.json").read_text())
bad = [
    rel for rel, expected in manifest["files"].items()
    if hashlib.sha256((root / rel).read_bytes()).hexdigest() != expected
]
print("digest mismatches:", bad or "none")
EOF
```

**Replay.** For any receipt whose `replay_level` is `state_and_score`, the
terminal state and score must be recomputable from the sealed event log with
zero provider calls. This is Gate 2, requirement 5 of the
[benchmark QC standard](../operations/benchmark_qc.md). The entry points are
`replay_family_receipt` and `audit_family_receipt` in
`src/aeread/shared_runner/task/evaluation.py`; a campaign that publishes
trajectories for review should ship a one-command wrapper around them next to
the bundle. If no wrapper exists, ask for one — do not accept
`replay_verified: true` in a JSONL record as a substitute for running it.

**Status and inclusion.** Filter `receipts/projections.jsonl` by
`inclusion_status`. Episodes excluded for operational reasons (empty completion,
invalid JSON, HTTP 429, token ceiling) are **typed missingness**, not a score of
zero. A campaign whose exclusions are concentrated in one route or provider has
a routing finding, not a capability finding — check `trajectories/sanitized.jsonl`
`failure` and `expected_route` fields to see which.

## 3. What a human is actually reviewing

Mechanical correctness — parity against upstream, replay, evidence sealing — is
machine-verified. What a script cannot check is whether the **declarations**
match the **measurement**. This is where your attention is most useful, and it
follows the [verifier taxonomy](../research/verifier_taxonomy.md).

For each family in the bundle, look at `receipts/projections.jsonl` `scores`
and the family's measurement declaration and ask:

1. **Is anything judge-dependent labelled deterministic?** A leaf whose
   evaluation mode is `deterministic` must be reconstructible from sealed state
   alone. If it depends on a rubric, a rater, or a model-as-judge, the label is
   wrong even if the number is plausible (taxonomy §2.2, §7).
2. **Is a bound presented as an attainable optimum?** An upper bound, a greedy
   baseline, or a "natural maximum" is a reference leaf. It must not be the
   denominator of a "fraction of optimum" claim unless the family has certified
   it as achievable (taxonomy §5.1–5.3).
3. **Is each estimand carved the way you would carve it?** Comparative families
   must declare the opponent, pairing, and seed as part of the estimand;
   simulation families must declare clusters and seeds; a family that reports
   one blended scalar where the taxonomy says *retained vector* is hiding
   information (taxonomy §6, §8, §10).
4. **Does the primary leaf match the campaign's claim?** `primary_leaf_id` is
   what the fact tables report. If the campaign README argues about legality or
   constraint satisfaction but the primary leaf is an economic value, the
   headline and the evidence have drifted apart.
5. **Would the illegal-action golden have caught this?** Gate 2 requires an
   invalid-or-unauthorized golden that changes no protected state and receives
   no credit. If the sanitized records show only well-formed, legal episodes, the
   review has not exercised the verifier's refusal path, and a scorer bug of the
   "positive residual scored as success" kind would be invisible.

Write findings as *declaration ≠ measurement* statements with the leaf id and
the record's `source_receipt_sha256`, so the author can locate the exact
receipt without you sharing anything from `runs/`.

## 4. What a review bundle should contain

If you are preparing trajectories for someone else to review, ship:

- the `evidence/<campaign_id>/` projection as above, unmodified;
- a `REVIEW.md` next to it naming the verifier family, the estimand, the
  primary leaf, and the specific question you want answered;
- a runnable replay/verification command (Section 2) that exits non-zero on
  any mismatch;
- the illegal-action episode, not only the successful one.

A bundle with only successful trajectories and a prose assurance that replay
passed is not ready for review.
