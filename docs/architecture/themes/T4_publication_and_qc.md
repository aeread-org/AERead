# T4: Publication and QC

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5 and is decided in [issue #319](https://github.com/aeread-org/AERead/issues/319); a ruling is recorded here with its date and source.

**Summary.** Published bundles do not carry the facts the Examiner and the QC gates need (replay result, cost qualifier, planned and completed cell counts, claim boundary, QC-profile reference), so every check guesses from report keys and every fix is one bundle at a time. 407 of the Examiner's 670 flagged lines are this one gap. The direction is one versioned facts block in the existing publication manifest, written by the bundle builder, in which each fact is marked `derived` (recomputed from sealed receipts), `verified` (replay or independent check actually run) or `declared` (a publisher claim), and read by the Examiner and the gates as the only source; corrections to sealed bundles are carried by an errata layer. The ruling requested: may the Examiner stop inferring these facts for bundles sealed after a cut-over, and how are the three kinds of existing bundle (70 kernel manifests, 29 family manifests, 36 with none) to be read.

## 1. Problem and root cause

Root cause: a bundle is sealed from whatever the family publisher chose to write. The kernel manifest (`aeread.publication_manifest/0.1`) fixes identity, artifact digests and privacy boundary but not the run facts, so the facts live in free-form report keys. The Examiner recovers them by key scans and word matches, QC gates are asserted in prose, and a sealed bundle has no place to receive a correction. Each symptom below is a different face of the same absence.

| Symptom | Where it shows | Evidence |
|---|---|---|
| 5 facts absent from bundles: replay 106, cost qualifier 78, cell counts 62, claim boundary 42, QC profile 119 = 407 of 670 lines | #287.b; Examiner triage | the Examiner triage summary line 3 (working note, unpublished) `[read]`. the theme assignment note (working note, unpublished) says 395 (QC profile 107); the summary says 119 |
| Kernel builder writes no run facts | all new bundles | `src/aeread/shared_runner/run/publication.py:452-503` `[read]` |
| Only 11 of 99 manifests state cost qualifier or claim flags; none states cell counts or replay | evidence/ | key census over 99 manifests `[run]` |
| 29 of 99 manifests use family-specific schema versions that the kernel re-seal refuses; 36 more bundles have no manifest at all (135 discovered at `1e2ae367`) | evidence/ | census and Examiner `discover()` `[run]`; `publication.py:528-531` `[read]` |
| Cell accounting reads "yes" when both counts exist, even planned 10, completed 1 | N7, G24 | `build_general_examiner.py:505-517` in the Examiner repository (Examiner repo copy) `[read]` |
| Rows attach to runs by one word; 50 of 77 attachments false | #287.a/.d/.e, DC-T-16 | #287 comment 2026-10-13 `[row]` |
| 8 published procurement rows typed as model behaviour were truncation; the bundles do not say which rows | G01, #135.f, #265.a | bundle file lists and report grep `[read]`; ruling D-13 `[owner]` |
| 4 more bundles (draft PR #259) predate the fix; 35 of 36 Qwen-thinking trajectories unparseable, reliability 0.97 reported | #265.b | #265 comment `[row]` |
| No place to correct a sealed bundle: errata layer #117 closed unmerged 2026-10-21 | G01 | `gh pr view 117` `[read]`; no `errata` verb on main `[read]` |
| Hand-maintained indexes, templates and deploy scripts drift (evidence index 82 vs 93, site CSV vs chart 23 of 64, six unreleased runs deployed, v12 publication verified by nothing on a clean checkout) | G25 | EVID-O-02, DC-T-02 on main `[read]`; SITE-O-01/02, P-T-12 `[row]` |
| QC gates are claimed, not checked: runner mints Refund approval, one family has a falsification arm, no recorded mutation kills | G26 | #279, #280 `[read]`; RF-T-01 `[row]` |

## 2. Direction

**One facts block, generated, read-only to consumers.** Extend the kernel manifest (version 0.2) with a `run_facts` block that `seal_publication_manifest` computes from the sealed receipts and reports instead of accepting free-form fields. Proposed contents, each a typed value with a source path:

| Fact | Form | Replaces |
|---|---|---|
| `family_id`, `case_id`, `pack_sha256`, `qc_profile_ref` (path and gate outcomes digest, or explicit `none`) | strings | word match in the Examiner; family targeting that errata deferred |
| `cells`: planned slots, each keyed by `(run_plan_id, cell_id, episode_attempt_id)` (`EPISODE_KEY_FIELDS`, `publication.py:128-135` `[read]`), with a digest of the sorted slot list; completed, typed_missing (by type) and not_attempted as disjoint sets of slots; counts derived from them | slots, digest, integers | key scan; N7's count-only check |
| `replay`: checked, matched, not_checkable, plus how it was run | integers | `replay_verified` guesses |
| `cost`: total_usd, qualifier (`exact` or `lower_bound`), complete flag | typed | cost key aliases |
| `claims`: winner_claim_allowed, ranking_allowed, causal_allowed, claim_status | booleans and enum | per-family claim keys |
| `row_facts`: per-row `finish_reason`, typed outcome, receipt digest (already published for kernel bundles via `sanitized_trajectory_rows`) | table | the README reading used for #265.b |

**Trust tier per fact.** A sealed field proves what the publisher wrote, not that it is true. `replay_verification.py:87` re-drives receipts only with the original run evidence and the family setup, and `benchmark_qc.md:269` (Gate 2) requires scores reconstructed from evidence, not trusted from a declaration `[read]`. So each fact carries its tier and the source of that tier:

| Fact | Tier and source | Consumer may rely on it mechanically |
|---|---|---|
| cells | `derived`: recomputed by the builder from the sealed plan and receipts | Yes |
| cost total and `complete` flag | `derived` from sealed provider results; the qualifier `exact` needs complete coverage | Yes |
| replay | `verified` only if `verify_bundle_replay` ran with run evidence (rows `verified`, `differs`, `evidence_missing`); else `not_checkable` | Only when `verified` |
| claims | `declared` by the family and owner; Gate 3 and Gate 4 judgements are not computable from receipts | No; shown as "declared by publisher" |
| `qc_profile_ref` | `declared` reference; gate outcomes are `verified` only by an independent reconstruction recorded in the QC record | Presence of the reference, not the outcome |

The builder refuses to seal when a `derived` fact cannot be computed, so "not stated" cannot occur in a new bundle; an honest value such as `not_checkable`, `declared` or `lower_bound` is allowed. Family publishers pass run facts to the builder and stop writing manifests by hand (`aeread seal-manifest` already exists for this, `seal_manifest.py:25-60` `[read]`).

**Consumers.** The Examiner reads `run_facts` and nothing else for these five checks. It prints "predates manifest 0.2" for older bundles instead of inferring. The `cells_accounted` rule becomes a computed check on slots (completed, typed missing and not attempted partition the planned slots; the slot digest matches), so a missing cell cannot be hidden by a same-named cell of another plan (`datacenter_counteroffer_action_schema_v1` has 20 episode keys over 4 distinct `cell_id` `[run]`). Incident rows attach by `family_id`, `case_id` and pack, not by word; this fixes identity only (see Section 6 for the row-kind, state and control-role rules). QC gates (`benchmark_qc.md` Gates 0-5, on main `[read]`) get a mechanical check script that reads the same block, limited to `derived` and `verified` facts. The Refund runner minting its own approval (RF-T-01) is a separate Refund item (Section 4).

**Corrections.** A sealed bundle is never edited. Errata live beside it as sealed records that select by manifest facts. On the #117 branch the selectors are `campaign_ids`, `run_plan_sha256s`, `receipt_sha256s` and `implementation_pins`, and `scan_bundles()` reads `receipts/projections.jsonl` (`errata.py:111-140, 487` on `origin/codex/evidence-errata-layer` `[read]`). It has no action-row selector, and one receipt can hold several actions. So the branch can flag the whole campaign of the 8 rows today. Selecting one episode needs the receipts published as a new sealed artifact; selecting one action row needs a new selector and an identity for an action row, which is new design, not part of #117. It needs its three review findings closed and a fresh PR.

**Generated, not hand-kept.** Evidence index, family README sections and the deploy allow-list are generated from the manifests, with a link-coverage test (EVID-O-02, P-T-12, SITE-O-02).

**Replaces.** Examiner key-scan heuristics, the sorting layer as the primary defence, the per-bundle manual relabelling, and ticket-by-ticket template edits.

**Alternatives considered.**

| Alternative | Why not recommended |
|---|---|
| Keep the heuristics and refine them (status quo, the sorting layer) | It lowered reviewer lines 670 to 58 but leaves the builder unchanged; new bundles still read "not stated" (#287, 2026-10-13) |
| A new standalone schema outside the manifest | A kernel manifest and builder already exist (`publication.py:172`); a second one splits the sealed identity |
| Rewrite old bundles | Contradicts sealed evidence and the QC standard's no-deletion rule |

## 3. Scope

In scope: clusters G01, G24, G25, G26; board items #287, #280; #265 (a, b), #135.f, #117 (revival), #279, #289.e, #290.f; rows SITE-O-01, SITE-O-02, EVID-O-02, DC-T-02, DC-T-16, P-T-12, RF-T-01, RF-D-06, N7, B04.

Out of scope:

| Item | Destination |
|---|---|
| Call-outcome typing, truncation handling at run time (G04, TB-D-03 code), retries, billing of calls | T1 |
| Sizing, admission statistics, falsification-arm statistical design (#288) | T5 |
| Construct validity of cases (DC-D-02/03 and similar design rows) | T6 |
| Portability of publication tests off a clean checkout beyond DC-T-02 | T7 |
| The Examiner's own code and display | Chenyu (owner); T4 only defines what it reads |

## 4. Already decided

| Decision | Label | Source |
|---|---|---|
| Truncation is typed `length`, never a scored answer (#152 option 1); an erratum record follows for published rows | `[owner]` 2026-09-10 | D-13, [rulings register](ledgers/rulings_register.md) |
| Completed non-truncated malformed output stays model behaviour | `[owner]` 2026-09-10 | D-12 |
| Kernel order #246 (merged), #291, #292, #293; #248 after part-1 repairs | `[owner]` 2026-10-21 | D-11 |
| QC standard (Gates 0-5, contribution admission) is on main | `[merged]` | `docs/operations/benchmark_qc.md` |
| Kernel lane needs one non-author approval on the head | `[merged]` | `docs/operations/pr_lanes.md:21` |
| #117 closed 2026-10-21; branch kept, resume by fresh PR | `[owner]` (per closing comment) | #117 |
| Contribution admission requires a human QC approval whose evidence and digest bind the exact contract (`benchmark_qc.md:503`) | `[merged]` | `docs/operations/benchmark_qc.md` |
| Refund runner stops minting the approval; reviewer-signed record binds the contract digest | `[record]`: proposed in #290, an owner-authored design hand-over for Refund V2.6 that says it is "not a request to change V2.5"; the cluster lists it as ruled, the register has no entry | #290 (the issue text (working note, unpublished)) |

Not decided: the manifest facts, the Examiner's source of truth, and the reading of legacy bundles.

## 5. Theme ruling requested

**Question.** Is the manifest `run_facts` block the single source for replay, cost, cell accounting, claim boundary and QC profile, so that the Examiner and the QC gates stop inferring them from reports for any bundle sealed after a cut-over date?

Sub-questions (independent; each has its own options below):

1. **Legacy bundles (135 discovered: 70 kernel-schema manifests, 29 family-schema manifests, 36 without a manifest).** How does the Examiner read them?
2. **Row correction.** How are the 8 truncated rows corrected?
3. **Cut-over.** From which kernel change does the builder refuse to seal without `run_facts`?

**Sub-question 1 options.**

| Option | Measured results | Frozen identities | Cost and work |
|---|---|---|---|
| A. Facts block required for new bundles; all legacy bundles shown as "predates 0.2"; Examiner heuristics removed | No score changes. Old bundles show unknown for 5 checks (about 407 lines turn into one honest label) | Sealed bundles untouched. New manifests carry facts, so their `manifest_sha256` differs from what 0.1 would give (`publication.py:427`); pack and case identities are not changed by facts. Plans created after the builder change pin new shared-runner bytes where a family pins them (e.g. `continuous_recovery.py:53-58` pins every `shared_runner/*.py`); sealed plans keep their old pins | Kernel change to the builder, Examiner change by Chenyu. Smallest. |
| B. A plus a separately sealed, `derived`-tier facts file for legacy bundles that have a manifest | Same scores; Examiner can show cells and artifact digests for old runs | Bundles untouched; the file is a new sealed artifact whose derivation must be stated and which binds the bundle by `manifest_sha256` | 99 bundles with manifests; the 29 family-schema ones need per-schema readers. The 36 without a manifest have no sealed identity to bind, so they need a bundle-identity rule first (not proposed here). Risk that a derived fact is read as recorded |
| C. Keep inference, fix per ticket | No change | None | Recurring: the template and Examiner edited for each check; 407 lines stay |

**Sub-question 2 options (the 8 rows).**

| Option | Effect | Cost and work |
|---|---|---|
| 2a. Campaign-level erratum now, naming the two bundles and the 8 rows in its description | Every row of both campaigns is flagged, including rows that were not truncated; no reader cites the 8 as model behaviour | Needs the errata layer (revived #117); no new selector |
| 2b. Wait for receipts, then an episode-level erratum | Names the affected episodes by receipt digest | Needs the receipts of these runs published as a new sealed artifact (not checked that they exist); until then the 8 stay uncorrected |
| 2c. 2b plus an action-row selector | Names the 8 rows exactly | New selector and row identity design on top of #117; kernel lane |

**Sub-question 3 options.**

| Option | Effect |
|---|---|
| 3a. First kernel PR after #293 that touches `publication.py` | Stays inside the owner's order (D-11) |
| 3b. A date or a manifest version bump agreed by the owner, independent of PR order | Clear for publishers; must still land after #293 in kernel order |

**Recommendation (not a ruling).** Sub-question 1: A for the cut-over; B only for the two facts that can be recomputed exactly from published bytes (cell counts and artifact digests), and only for bundles that have a manifest. Replay, cost qualifier and claim boundary stay "predates 0.2" for all legacy bundles, and the 36 manifest-less bundles stay "no manifest" until an identity rule exists. Recomputed counts add no judgment; the others would restate a publisher's claim, which is the inference the theme exists to remove. Sub-question 2: 2a now, 2b or 2c later if the owner wants row precision. Sub-question 3: 3a, so it does not cut across the owner's order.

## 6. Issue-level decisions that follow

| Question | Decider | Blocks | Issue |
|---|---|---|---|
| Revive the errata layer: fresh PR from `codex/evidence-errata-layer` after the three review findings; add `family_id` once 0.2 exists | Chenyu (approval); Zeyu (implementation) | #265.a, #135.f, any correction | #265 exists; PR to open |
| PR #259: flag the four bundles as predating the ruling, erratum-select them, or hold the PR | Chenyu | #265.b | #265, #259 exist |
| N7 scope: aggregate count balance versus per-cell identity coverage | Chenyu | G24 builder rules | none yet |
| Examiner rule changes after A: cells computed, claims from block (declared tier labelled), attach by family and pack | Chenyu | #287.b, .c, N7 | #287 exists |
| Incident-row applicability (operational rows attach only to the run they name; design rows inherit by environment), explicit disposition state instead of first word, declared control role instead of a `scripted_` name. These need data in the incident log and profiles, not manifest facts (`build_general_examiner.py:338, 579`) | Chenyu | #287.a, .d, .e, DC-T-16 | #287 exists |
| SITE-O-01: regenerate the site CSV from re-runs or label it a pre-correction snapshot | Chenyu | the site numbers | row only |
| SITE-O-02: do the six unreleased runs stay public; deploy allow-list | Chenyu | deploy script | row only |
| DC-T-02: commit the v12 bundle or delete the publisher and tests | Chenyu | clean-checkout verification | row only |
| QC profile for Refund, GovSim, EconEvals | Chenyu and family owners | `qc_profile` check | #287.f |
| Known-bad inputs and recorded mutation kills per family (table in each `qc.md`); falsification arm beyond procurement | Chenyu (#280, #279) | G26 | #280, #279 exist |
| Whether and in which Refund version (V2.6 per #290) the runner stops minting the QC approval and a reviewer-signed record binds the contract digest; whether admission checks delivered schemas | Yuchen, with Chenyu | RF-T-01, #289.e | #290.f, #289 exist |
| Close stale blockers: benchmark_qc.md is on main | Zeyu to correct cluster text | G26 wording | none |

## 7. Delivery

| Step | Owner | Lane | Depends on | Start now |
|---|---|---|---|---|
| 1. Rule the Section 5 question | Chenyu | none | none | Yes |
| 2. Draft manifest 0.2 `run_facts` schema and a fixture bundle; probe it on 5 existing bundles without sealing | Zeyu | family (draft, no merge) | 1 for the final shape | Yes, draft |
| 3. Builder change: compute `run_facts` in `seal_publication_manifest`, refuse without it, adapt `rebuild_publication_manifest` for 0.1 and 0.2 | Zeyu | kernel; non-author approval; after #293 per the owner's order | 1, 2 | After #293 |
| 4. Family publishers pass facts to the builder; start with procurement and datacenter | Zeyu with family owners | family | 3 | After 3 |
| 5. Revive errata PR, fix the three findings, add fixture erratum matching a moved bundle | Zeyu | kernel (`cli.py`, `analysis`) | 1; after step 3 if `family_id` is included | Findings can be fixed now |
| 6. Erratum for the 8 rows per the Section 5 sub-question 2 ruling; flag for #259 | Zeyu drafts; Chenyu approves | evidence | 5 | After 5 |
| 7. Examiner reads `run_facts`; cells computed on slots; claims labelled by tier; attach by family and pack; "predates 0.2" and "no manifest" labels. Closes #287.b, .c and N7 only | Chenyu | Examiner repo | 2 (schema), 3 | Schema review can start |
| 7b. Incident applicability, disposition state and control role as declared data (Section 6) | Chenyu | Examiner repo and incident log | none on the kernel | Yes, after the owner chooses the form |
| 8. QC gate check script reading the block; per-family mutation-kill tables | Chenyu and family owners | SOP and tooling | 3 | #280 tables can start now |
| 9. Generate evidence index and deploy allow-list from manifests, with link-coverage test | Zeyu | tooling | 3 | After 3 |

Nothing here edits `evidence/**`. Steps 2 and 8 (tables) need no kernel change and can start immediately.

## 8. Not verified

- The Examiner's 670 lines were not recomputed, and its 144 bundles differ from the 135 that `discover()` finds on main at `1e2ae367` (different base, not reconciled); counts come from the triage summary and issue comments (407 versus the 395 in the theme assignment note (working note, unpublished) is unresolved).
- The Examiner was read through a copy outside this repository (a454dc47), not its current head.
- That the 8 rows would have parsed was not tested; the ruling rests on the signature.
- Rows SITE-O-01/02, DC-T-16, P-T-12, RF-T-01 and RF-D-06 are not on main and were not checked on their branches.
- Whether #291-#293 or #248 touch `publication.py` was not checked, so the cut-over timing in Section 5 is stated relative to the owner's order, not to file overlap.
- Whether receipts for the 8 rows exist and can be published was not checked; the action-row selector is not designed.
- The trust tier of each fact is a proposal; which families can run `verify_bundle_replay` on their published bundles was not checked.
- The `run_facts` contents are a proposal; their computability from receipts for every family was probed on none.
