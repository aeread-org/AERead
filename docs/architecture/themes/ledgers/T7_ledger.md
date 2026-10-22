# T7 Other: evidence ledger

**Evidence ledger for [T7](../T7_other.md).** Line references are at main 1e2ae367 unless a row says otherwise.

Source tree: `origin/main` `1e2ae367` Paths below are relative to the repository root. Cluster ids (G01..G36) refer to the root-cause clustering summarised in the [themes README](../README.md). Labels: `[read]` read at source, `[run]` reproduced in memory, `[row]` taken from an incident row, record or issue text. Threads fetched with `gh` on 2026-10-21 (read only).

## A. Verdict on the shared root cause

No shared root cause exists. The brief's items fall into seven unrelated kinds (governance, test-environment portability, training-integration docs, a diagnostic counter, run-tracking umbrellas, a kernel-contract ruling, a research RFC) plus one item that is not in this repository (case-consultant). They have different owners, lanes and blockers; fixing one changes none of the others. The only property they share is that none of them changes a measured number today. T7 is therefore a disposition list, not a design theme. `[read]` for each mechanism below; the negative finding itself is a judgment.

## B. Evidence ledger

| # | Claim | Source | Label |
|---|---|---|---|
| 1 | `harness_claim_unreconciled` is appended, never raised, when `claimed != port.tool_calls_dispatched`; comment says a mismatch "is recorded, never raised". | `src/aeread/shared_runner/model_call/harness.py:1236-1250` | read |
| 2 | `tool_calls_dispatched` increments only in the native-provider path (`+= len(tool_calls)` in the model-turn builder). | `harness.py:253`, `:447` | read |
| 3 | A second per-invocation record exists: the tools port keeps `invocation_ids`, appended per dispatched invocation, and the executor already reads it for the attempt. | `harness.py:490`, `:571`, `:1259` | read |
| 4 | #128 reports all 100 periods of every econevals receipt carry `claimed 2, recorded 0`; govsim carries none because it declares no tools. Issue has 0 comments, no assignee, updated 2026-09-06. | `gh issue view 128`; record #128 | row |
| 5 | #128 was moved out of cluster G07 (T1 lifecycle) to a P3 diagnostic: the event never raises. The move is a `[record]` classification, not a ruling. | the review dispositions note (working note, unpublished) row 6; [T1 design](../T1_call_outcome_design.md) ("outside the contract: a diagnostic") | read |
| 6 | `OpenRouterChatClient` raises `provider_contract` "OpenRouter diagnostic runs require a declared seed" with `retryable=False` when `request.seed is None`. | `src/aeread/shared_runner/task/execution.py:2135-2140` (class at `:1743`) | read |
| 7 | `seed_unsupported` appears nowhere in `src`, `docs`, `tests`, `configs`, `cases` at `1e2ae367`. Option 2 of #172 is not implemented. | `grep -rIn seed_unsupported` | run |
| 8 | A per-profile request seed can be derived (`paired_cell_v1`, needs non-negative `request_seed_base`); that is the existing way a seed is declared. | `execution.py:4570-4580`, `:4654-4676` | read |
| 9 | #172: Claude Opus 4.6/4.7 has 0 seed-capable OpenRouter endpoints; GovSim usable rows are OpenAI only; EconEvals only GPT-4o. Author proposes option 2 and says it "is a kernel contract change and therefore a ruling". Status Needs decision, waiting on Chenyu; 0 comments. | `gh issue view 172` | row |
| 10 | Kernel lane = `src/aeread/shared_runner/**`, `src/aeread/cli.py`, `conftest.py`, `tests/conftest.py`; gate is CI plus one non-author approval on the current head. | `docs/operations/pr_lanes.md` section 1 | read |
| 11 | `enforce_admins` is off; an admin merge past red `kernel-review` "is an incident-log row, not a shortcut: record why, and what verification replaced the review". | `docs/operations/pr_lanes.md:156-159` | read |
| 12 | RN-O-01 (#232-#239), RN-O-03 (#294), RN-O-04 (termsbench row) are all recorded as owner-directed admin merges; reverts are one line in `registry.py` plus two registration rows. | `docs/operations/incident_log.md:678`, `:684`, `:685` | read |
| 13 | RN-T-05: the `kernel-review` gate could not pass on any kernel PR from 5252fff8 (2026-09-11) because `gh api --slurp` with `--jq` is rejected; fixed. So for part of the period an approval would not have turned the check green. | `incident_log.md:687` | read |
| 14 | #266 lists the eight PRs as an unchecked list; closes "when all eight have been read"; labels `lane:kernel`, `area:runner`; board: Blocked by "non-author kernel reviewer", P2. #266 does not list #294 or the termsbench row. | `gh issue view 266` | row |
| 15 | `conftest.py:8-10` inserts `src` on `sys.path` for the pytest process only. | `conftest.py:8-10` | read |
| 16 | Three tests spawn `python -m aeread_families...` with no `PYTHONPATH`: `tests/test_datacenter_stack.py:425`, `tests/test_datacenter_world_campaign.py:84`, `tests/test_datacenter_development_terms.py:355` (the last passes `cwd=ROOT`, which does not put `src/` on the path). #165 names two; the third (world campaign) has the same shape. | those lines | read |
| 17 | Child import fails without the shim: with no `PYTHONPATH` and no install, `python -m aeread_families.datacenter_development.stack_campaign --help` gives `ModuleNotFoundError: No module named 'aeread_families'`; with `PYTHONPATH=src` it prints usage. | in-memory probe, py3.12 venv | run |
| 18 | CI installs with `pip install -e '.[dev]'`, which is why CI does not see #165. | `.github/workflows/ci.yml:20,64,112,184` | read |
| 19 | `_NEIGHBOURING_ROOT`/`DOCUMENTED_SIBLING_CHECKOUT` is computed at import by `_ancestor_named(REPO_ROOT, "AERead")`, which raises `AssertionError` when no ancestor has that name. | `tests/test_negarena_provisioning.py:46-72` | read |
| 20 | #268 and RN-T-01 both report this failure in worktrees not under a directory named `AERead`; RN-T-01's workaround was to sit the worktree under `AERead`. | record #268; `incident_log.md` RN-T-01 | row |
| 21 | P-T-18: committed `pay_or_test_v2` pack world 21 `two_step_value` 0.17 committed vs 0.16 on Python 3.10; cause given as 3.12 compensated `sum()`; fix `math.fsum` plus new pack id; "shows 0.17 vs 0.16 diagnostic only"; the committed pack is named by the confirmatory plan. | record P-T-18; cluster G28 | row |
| 22 | `fsum` is not used in `src/aeread_families/procurement_allocation/*.py` (so the reference still uses `sum()`). | grep | run |
| 23 | rLLM integration code exists at `src/aeread/integrations/rllm_flow.py`, `rllm_eval.py`; docs at `integrations/rllm/README.md`, `HANDOVER.md`. Neither documents the verl flash-attn recipe, the loop-bound config location, or the gateway-session requirement for `aeread_flow.run()`. | file listing; grep for `total_training_steps`, `flash_attn`, `verl` in `integrations/rllm` | read |
| 24 | `FlowTelemetry`, `get_flow_telemetry`, `_FLOW_TELEMETRY`, `CandidateTraceMismatch` do not occur anywhere in the tree at `1e2ae367`. The #4.b and #4.c mechanisms cannot be checked at main; they describe a branch or external rLLM code. | `grep -rIn` over `.` excluding `evidence/`, `runs/` | run |
| 25 | #4: Chenyu's 2026-08-09 comment gives a working recipe (CUDA 13 devel base, clang, source-built flash-attn 2.8.3, tensordict 0.10.0), says the step runs, confirms telemetry blind under real training, and says findings 2 and 4 stand. Issue still open, 1 comment, no assignee. Board Theme for #4 is T5, not T7. | `gh issue view 4`; the board export (working note, unpublished) | row |
| 26 | #89: tau3 proof evidence is in open PR #97 (last updated 2026-09-10, reopened by Yuchen for "trajectory/contract work"). Chenyu accepted the Arena glm-5p2 route "for the pipeline proof only". | `gh issue view 89`; `gh pr view 97` | row |
| 27 | #93: Chenyu's two prerequisites: #101 (cleared, merged `d89da44`) and a live-panel driver. Evidence in open PR #132 (last updated 2026-09-11, "conflicts with main, failing CI" per Yuchen 2026-09-08). Failures split to #135 (T1). | `gh issue view 93`; `gh pr view 132` | row |
| 28 | #90: no comment beyond creation (2026-09-05), assignee Chenyu, board "Paid run approval". | `gh issue view 90` | row |
| 29 | #39 holds the ruled matrix (tau3, EconEvals, GovSim, TERMS-Bench); route "pinned OpenRouter GLM 5.3 Flash/Parasail" for items 2-4; cheap smoke with one illegal action before gate-4. Board Theme for #39 is T3. | `gh issue view 39` (Chenyu ruling comment) | row |
| 30 | #140 RFC lists five owner questions; Chenyu has not replied (1 comment, by the author). Question 5 ("should PR #72 be refreshed") is stale: PR #72 merged 2026-09-09T07:34:44Z. | `gh issue view 140`; `gh pr view 72` | read |
| 31 | Case-consultant (CC-D-06, CC-T-04) is absent from `main`: no `src/aeread_families/*consult*`, no `case_consultant` or `daily-js` text outside excluded dirs. Records are marked "only on non-PR branch(es): lower confidence". | `ls`, `grep -rIl` | run |
| 32 | The provider-failure census concatenates logs per root without deduplicating by log identity: `for root in runs for log in _attempt_logs(root)`. Overlapping explicit roots would walk the same `events.jsonl` twice. Not reproduced. | `src/aeread/shared_runner/run/provider_failures.py:436-446` | read |
| 33 | CENSUS-OVERLAP source found: `handoff_runner_2026-10-18/reports/REVIEW_246_RESIDUALS.md:8-14` records an independent reproduction (parent and child roots: one failure counted twice), no publication impact shown, and the constraint not to merge distinct directories on equal local IDs. No issue exists. Not re-run here. | that file; the clustering notes (working note, unpublished) | read |
| 34 | Execution identity: Refund pins the bytes of `execution.py` as harness and runtime pins, so any edit moves `run_plan_id`; `design_plan_sha256` strips the `implementation:` pins and is stable. | `src/aeread_families/refund/runner.py:1230-1244`; `run/resolver.py:721-748` | read |
| 35 | Seed on the wire: paired-cell seed, else `sampling.seed` (`execution.py:3166-3168`); both OpenRouter paths send `seed` unconditionally (`:1826`, `:1953`) with `require_parameters=True` (`:2145`). | those lines | read |
| 36 | #172 coverage: TERMS-Bench also has GLM-5.1 via DeepInfra fp4; EconEvals' other two models have no live endpoints (deprecation); an endpoint snapshot of the issue date. | the issue text (working note, unpublished) | row |
| 37 | #268: PR #132 already holds a collection fallback and a provisioning fallback; renamed checkout 5 passed, external linked worktree 2 failed (test expects worktree sibling, script resolves main repo sibling). | `handoff_runner_2026-10-18/reports/PR_ISSUE_MATRIX.md:16`; `pr132-268-coverage.json` | read |
| 38 | CC-D-06 and CC-T-04 list `origin/codex/case-consultant` as source, disposition open. | the incident records (working note, unpublished) | read |
| 39 | PR #97 updated 2026-09-10, DIRTY; PR #132 updated 2026-09-11, CLEAN; both OPEN (2026-10-21). | `gh pr view` | read |

## C. Member list

Brief says 9 board items carry "T7 Other"; the board export (working note, unpublished) confirms exactly: #268, #266, #172, #165, #140, #128, #93, #90, #89.

| Member | What it is | State | Owner | Still true at 1e2ae367 |
|---|---|---|---|---|
| G27 #266 | Post-merge read of eight #226 kernel PRs | open, P2, kernel | Chenyu (record); blocked on a non-author reviewer | yes; rows 11-14 |
| G27 RN-O-01 | same eight PRs, incident row | open row | same | yes |
| G27 RN-O-03 | #294 trusted-plugin row override | open row; not in #266 | Chenyu | yes (`incident_log.md:684`) |
| G27 RN-O-04 | termsbench 0.2.0 trusted-plugin row override | open row; not in #266; PR number not recorded | Chenyu | yes (`:685`) |
| G28 #165 | datacenter subprocess tests need editable install | open, P3, family | Zeyu (record) | yes, and three tests not two |
| G28 #268 | negarena tests need a dir named `AERead` | open, P3, family; partly fixed in PR #132 (row 37) | Yuchen (record) | yes on main (row 19) |
| G28 P-T-18 | pack not byte-reproducible on py3.10 | open row, no issue | needs Chenyu (new pack id) | not rechecked; `fsum` absent |
| G28 B10, N5, B19, B20 | secondary items (B10/N5: same interpreter-unstable pack; B19/B20 not in records) | secondary | - | not verifiable, not in records |
| G29 #4.a, #4.b, #4.d | verl install, gateway-session seam, loop bound docs | issue #4 open; board Theme T5 | Chenyu (record) | docs gap yes; code mechanisms not at main (row 24) |
| G30 #4.c | FlowTelemetry blind across Ray actor | same issue | Chenyu | not checkable at main |
| G31 #39.b | paid matrix umbrella | open; board Theme T3 | Yuchen, Chenyu | umbrella only |
| G31 #89, #90, #93 | campaign tracking issues | open, P3, family, Kind Tracking | Yuchen / Chenyu / Yuchen | yes; PRs #97 and #132 still open |
| G33 #172 | declared-seed requirement | open, P2, Needs decision | Chenyu | yes (rows 6-7) |
| G34 #140 | trajectory-diagnostics RFC | open, P3, Needs decision | Chenyu rules; Zeyu authored | yes; question 5 stale |
| G35 CC-D-06, CC-T-04 | case-consultant app prompt rule and dependency pin | incident rows, no issue; source `origin/codex/case-consultant`, disposition open | none | not on `main` (row 31); off-scope, branch-only, unconfirmed (row 38) |
| G36 CENSUS-OVERLAP | census double counts overlapping roots | secondary only, no issue | none | yes by code and on record (rows 32, 33) |
| #128 | claimed-tool counter wrong denominator | open, P3, kernel | none assigned | yes (rows 1-4) |

## D. Rulings in force

- Maintainer ruling on #89, `[owner]`: Arena glm-5p2 acceptable for the tau3 pipeline proof only; matrix runs (#90-#92) stay on the pinned OpenRouter route. Source: #89 comment by LEE-CHENYU.
- Paid experiment matrix, `[owner]` 2026-09-06: tau3, EconEvals, GovSim, TERMS-Bench; smoke with one illegal action before gate-4. Source: #39 comment.
- Kernel landing order, `[owner]` 2026-10-21: #246, #291, #292, #293; #248 after part 1 ([rulings register](rulings_register.md) D-11). Any #128 fix is kernel lane and must not be stacked ahead of it.
- Override of `kernel-review` on #232-#239, #294, termsbench row, `[record]`: the rows say the owner directed the merges, but the register holds no ruling; not a standing rule. `pr_lanes.md` section 6 only says an override is an incident-log row.
- "Do not fold the seed into the episode identity; name the unique key instead" (DC-T-04), `[on behalf]` per RN-O-01 row (`incident_log.md:678`). Relevant to any `seed_unsupported` design.
- No ruling exists on `seed_unsupported`, #140's five questions, or a standing reviewer rule.

## E. Open questions

1. #172: option 1 / 2 / 3 (Chenyu).
2. G27: assign a non-author kernel reviewer, or record a standing override rule (Chenyu).
3. #140: five owner questions (Chenyu); question 5 is moot.
4. P-T-18: new pack identity (Chenyu), since the committed pack is named by the confirmatory plan.
5. #128: which denominator (invocation ids from the tools port, or suppress for JSON-dialect harnesses). No one has proposed it in the thread.
6. Umbrellas: close on PR merge, or on paid-run report; PRs #97 and #132 last updated 2026-09-10 and 09-11 (row 39).
7. #268: which sibling root is canonical (row 37).
8. #172: behaviour of a seed exception (rows 34, 35).

## F. Conflicts between sources

- Board Theme vs brief: #4 is T5 on the board and #39 is T3, but the brief lists G29/G30/G31 here. This ledger gives them dispositions and flags the board assignment.
- #165 text says two tests; main has three with the same shape.
- #140 question 5 (refresh PR #72) predates PR #72's merge on 2026-09-09; the issue body was written the same week.
- Cluster G33 lists #172 as secondary in G09 (T3 identity); the board puts it in T7. Kept here because the open item is a kernel contract ruling.
- #4.b / #4.c mechanisms (`CandidateTraceMismatch`, `_FLOW_TELEMETRY`) are not in the main tree; the clusters mark them unchecked.
- Cluster G07 (T1) originally held #128; moved out by review disposition 6.
