# T7: Other (no shared root cause; disposition list)

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5 and is decided in [issue #322](https://github.com/aeread-org/AERead/issues/322); a ruling is recorded here with its date and source.

**Summary.** T7 holds items that are not defects in a measured number and share no root cause: a review-gate override pattern, test-environment assumptions, training-integration docs, one diagnostic counter, run-tracking umbrellas, a seed-requirement rule, and a research RFC. The direction is not a redesign. It is a disposition policy: every item gets one owner and one next step, nothing here is scheduled ahead of the T1 and T2 kernel work, and the items that need an owner ruling are listed once so they can be answered together. The ruling requested: confirm the dispositions in section 2, and rule on #172 (the declared-seed requirement) and on the reviewer rule for kernel PRs.

## 1. Problem and root cause

Test for a shared root cause: the items were checked against the source at `1e2ae367` one by one. They fail in different layers (CI policy, test code, docs, a kernel event, issue tracking, a client contract, a research plan), have different owners and none depends on another. No single change fixes two of them. T7 is therefore a bucket, and this charter does not invent a theme for it. `[read]` ([ledger](ledgers/T7_ledger.md), section A).

What they do share is that none changes a published score today, which is why they sit below T1 to T6.

| Symptom | Where it shows | Evidence |
|---|---|---|
| Kernel PRs merged past a red `kernel-review` | #266 (eight PRs #232-#239), incident rows RN-O-01, RN-O-03 (#294), RN-O-04 (termsbench row) | `docs/operations/incident_log.md:678,684,685`; `docs/operations/pr_lanes.md:156-159` `[read]` |
| `harness_claim_unreconciled` on all 100 periods of every econevals receipt | #128 | `model_call/harness.py:1236-1250` compares against the native counter set at `:447`; the tools port keeps its own `invocation_ids` (`:490,:571`) `[read]` |
| Tests fail outside CI's editable install or outside a directory named `AERead` | #165, #268, P-T-18 | `conftest.py:8-10`; `tests/test_negarena_provisioning.py:46-72`; child import failure reproduced `[read][run]` |
| Reproduction check limited to models with seed support | #172 | `task/execution.py:2135-2140`; `seed_unsupported` absent from the tree `[read][run]` |
| Tracking issues stay open while their PRs sit idle | #89, #90, #93, #39.b | PRs #97 and #132 last updated 2026-09-10 and 09-11 `[row]` |
| Training-integration pitfalls not in the README | #4.a, #4.b, #4.d (and #4.c) | `integrations/rllm/README.md`, `HANDOVER.md` do not cover them `[read]` |
| RFC awaiting owner scope | #140 | one comment, no reply `[row]` |
| App issues in another codebase | CC-D-06, CC-T-04 | absent from `main` `[run]` |

## 2. Direction

The direction is the disposition policy for the bucket. Rules, then the per-item table.

1. **One owner and one next step per item.** An item stays in T7 only while no other theme owns its mechanism.
2. **No T7 work is scheduled ahead of the kernel landing order** #246, #291, #292, #293, then #248 after part 1. Kernel-lane T7 items (#128, #172, any registry change) wait their turn and are not stacked on those PRs.
3. **Tracking umbrellas are not defects.** They close on the evidence they name (a merged PR and a reported run), not on a code change.
4. **Process findings are recorded once.** Overrides of the kernel gate stay incident-log rows; the standing question is asked in section 5.
5. **Items outside the benchmark's scope keep their provenance** and are handed over only once a destination is confirmed.
6. **Nothing here needs a new convention.** Where a choice is open it is in section 5 or 6.

### Disposition per item

Priority is the current board value unless noted. "Close candidate" means close once the stated evidence exists; nothing is proposed for closing today.

| Item | Disposition | Owner | Priority | Close candidate / destination |
|---|---|---|---|---|
| #266, RN-O-01 | Keep. Read the eight PRs after a non-author reviewer exists. Extend the existing checklist to #294 and the termsbench row (RN-O-03, RN-O-04). | Chenyu names reviewer; reviewer reads | P2 | Closes when all rows are read (the issue's own condition) |
| RN-O-03, RN-O-04 | Fold into #266 (edit the existing issue; the termsbench PR number is not recorded in the row and must be added) | Zeyu | P2 | Same as #266 |
| #128 | Keep as a small kernel item. Compare against the tools-port invocation count for JSON-dialect harnesses, or skip the check for them (open choice, section 6). The event never aborts an episode, so no measurement is affected. | Zeyu (kernel) after #248 | P3 | Closes with that PR; also check tau3 receipts for the same marker |
| #165 | Fix: pass `PYTHONPATH` (the repo `src`) in the child environment. Three tests, not two (`test_datacenter_stack.py:425`, `test_datacenter_world_campaign.py:84`, `test_datacenter_development_terms.py:355`). | Zeyu, family/test lane | P3 | Closes with the PR |
| #268 | Not a fresh fix. PR #132 already carries a collection fallback and a Git-common-dir fallback in `provision.sh`; its own comparison shows 5 passed in a renamed checkout but 2 failed in an external linked worktree, because the test expects the worktree's sibling and the script resolves the main repository's sibling (`handoff_runner_2026-10-18/reports/PR_ISSUE_MATRIX.md:16`, `pr132-268-coverage.json`) `[read]`. First agree the canonical sibling root (section 6, item 7), then fix test and script together and verify in both layouts. | Yuchen (per record), with Zeyu; family lane | P3 | Closes with that PR |
| P-T-18 | Needs a ruling before any code: `math.fsum` changes the pack and the committed pack is the one the confirmatory plan names. Diagnostic only (0.17 vs 0.16). Until ruled, document the supported interpreter. | Chenyu (identity), Zeyu | P3 | No issue exists; open one only if the owner wants the change |
| #172 | Needs ruling (section 5, Q1). | Chenyu | P2 | Closes when the ruling is recorded and, for option 2, the kernel PR lands |
| #140 | Keep parked. Five owner questions are open; question 5 is moot because PR #72 merged on 2026-09-09. No implementation before scope approval. | Chenyu (scope), Zeyu (author) | P3 | None; research item, not a defect |
| #89 | Keep as tracking. Closes when PR #97 is approved and merged, as Yuchen's reopening note says. PR #97 was last updated 2026-09-10 and is DIRTY; PR #132 on 2026-09-11, CLEAN (`gh pr view`, 2026-10-21) `[read]`. | Yuchen | P3 | After PR #97 merge |
| #93 | Keep as tracking. Closes after the PR #132 successor campaigns are corrected and merged; failures live in #135 (T1). | Yuchen | P3 | After PR #132 successor merges |
| #90 | Keep as tracking. Paid run needs owner approval; no activity since creation. | Chenyu | P3 | After the EconEvals campaign is reported |
| #39.b | Not T7 on the board (T3). Tracking only. | Yuchen, Chenyu | P3 | Board theme T3 |
| #4.a, #4.b, #4.d | One README section for the rLLM/verl recipe, the gateway-session requirement, and the `rllm.trainer.*` loop bounds. Board puts #4 in T5. | Zeyu, docs | P3 | Close candidate once the section merges (Chenyu already unblocked the run on 2026-08-09) |
| #4.c | Telemetry blind across the Ray actor boundary. The code is not on `main`, so it cannot be checked or fixed here. Needs the branch that holds it. | Chenyu | P3 | Not closable until located |
| CC-D-06, CC-T-04 | Outside the benchmark's scope and not on `main`. Both rows name `origin/codex/case-consultant` as their source and are recorded as open (the incident records (working note, unpublished)) `[read]`; the branch was not inspected. Keep the rows with that provenance, status "off-scope, branch-only, unconfirmed"; hand over to the app's tracker only once its destination is confirmed. | Chenyu confirms destination | n/a | Hand over after confirmation; do not delete from the audit record |
| CENSUS-OVERLAP | Deduplicate repeated encounters of the same physical event log in the census (`provider_failures.py:436-446`). The residual record (`handoff_runner_2026-10-18/reports/REVIEW_246_RESIDUALS.md:8-14`) reports an independent reproduction (parent and child roots both supplied: one transport failure counted twice) and no historical publication impact `[read]`; I did not re-run it. Constraint from that record: distinct run directories must not be merged on equal local IDs alone; test repeated paths, symlinks and genuinely separate roots first. No issue exists. | Zeyu, kernel tooling | P3 | Open an issue when the owner wants it; reproduction is on record |

**What this replaces.** Today these items sit among the P1 and P2 work and some carry an implied "fix soon" they do not have. **Alternatives considered.** (a) Distribute each item to T1 to T6: rejected for #128 (T1 already excluded it by review disposition 6), #165, #268 and the umbrellas, which fit no theme's mechanism. (b) Build a "hygiene" design (a CI profile that always runs tests in a fresh checkout path and interpreter): attractive but it would be a new convention and is not needed for two P3 test fixes; revisit if a third portability item appears. (c) Close the umbrellas now: rejected, their PRs are open and Yuchen reopened them on purpose.

## 3. Scope

In scope: clusters G27, G28, G29, G30, G31, G33, G34, G35, G36; #128; the nine board items with Theme "T7 Other" (#268, #266, #172, #165, #140, #128, #93, #90, #89).

Out of scope, with destination:
- #4.e (zero-gradient micro-GRPO step, per-case base rate): T5 (board Theme for #4).
- #39 as a whole (matrix, receipts), and the call-level failures behind #93 (#135): T3 and T1 respectively.
- #130 (billed-input divergence, cluster G32): T1.
- Call-outcome typing, billing, retries inside an attempt, terminal writers, tool-dispatch dispositions (#102): T1.
- Campaign launch gates (#292): T2.
- Which seed a paired cell declares, if the owner wants it folded into identity: T3 (identity), noting DC-T-04.

## 4. Already decided

- Kernel landing order `[owner]` 2026-10-21: #246, #291, #292, #293; #248 after its part-1 repairs ([rulings register](ledgers/rulings_register.md) D-11).
- Paid experiment matrix and its pre-gate smoke `[owner]` 2026-09-06 (#39 comment).
- Arena glm-5p2 only for the tau3 pipeline proof `[owner]` (#89 comment).
- Kernel lane requires a non-author approval; an admin override is an incident-log row `[merged]` (the gate rule itself) (`docs/operations/pr_lanes.md:156-159`).
- The overrides on #232-#239, #294 and the termsbench row were directed by the owner and recorded as incident rows `[record]` (`incident_log.md:678,684,685`). That is a record of a decision, not a standing rule.
- "Do not fold the seed into the episode identity; name the unique key instead" (DC-T-04) `[on behalf]`, per `incident_log.md:678`. Any `seed_unsupported` design must keep this.
- #128's event is appended and never raised (`harness.py:1236-1250`) `[read]`. Moving it out of T1 was a classification adjustment in the issue taxonomy `[record]`, not a ruling.
- No ruling exists on `seed_unsupported`, on #140's five questions, or on a standing reviewer rule.

## 5. Theme ruling requested

**Question.** Confirm the section 2 dispositions (T7 is a disposition list with no redesign, and nothing here jumps the kernel landing order), and rule on the two items that need the owner.

**Q1. #172: the declared-seed requirement.** `OpenRouterChatClient` refuses an undeclared seed (`execution.py:2135-2140`) `[read]`. Coverage as the issue author measured it, an endpoint snapshot of the issue date `[row]` (the issue text (working note, unpublished)):

| Family | Usable under the rule | Excluded, and why |
|---|---|---|
| TERMS-Bench | GPT-4o-mini; GLM-5.1 via DeepInfra at fp4 only | Claude Opus 4.6/4.7 (its best agent): 0 seed-capable endpoints |
| GovSim | OpenAI models only | Every Anthropic and open-weight model: no seed-capable endpoint |
| EconEvals | GPT-4o only | The other two models list no live endpoints at all: deprecation, not the seed rule. A seed exception cannot restore them |

How a seed is chosen today: the paired-cell seed wins, else `sampling.seed` (`execution.py:3166-3168`); both OpenRouter paths always send `seed` on the wire (`:1826`, `:1953`) and set `require_parameters=True` (`:2145`) `[read]`. So "allow an undeclared seed" is not yet a defined behaviour.

*Q1a. Keep the rule or add an exception?*

| Option | What changes | Effect on results and identities | Cost and work |
|---|---|---|---|
| 1. Keep the rule | Nothing; published comparisons state they cover only the rows the rule admits (OpenAI rows, plus GLM-5.1 at fp4 for TERMS-Bench) | None | None |
| 2. Sealed `seed_unsupported` condition | A profile declares in its sealed config that its route takes no seed; the receipt records it; re-runs are reproducible in distribution only | Three identity layers. Historical sealed artifacts: unchanged. Design identity (`design_plan_sha256`): unchanged by a kernel edit, changes only for profiles that declare the new field. Execution identity (`run_plan_id`): for families that pin `execution.py` bytes as harness and runtime pins (Refund: `refund/runner.py:1230-1244`), any edit to `execution.py` moves `run_plan_id` of every regenerated plan, declared or not; confirmed in memory with identical profiles `[read][run]`. If regenerated plans must keep their ids, that is a T3 dependency | One kernel PR (client, profile schema, receipt field, tests), after #293 and #248 |
| 3. Per-family exemption | A family waives the rule | Same weakening, less visible in the receipt | Smaller code, worse audit trail |

*Q1b. Only if option 2 or 3: what the exception does.* Independent of Q1a.

| Option | Behaviour | Consequence |
|---|---|---|
| A. Reject the combination | A profile with `seed_unsupported` may not also set `sampling.seed` or `request_seed_source=paired_cell_v1`; the seed is omitted from the wire request | Clear semantics; world pairing then rests on world seeds alone and no request-level pairing exists; DC-T-04 untouched |
| B. Override | The declared seed is kept in the plan for pairing and the request hash but dropped from the wire request | Keeps pairing and hashes; the hashed request no longer equals what was sent, which weakens the audit trail |

Not yet decided in either case: whether `require_parameters=True` stays (it filters endpoints by supported parameters).

Recommendation (a recommendation, not a ruling): Q1a option 2, scheduled after the landing order, with option 1 wording in any comparison published meanwhile; Q1b option A, the simpler contract. Option 3 is not recommended; the issue author reaches the same view.

**Q2. Reviewer rule for kernel PRs (G27).** The gate requires a non-author approval, but every session pushes as one identity, so no session can supply one, and the gate was itself broken from 2026-09-11 until fixed (RN-T-05). Options: (a) name a non-author kernel reviewer; (b) record a standing override rule with conditions (for example registry-row-only PRs with green CI on both interpreters); (c) keep case-by-case overrides as incident rows. Consequence of (b) or (c): the eight PRs and the two registry rows still need a post-merge read to close #266. Recommendation: (a), because it is the only option that makes the "non-author" requirement true again; (b) only if no reviewer exists.

**Q3. Umbrellas and RFC.** Confirm that #89, #90, #93 stay open as tracking until their named evidence exists, that #140 stays parked until scope approval, and that CC-D-06 and CC-T-04 are marked off-scope, branch-only and unconfirmed, then handed over once a destination is named (no deletion). Recommendation: confirm all three.

## 6. Issue-level decisions that follow

| # | Question | Decider | Blocks | Exists as issue |
|---|---|---|---|---|
| 1 | #172: Q1a option 1, 2 or 3; Q1b behaviour if 2 or 3 | Chenyu | Kernel PR for `seed_unsupported`; wording of published comparisons | Yes, #172 |
| 2 | Non-author kernel reviewer or standing rule (Q2) | Chenyu | Closing #266; future registry-row PRs | Yes, #266 (rule question not stated there) |
| 3 | Add #294 and the termsbench row to #266's checklist | Zeyu | Complete record of overrides | Edit to #266 |
| 4 | #128 fix shape: count tools-port invocations for JSON-dialect harnesses, or skip the check for them. Also whether the event is part of any sealed receipt identity (not checked) | Zeyu proposes, Chenyu if identity-touching | A small kernel PR after #248 | Yes, #128 |
| 5 | P-T-18: `math.fsum` with a new pack id, or leave and document the interpreter | Chenyu | Any change to the committed pack | No |
| 6 | #140 five questions (scope, Housing in paper scope, retained runs vs rerun, method sequence, privacy boundary; question 5 moot) | Chenyu | Any Phase 0 work | Yes, #140 |
| 7 | #268 canonical sibling root: the worktree's sibling or the main repository's sibling (tests and `provision.sh` must agree), and whether PR #132's fallback is the fix | Yuchen, with Zeyu; Chenyu if `provision.sh` behaviour changes | Test collection and provisioning in other checkouts | Yes, #268; fix in PR #132 |
| 8 | Where #4.c's code lives and whether to fix it | Chenyu | Telemetry under training | Part of #4 |
| 9 | Paid-run authorization for #90 and the remaining matrix runs | Chenyu | #90 and #39.b | Yes, #90, #39 |
| 10 | Status of PRs #97 and #132 (refresh, supersede or close) | Yuchen; Zeyu merges | #89, #93, #268 | Yes, the PRs |
| 11 | Where CC-D-06 and CC-T-04 go (the case-consultant app's tracker) | Chenyu | Removing them from the AERead tracker | No |

## 7. Delivery

| Step | What | Owner | Lane | Depends on | Can start now |
|---|---|---|---|---|---|
| 1 | Owner answers Q1 to Q3 | Chenyu | n/a | none | yes |
| 2 | Edit #266 checklist (add RN-O-03, RN-O-04) | Zeyu | docs | none | yes |
| 3 | #165: pass `PYTHONPATH` in the three child processes | Zeyu | family/test | none | yes |
| 4 | #268: agree the canonical sibling root, then review PR #132's existing fallback and fix test and script together | Yuchen, Zeyu | family/test | section 6 item 7 | after the root contract is agreed |
| 5 | rLLM README section (#4.a, #4.b, #4.d) | Zeyu | docs | none | yes |
| 6 | Post-merge read of the eight PRs and two rows | named reviewer | kernel | Q2 answered | after step 1 |
| 7 | #128 fix | Zeyu | kernel | #291, #292, #293, #248 part 1; step 4 of section 6 | after the landing order |
| 8 | `seed_unsupported` kernel PR (if option 2) | Zeyu | kernel | Q1, same landing order | after the landing order |
| 9 | Close umbrellas as PRs #97, #132 and the campaigns report | Yuchen, Chenyu | family | PR refresh decisions | no |
| 10 | #140 Phase 0 | Zeyu | research/SOP | #140 scope approval | no |

Chenyu rules on kernel and scoring; a non-author reviewer supplies the kernel approval; Zeyu performs every merge. This plan only reports "ready to merge".

## 8. Not verified

- Whether `harness_claim_unreconciled` appears in any sealed receipt identity or hash, and whether editing `harness.py` affects the kernel-byte coupling that PR lanes mentions. Not read.
- tau3 receipts for the same marker as #128; no receipts opened.
- P-T-18's Python 3.10 result was taken from the incident row; not re-run (no 3.10 interpreter used).
- #165 was reproduced only as a failing child import, not by running the three tests; #268 was read, not run in a renamed checkout.
- #4.b and #4.c mechanisms: the named symbols are not in the tree at `1e2ae367`, so the claims could not be checked; they come from the issue and Chenyu's comment.
- CENSUS-OVERLAP: the source note was found and its reproduction read, but not re-run by me.
- Secondary items B10, N5, B19, B20 are not in the records and were not examined.
- Case-consultant: the branch `origin/codex/case-consultant` was not inspected.
- `seed_unsupported` itself is not implemented; the identity consequences above come from reading the pins and one in-memory comparison, not from a prototype. Endpoint coverage is the issue author's snapshot, not re-queried (no network).
