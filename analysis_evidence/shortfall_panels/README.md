# Table 5.5: current case panels

This is a post-run, descriptive accounting derivation for working draft v8,
17 October 2026. It does not change frozen campaign identities or establish
a new confirmatory comparison. No model calls are required.

From the draft folder, run:

```sh
uv run --with scipy python analysis_evidence/shortfall_panels/derive_panels.py
```

The entry point is `derive_panels.py`. It regenerates `panels.json`, including
per-unit components, totals, distributions, descriptive Student t intervals,
checks and SHA-256 input bindings. The other Python files and taxonomy JSON
files are historical snapshots from the paper worktree; they document the
original classification and may require their original worktrees to run.
They are not the reproduction entry point for this revision.

- Housing: retain the existing corrected priority classification; join all
  1,764 completed cells to the packaged reply-conditioned v2 analysis using
  campaign ID, world seed and arm. Every cell's correction matches. Average
  both arms within complete main worlds, then worlds. Gemini has 240 complete
  main worlds; GLM and Luna have 260. Missing arms exclude their whole world.
- Procurement: the 20 declared worlds of Table 5.3, two plays each, from
  `procurement_pay_or_test_v3_taxonomy.json` (rules fixed in 51e9bfd3 before the
  flash plays; output ea9dcfdc). Every world's total for each of four subjects
  matches the replayed read-outs in `../procurement_v3/` within 0.001. No plays
  are missing. The declared rules file an early award's whole loss under
  information not acquired, including a worse quantity (P-T-23): $6.33 a world
  of Luna's. `procurement_pay_or_test.py` and its taxonomy are the earlier
  pack's (Table E.14) and are not read.
- Data center: verify every artifact hash in the firm-population and
  head-to-head publication manifests; read their 360 valid negotiations.
  Joint loss is allocation plus no-deal plus delay loss. Split allocation
  into inferior clauses in positive-surplus worlds and harmful agreements
  in worlds with no positive available surplus. For Table 5.5, average the
  two focal roles within each of the 60 worlds, then worlds. These are joint
  outcomes, including actions by the subject and the firm counterpart.
- Refund: map the original cell-level parts, average 20 retained cells in
  each of six fixed cases, then cases. Each subject has 120 cells and no
  operational exclusions in the retained taxonomy.

The script checks component identities and source totals at the precision of
the retained evidence (1e-5 for component identities; 0.0051 when matching
two-decimal published means). It keeps signed Housing amounts. Rounded paper
components can differ from rounded totals by 0.1.

Intervals in Table E.9 and this report are newly derived descriptive t
intervals, not substitutions for declared campaign intervals. Correlated
arms and seats are averaged before computing them. Refund's six cases are a
fixed suite; its intervals do not justify population or model-ranking claims.
Intervals are untruncated, including those crossing Refund's 0–100 bounds.
One retained run per world/condition leaves run-to-run variance unmeasured
for Housing, Procurement and Data center. Refund's per-case repeated-cell
outcomes are included in `per_case_cell_totals`.

Provenance: taxonomy snapshots from `docs/paper-case-studies-qc`; Data-center
confirmatory report at 12516caf, with bundled source bindings; Housing uses the
independently verified reanalysis already packaged in v7; Procurement uses the
v3 read-outs in `../procurement_v3/` (bound in its SOURCES.json). Refund source snapshots were read from the clean `refund-gap` worktree
at 220ab7463fad8da2455aef3fd0e0b1e69cb12998. Every used input is hashed.

This check also found a denominator error in v7 Table 5.1: 126.8 / 77.5 are
joint losses over all 60 worlds, not the 45 deal worlds used for earnings.
v8 fixes the denominator and labels the integrator in each assignment.
The paper worktree records the correction as RES-J-05. Prior versions and
sealed campaign evidence remain unchanged.
