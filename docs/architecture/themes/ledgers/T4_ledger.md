# T4 Publication and QC: evidence ledger

**Evidence ledger for [T4](../T4_publication_and_qc.md).** Line references are at main 1e2ae367 unless a row says otherwise.

Source tree: `origin/main` `1e2ae367` (paths below are relative to the repository root). Labels: `[read]` read at source, `[run]` reproduced in memory, `[row]` taken from a row or issue text. Cluster ids (G01..G36) refer to the root-cause clustering summarised in the [themes README](../README.md). Threads fetched with gh (read only) on 2026-10-22.

## 1. Evidence ledger

| # | Claim | Source | Label |
|---|---|---|---|
| 1 | A kernel publication manifest already exists: `schema_version` `aeread.publication_manifest/0.1`, fields `publication_id`, `campaign_id`, `artifacts` (path to sha256), `privacy_boundary`, `sanitization`, `source_bindings`, optional `source_commit`, extra family fields, `manifest_sha256`. | `src/aeread/shared_runner/run/publication.py:172`, `:452-503` | read |
| 2 | The kernel builder `seal_publication_manifest` takes only identity, privacy boundary and free-form `**fields`. It computes no planned or completed cell counts, no replay result, no cost qualifier, no claim flags, no QC-profile reference, no family id. | `publication.py:452-503` | read |
| 3 | `aeread seal-manifest` writes or re-seals a manifest from files on disk and carries family fields over; its CLI arguments are identity, privacy and source bindings only. | `src/aeread/shared_runner/run/seal_manifest.py:25-60` | read |
| 4 | `rebuild_publication_manifest` refuses any manifest whose `schema_version` is not exactly `aeread.publication_manifest/0.1`. | `publication.py:528-531` | read |
| 5 | `evidence/**/publication_manifest.json` has 99 files: 70 use the kernel schema 0.1, 29 use many distinct family-specific `schema_version` strings (datacenter_*, commercial_state, ...). The Examiner's `discover()` on main finds 135 bundles, so 36 have no manifest (older `reports/` layout, `build_general_examiner.py:899`). The Examiner triage counted 144 on its own base. | count over `evidence/`; `discover()` | run |
| 6 | Of the 99 manifests, cost_qualifier, total_cost_usd, winner_claim_allowed and inferential_model_ranking_allowed appear in 11; claim_status in 11; none carries planned or completed cell counts or a replay result. None of the 70 kernel-schema manifests carries `source_commit`. | key census over the 99 files | run |
| 7 | Only 64 bundles carry `tables/fact_manifest.json` and its shape is not uniform (3 observed key sets: 21, 17, 9 files). 56 bundles have `receipts/projections.jsonl`, 59 have `trajectories/sanitized.jsonl`. | `find evidence` | run |
| 8 | Row-level finish_reason is a kernel published field for new bundles (`_PROVIDER_RESULT_PUBLIC_FIELDS`, `_CANONICAL_RESPONSE_PUBLIC_FIELDS` include `finish_reason`, `truncated`). | `publication.py:175-196` | read |
| 9 | The two bundles holding the 8 rows (`procurement_allocation_qwen3_30b_coreweave_case_variance_v2`, `procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2`) publish reports only: no `receipts/projections.jsonl`, no `sanitized.jsonl`. `finish_reason` appears only in the admission canary reports. Rows are listed as `violations:["malformed_json"]` with no finish_reason. The truncation cause is therefore not recoverable from the bundles. | file listing and grep of both bundles | read |
| 10 | Main types a length-truncated structured reply as a provider failure before the family parser, except when `_is_usable_truncated_reply` holds (a harness already built an action, or the text is a complete JSON value): then `retry_condition` is cleared and the reply continues as an answer. Ruling D-14 (reject parseable content reported as truncated) is therefore not fully implemented; the residual belongs to T1. | `src/aeread/shared_runner/task/execution.py:1191-1203`, `:3518-3520`; [rulings register](rulings_register.md) D-14 | read |
| 11 | PR #117 (errata layer) is CLOSED, not merged; closed 2026-10-21 "on the owner's decision" (kernel-review red since 2026-10-01, over the 3-ready-PR limit). Branch `codex/evidence-errata-layer` kept; to resume: address requested changes, rebase, open a fresh PR. | `gh pr view 117 --comments`, last comment | read |
| 12 | `errata.md` (under `docs/operations/`), `evidence/errata/`, `evidence/errata_register/` and an `errata` verb in `src/aeread/cli.py` do not exist on main. They exist only on the #117 branch (15 files, 1385 insertions). | `ls docs/operations evidence`; `grep errata src/aeread/cli.py` empty; `git diff --stat origin/main...origin/codex/evidence-errata-layer` | read |
| 13 | #117 review (Zeyu, head f1de54e0) requested changes: `family_ids` selector can never match; bundle path drops `implementation_pins`; shipped register only exercises the empty case. Later head 6c307d5c removed the family selector and unified selectors; "Still needs one non-author approval". | #117 comments; `errata.md` section 2 on the branch | read |
| 14 | The branch's errata doc says family targeting is deferred "because neither the published manifests nor the bundle subjects declare a family identity", and that restoring it needs a declared family identity in the kernel publication manifest. It also says current bundles omit `implementation_pins`. | `git show origin/codex/evidence-errata-layer:docs/operations/errata.md` section 2 | read |
| 15 | Errata select by `campaign_ids`, `run_plan_sha256s`, `receipt_sha256s`, `implementation_pins`, all at bundle, plan or receipt grain; `scan_bundles()` reads `receipts/projections.jsonl` (`errata.py:111-140, 487` on the branch), not sanitized action rows. There is no row grain, and one receipt can hold several actions. For the 8 rows an erratum could only select the whole campaign, or receipts that these bundles do not publish. | same doc, sections 1-2; claim 9 | read |
| 16 | #117 comment 3: after #180, 59 of 76 bundles live in `evidence/<family>/<campaign_id>/`, 17 stay flat; a bundle scan must cover both depths. | #117 comments | row |
| 17 | `docs/operations/benchmark_qc.md` IS on main (513 lines, Gates 0-5, section 6 contribution admission, last touched by 7924eba0). Clusters G26 and #39.c say it is "only on codex/procurement-harness-bakeoff". That blocker is stale. | `wc -l`, `grep '^#'`, `git log` on the file | read |
| 18 | Examiner triage, 670 flagged lines on 144 bundles, data checked 2026-10-13: systemic classes replay 106, cost_qualified 78, cells_accounted 62, claim_boundary 42, qc_profile 119. Their sum is 407, not 395. | the Examiner triage summary line 3 (working note, unpublished); #287.b "407 of 670" | read |
| 19 | The brief and the theme assignment note (working note, unpublished) give 395 (qc_profile 107). The triage summary shows qc_profile/systemic 119 and qc_profile/review 5. 395 = 407 - 12. Conflict recorded in section 4. | arithmetic over claim 18 | run |
| 20 | 58 of 670 lines need a reviewer after the sorting layer (Examiner `qc-triage`, code and 18 tests on the Examiner repo, version 97). The builder itself is unchanged. | #287 comments 2026-10-13 | read |
| 21 | Examiner `cells_accounted` returns `yes` when both counts are whole numbers; the balance `completed + failures == planned` is only appended as text. Example from N7: planned 10, completed 1, 0 failures reads yes. | `build_general_examiner.py:505-517` in the Examiner repository (copy at a454dc47, Examiner repo, not AERead main) | read |
| 22 | The Examiner reads claim flags first from `publication_manifest.json`, else from `reports/*.json` and `qc/*.json`; it reads cell counts, cost qualifier and replay by scanning top-level report keys and aliases (`planned_trajectory_count`, `cost_accounting`, `replay.json` cells). | `build_general_examiner.py:61-63, 211-230, 271-287, 473-477, 625-640` | read |
| 23 | Row-to-run attachment in the Examiner uses single words of row text; 50 of 77 "not yet read" lines were false attachments, 27 applied. | #287 comment 2026-10-13 (EX-J-05) | row |
| 24 | Owner-reported figure: Qwen-thinking inference bundle, 35 of 36 trajectories unparseable at the 1,800-token cap, reported reliability 0.97; tables lack `finish_reason`. Draft PR #259 (4 bundles) still open, draft, no review. | #265 comment; `gh pr view 259` | row |
| 25 | Conflict in #265/#259: Qwen-instruct unparseable actions are 0 in the #265 table and 4 in the #259 body table. | #265 comment vs #259 body | row |
| 26 | `incident_log.md` on main carries EVID-O-02 (line 699) and DC-T-02 (line 561). Rows SITE-O-01, SITE-O-02, DC-T-16, P-T-12, RF-T-01, RF-D-06 are not in `docs/` on main; the records mark them "only on non-PR branch(es)". | `grep -rn docs`; records | read |
| 27 | RF-T-01 / #290.f: Refund `_contribution()` binds the QC approval digest to the contribution it just built (`src/aeread_families/refund/v2_runner.py:401`). #290 is an owner-authored design hand-over for Refund V2.6, "not a request to change V2.5"; its table is headed "Change proposed". The cluster record says `ruled_awaiting_impl`; rulings register has no entry. The merged QC standard requires approval digests to bind the exact contract (`benchmark_qc.md:503`). | the issue text (working note, unpublished); records; `v2_runner.py:401` | read |
| 28 | #279 (only procurement has a falsification arm) and #280 (no recorded mutation kills, no known-bad input set) are open, labelled `area:quality-control`; #280 proposes a table in each `docs/families/<family>/qc.md`. | `gh issue view 280`; records #279 | read |
| 29 | `kernel-review` rule: the kernel lane (`src/aeread/shared_runner/**`, `cli.py`, conftest) needs one approval from a non-author on the current head. `publication.py` is in this lane. | `docs/operations/pr_lanes.md:21` | read |
| 30 | PR #256 (housing lemons world, v14 panel, corrected three incident rows) merged 2026-10-22T04:31Z. | `gh pr view 256` | read |

## 2. Member list

Clusters, members, board items. "True at 1e2ae367" is the check made in this pass.

| Member | What it is | State | Owner | True at 1e2ae367 |
|---|---|---|---|---|
| G01 / #135.f | 8 truncated rows published as malformed_json (qwen3 30b case_variance_v2: 6; glm53 confirmatory_v2: 2) | ruled (D-13), awaiting implementation | LEE-CHENYU | Yes. Code defect fixed forward except complete-JSON truncated replies, which still count as answers (claim 10, T1); rows not correctable (no errata layer on main, claim 12) and not selectable (claim 9) |
| G01 / #265.a | Same 8 rows, erratum issue "waiting on #117" | open, `lane:evidence` | LEE-CHENYU | Yes, but its blocker (#117) is closed unmerged (claim 11) |
| G01 / #265.b | 4 inference-panel bundles on draft PR #259 predate the fix | open | LEE-CHENYU | Yes; PR #259 still draft |
| G24 / #287.a | Open incident rows attach to every later run of a case | partly fixed (display layer) | LEE-CHENYU | Yes; builder unchanged (claim 20) |
| G24 / #287.c | Stated limits counted as flags | partly fixed | LEE-CHENYU | Yes, same |
| G24 / #287.d | Disposition state read from first word | open; 3 Housing rows fixed on #256 (merged) | LEE-CHENYU | Partly |
| G24 / #287.e | Rows attach by single words (EX-J-05) | open | LEE-CHENYU | Yes (row) |
| G24 / #287.f | Refund, GovSim, EconEvals have no QC profile; noise hides findings | open | LEE-CHENYU | Triage summary still lists qc_profile gaps for econevals, govsim, refund (claim 18) |
| G24 / DC-T-16 | Two-sided scripted control profiles not named `scripted_*` | open | none | Not on main (claim 26) |
| G24 / N7 | cells_accounted yes with planned 10 completed 1 | secondary, unreviewed prototype | Examiner (Chenyu) | Yes in the Examiner copy (claim 21); not AERead code |
| G24 / B04 | secondary item, no detail beyond the cluster | secondary | none | Not checked |
| G25 / #287.b | Publishing template omits keys the checklist reads (407 of 670 lines) | open; board "Backlog", blocked by "publishing template change" | LEE-CHENYU | Yes (claims 2, 6, 18) |
| G25 / P-T-12 | Relationship README template states two false seed facts | open | none | Not on main |
| G25 / EVID-O-02 | Evidence index README says 82 directories, tree has 93 | partly fixed | none | Row on main (claim 26); README guard test not verified |
| G25 / SITE-O-01 | Site results CSV disagrees with its chart in 23 of 64 cells | blocked on owner ruling | none | Not on main; site is not a sealed bundle |
| G25 / SITE-O-02 | Examiner deploy published six unreleased runs | open, owner decides whether public | none | Not on main |
| G25 / DC-T-02 | v12 publication verified by nothing on a clean checkout | open | none | Row on main (claim 26) |
| G26 / #39.c | Eleven builds hit the same contract gaps; says benchmark_qc.md not on main | partly fixed | LEE-CHENYU | The benchmark_qc.md claim is false now (claim 17) |
| G26 / #279 | Only procurement has a falsification arm | open | LEE-CHENYU | Per issue text (claim 28) |
| G26 / #280 | No recorded mutation kills, no known-bad inputs | open, board T4 / SOP / Backlog / P2 | LEE-CHENYU | Yes (claim 28) |
| G26 / RF-T-01, #290.f, RF-D-06 | Refund runner mints human-QC approval | proposal in a V2.6 hand-over (`[record]`); cluster says ruled | ychenfang | Code true at `v2_runner.py:401`; ruling status not confirmed (claim 27) |
| G26 / #289.e | Contribution admission accepts placeholder schemas | open | LEE-CHENYU | Row only |
| Board #287 | Defect, tooling, P2, Backlog, T4 | open | LEE-CHENYU | Yes |
| Board #280 | Defect, SOP, P2, Backlog, T4 | open | LEE-CHENYU | Yes |
| Related #117 | Errata layer PR | CLOSED unmerged 2026-10-21 | LEE-CHENYU | Not on main (claim 12) |
| Related #259 | Draft PR holding the 4 unflagged bundles | open draft | LEE-CHENYU | Yes |
| Related #265 | See above | open | LEE-CHENYU | Yes |

## 3. Rulings in force

| Ruling | Label | Source |
|---|---|---|
| D-13: truncation is typed `length` and never a scored answer (#152 option 1); history stays, an erratum record is to follow | `[owner]` 2026-09-10 | rulings register D-13; rulings register row for #152/TB-D-03 |
| D-12: completed, non-truncated malformed output remains model behaviour | `[owner]` 2026-09-10 | rulings register D-12 |
| D-11: kernel landing order #246 (merged), #291, #292, #293; #248 after part-1 repairs | `[owner]` 2026-10-21 | rulings register D-11 |
| Published evidence is never rewritten; defects after publication go to an errata layer (design in docs on the #117 branch) | `[record]` (not merged); the closure of #117 is `[owner]` (comment states "on the owner's decision") | claims 11-12 |
| QC standard `benchmark_qc.md` Gates 0-5 and section 6 is in force on main | `[merged]` | claim 17 |
| #290.f: runner must not mint the Refund human-QC approval | `[record]` proposal in the V2.6 hand-over; the cluster lists it as ruled, the register does not (claim 27). The general requirement that the approval digest bind the contract is `[merged]` (`benchmark_qc.md:503`) | #290, records |

No ruling exists on: the content of a publication manifest, who may supply the five facts, or how legacy bundles are read by the Examiner.

## 4. Open questions and conflicts between sources

| # | Item | Detail |
|---|---|---|
| Q1 | Manifest facts for legacy bundles | 29 manifests use family-specific schemas and cannot be re-sealed by the kernel (claim 4). 70 kernel-schema manifests lack the facts. Sealed bundles cannot be edited. Whether a derived, separately sealed facts file may be accepted for them is not ruled. |
| Q2 | Row-level erratum | The errata design selects at bundle, plan or receipt grain (claim 15); the 8 rows sit in bundles with no receipt projection (claim 9). Not decided whether an erratum may flag the whole campaign, or the source receipts must be published first. |
| Q3 | N7 scope | Aggregate count balance versus per-cell identity coverage (cluster G24 blocking ruling). |
| Q4 | SITE-O-01, SITE-O-02, DC-T-02 | Owner decisions per the rows (regenerate or label; stay public or not; commit bundle or delete publisher). |
| Q5 | #259 | Decision before it merges: add a predates-ruling flag or select the four bundles by erratum. |
| C1 | 395 versus 407 | the theme assignment note (working note, unpublished) and the brief say 395 (qc_profile 107). Triage summary and #287.b say 407 (qc_profile 119). Charter uses 407 and notes it. |
| C2 | benchmark_qc.md | G26/#39.c say not on main; it is on main (claim 17). |
| C3 | "#117 awaits kernel review" (G01, #265.a, #135.f) | #117 is closed unmerged (claim 11). |
| C4 | Brief: "a manifest schema generated by the bundle builder" as new | A kernel manifest and builder exist (claims 1-3); the gap is the facts, adoption and enforcement, not the existence of a schema. |
| C6 | Cluster status for #290.f | Cluster G26 says "ruled"; #290 reads as a V2.6 design proposal and no register entry exists (claim 27). Charter labels it `[record]`. |
| C5 | Qwen-instruct unparseable count | 0 in #265, 4 in #259 body (claim 25). Not needed by the charter. |

## 5. Not verified

- The 144-bundle Examiner census and the 670 lines were not recomputed; figures are from the triage summary and issue comments.
- The Examiner repository was read only through a copy outside this repository (a454dc47), not at its current head.
- No row-level proof that the 8 rows would have parsed; the ruling was decided on the signature (record #135.f).
- SITE-*, DC-T-16, P-T-12, RF-* rows: not on main, not re-checked against their branches.
- Whether the kernel PRs #291-#293 or #248 touch `publication.py`: not checked, so the delivery order is stated relative to the owner's order, not to file overlap.
