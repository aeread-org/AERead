# Negotiating into an agreement, confirmatory v2: gate review

**Status:** written 2026-10-20 at the owner's request ("finalize v2 review"), after the v2 results
([agreement_confirmatory_v2_results.md](agreement_confirmatory_v2_results.md), 461c5d93). It reviews identity
`agreement_confirmatory_v2` on pack `agreement_admitted_v2` under `docs/operations/benchmark_qc.md`. It is a separate
file because [qc.md](qc.md) §11 has uncommitted edits in another worktree; once they land, §11 should point here. It
relabels nothing published.

**What the case measures.** The plan states the construct and its limit (§1): against the publicly drawn firm
counterpart, the integrator seat measures pricing and bargaining over clauses and price, not inference. The firm
script's first reply reveals the client's charge. The best informed integrator earns 196.3 a deal world at the true
charge and 199.3 when told the type (`codex/datacenter-best-informed`, c12539b5), so knowing the type is worth under
2% of what that policy earns. The verdicts below are for that construct. The case is not evidence about inference, and
it is not an invalid case for being so.

| Gate | Status | Evidence | Blocker |
|---|---|---|---|
| 0, profile | `partial` | qc.md §11 is the family's profile; this file is v2's record | the registry row (`datacenter_agreement_v1`, 03a7faef) is on the branch only and needs a non-author kernel review (DC-J-08) |
| 1, task distribution | `partial` | 80 worlds, 72 with a deal, from 5,436 scanned; seeds disjoint from every earlier pack; v1's admission rules plus a screen that the integrator's full-information ceiling beats the `price_only` rule by at least 25 on every deal world; packs and logs regenerate and recompute (`tests/test_datacenter_agreement_admitted_pack_v2.py`) | no frozen control screened the worlds: the degenerate ground is read only off the subjects (a model's two plays ended identically in 47 of 80 worlds for Opus and 28 for Codex); the client seat still fails the counterpart-type rule (DC-D-35), so it is secondary |
| 2, environment and verifier | `partial` | through the plugin's hooks the full-information pair loses 0 in all 80 worlds, signs c* in the 72 deal worlds and walks in the 8 others, and the draft pair loses exactly its midpoint prediction (test added 2026-10-20); all 640 receipts replay offline from their sealed events; the driver checks a failure receipt's digest and seal (DC-T-22, f97e0ca9) | `aeread verify-replay` through `main`'s CLI cannot run until the family is on `main` |
| 3, construct and baselines | `passed` (integrator seat) | lower controls: the `price_only` rule (exact, 81.9 a deal world) and the draft pair; upper: the best informed integrator (196.3) and the full-information ceiling; the admission screen guarantees the rule leaves room in every deal world; the pack separates the subjects (P3a: Codex − `price_only` +22.6 [8.1, 37.1], Holm p 0.008; P3b: Opus −0.5 [−17.1, 16.1]) | the client seat is `partial` (DC-D-35); the grid references are lower bounds (DC-D-40), but no primary contrast uses them |
| 4, attribution and controls | `partial` | both CLIs isolated and probed clean at the freeze and before every run (amendments 1 and 2); CLI versions are part of the identity; the integrator's brief is v1's byte for byte; every claim names its counterpart, and head to head is reported as a pairing | a CLI takes no seed or temperature; every receipt was sealed under the unreviewed registry row |
| 5, confirmatory reliability | `partial` | plan declared before the pack, the modules or any cell, with three amendments before any cell; a 12-world end-to-end pilot (96 negotiations) on its own pack; sizing from a committed module; freeze with the CLI versions; 640 of 640 negotiations valid, no missingness, no interim look; Holm across the four primaries; v1's departures closed in advance (plan §7); no departure recorded | the bundles are on the branch, not on `main`: the claim cannot stand there until Gates 0 and 2 clear |

**Reading.** Apart from Gate 1's missing frozen-control screen and the client seat's known limit, every remaining
blocker is the one Procurement's version 3 has: the family's registry row awaits a non-author review, and its code is
not on `main`. With the row reviewed and the family merged, verify-replay through `main` closes Gate 2, and Gates 0, 4
and 5 lose their blockers.
