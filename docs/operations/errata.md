# Errata: flagging published evidence after the fact

**Status:** normative for every published bundle under `evidence/`.

Published evidence is never rewritten: receipts are sealed, campaign modules
self-hash into their manifests, gate history is append-only. That is what
makes a number traceable. It also means a defect found *after* publication —
a kernel bug that under-counted cost, a route that was not what the pin said,
a claim later withdrawn — has nowhere to go inside the bundle. Errata are
where it goes.

This complements the [incident log](incident_log.md), which records what
happened and when in prose. An erratum is the machine-readable half: one
sealed record per finding, selecting the affected evidence by identity so
every bundle inherits it without being edited.

## 1. The record

One file per finding under `evidence/errata/<errata_id>.json`, sealed with
`artifact_sha256`, written once and never edited. A wrong or outdated erratum
is **superseded** by a new one that names it in `superseded_by`.

| Field | Meaning |
|---|---|
| `errata_id` | `ERR-YYYY-MM-DD-NNN`, the date the finding was recorded |
| `category` | `kernel`, `family`, `provider`, or `judgment` — where the defect lived |
| `effect` | What a reader must now assume: `cost_lower_bound`, `score_invalid`, `route_unverified`, `evidence_incomplete`, `claim_withdrawn`, `other` |
| `title`, `description` | The finding, stated so a reader of the affected bundle understands the consequence without opening the PR |
| `selectors` | Any of `campaign_ids`, `run_plan_sha256s`, `receipt_sha256s`, `implementation_pins` (`component_id` + digest set), `family_ids`. At least one is required. |
| `fix_ref` | PR or commit that fixed the defect, if any |
| `disposition` | `open` (affected evidence not yet corrected or relabelled), `fixed` (corrected or relabelled), `superseded` |
| `evidence_refs` | Links that substantiate the finding |

Record the erratum **when the defect is found, not when the evidence is
fixed** — the same rule as the incident log. A bundle that is later
republished with corrected numbers does not delete the erratum; the erratum's
disposition moves to `fixed` via a superseding record.

## 2. Selecting by identity

- `campaign_ids` is the universal selector: every published manifest carries
  one.
- `run_plan_sha256s` and `receipt_sha256s` refine to specific plans or
  receipts where the bundle publishes `receipts/projections.jsonl` or a
  manifest `plan_sha256`.
- `implementation_pins` express a kernel-level finding ("every receipt sealed
  under `minimal_chat` digest X"). A pin selector is **unconditional**: every
  receipt carrying that digest is flagged, so use it only when the effect
  does not depend on profile configuration that receipts do not carry (a
  scorer digest is a good pin selector; a bug that only bites when
  `max_rounds > 1` is not — select those by plan digest after resolving
  which plans qualify). Published projections omit pins, so resolve the
  selector once against local run directories with
  `plans_sealed_under(runs_root, component_id, sha256s)` and record the
  resulting plan digests in the erratum as well, so published evidence can
  match it.

## 3. What is derived from the records

Regenerate with `aeread errata --write-notes` (or
`python -m aeread.shared_runner.analysis.errata`). Everything it writes is
derived and reproducible; regenerating must yield identical bytes or the
records and the evidence have diverged.

- `evidence/errata_register/tables/affected.csv` — one row per (erratum,
  affected bundle) with what matched (`matched_by`), effect, disposition, fix.
- `evidence/errata_register/reports/summary.json` — sealed counts, by-erratum
  and by-effect indexes, `rows_sha256`.
- `evidence/<bundle>/ERRATA.md` — a sidecar next to each affected bundle,
  never inside its manifest, so the seal is untouched and a reader sees the
  finding where they would look for the numbers.
- Research ledgers built with `build_research_ledger(..., errata=...)` carry
  `errata_ids` on every attempt row, so exported tables can filter or
  footnote affected attempts.

## 4. When to file one

Any time the incident log gets a row whose consequence reaches already-
published numbers: a kernel accounting or evidence bug (`kernel`), a family
scorer or verifier defect (`family`), a route or provider that did not do what
its pin declares (`provider`), or a claim the maintainers withdraw
(`judgment`). If the consequence is confined to unpublished local runs, the
incident log alone is enough.
