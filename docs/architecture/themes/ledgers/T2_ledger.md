# T2 Run-control contract: evidence ledger

**Evidence ledger for [T2](../T2_run_control_contract.md).** Line references are at main 1e2ae367 unless a row says otherwise.

Snapshot 2026-10-21/22. Source tree: `origin/main` `1e2ae367`. Paths below are relative to the repository root unless marked. Labels: `[read]` source read, `[run]` reproduced, `[row]` taken from an incident row or issue text. Threads fetched with `gh` on 2026-10-22 (read only).

Abbreviations: the [rulings register](rulings_register.md) holds the ids D-n and Q-n; `REC` = incident-log rows by id (most in `docs/operations/incident_log.md`; some only on the branch that recorded them); `CL` = the root-cause clustering summarised in the [themes README](../README.md), whose cluster ids (G01..G36) are used below.

## 1. Evidence ledger

| # | Claim | Source | Label |
|---|---|---|---|
| E1 | A length retry grows the output budget by doubling, bounded by `_length_retry_ceiling(profile)`. | `src/aeread/shared_runner/task/execution.py:3713-3727` | read |
| E2 | `_length_retry_ceiling` returns `harness.config["max_output_tokens_ceiling"]` if declared, else `max_output_tokens * _LENGTH_RETRY_MAX_GROWTH`; a declared ceiling below the cap raises `EvidenceIntegrityError`. | `execution.py:3730-3750` | read |
| E3 | `_LENGTH_RETRY_MAX_GROWTH = 8` (the implicit 8x ceiling, conflict C-8 / Q-6). | `execution.py:995-1001` | read |
| E4 | Arena path: on `ProviderFailure` with condition `length` the budget is grown with the same helper before `continue`. So the "Arena length growth" asked for by #135.d / G04 exists on main. | `execution.py:3305-3322` (growth at 3315-3318) | read |
| E5 | The retry decision uses only `condition in retryable_conditions` and `ordinal + 1 < max_action_attempts`; a `length` retry is cancelled when growth no longer changes the budget (already at ceiling). | `execution.py:3849-3860` | read |
| E6 | `provider_stream` is opt-in via `harness.config`; absent means not streamed. | `execution.py:1008-1020` | read |
| E7 | No profile under `src/aeread_families` declares `provider_stream` (grep empty). | `grep -rn provider_stream src/aeread_families` | run |
| E8 | The only importer of `shared_runner/run/halt.py` is `shared_runner/__init__.py:93-104`; no module under `src/aeread_families` imports `require_halt_rule` or `OperationalHaltGuard`. Housing campaigns implement their own streak (`price_campaign.py:667,711-712,754`). | `grep -rn "run.halt\|require_halt_rule\|OperationalHaltGuard" src tools` | run |
| E9 | `halt.py` defines the contract field `max_consecutive_operational_failures`, conditions `halted_after_consecutive_failures` / `halted_on_account_fault`, status `not_attempted`; `require_halt_rule(required=False)` returns None for a schema that predates it, so a sealed contract never gains a rule it did not declare. | `src/aeread/shared_runner/run/halt.py:40-79` | read |
| E10 | HTTP 402 is typed `account_fault`. | `execution.py:977-984` | read |
| E11 | Datacenter profiles seal `max_action_attempts: 1`, `retryable_conditions: []`, concurrency 1 per route provider. | `aeread_families/datacenter_development/runner.py:176-177`, `adoption_runner.py:220-221`, `world_campaign.py:199-211`, `salience_campaign.py:49` | read |
| E12 | `RETRY_POLICY_V2` is on main: retryable conditions add `timeout`, `transport`; length growth factor 2 with `max_output_tokens_ceiling` 32768; backoff; `max_consecutive_operational_failures` 3; v1 stops a worker's range at the first failed cell (`halt_after` returns 1). It is a Housing-only constant, opt-in by `retry_policy_version: 2`. | `aeread_families/housing/price_campaign.py:695-755` | read |
| E13 | Housing v2 asserts the kernel growth equals its declared growth (`kernel_length_growth`), i.e. the declared ceiling is checked against the kernel, not the other way round. | `price_campaign.py:722-739` | read |
| E14 | The kernel has no balance or key-limit reader: `grep -rniE "balance|key_limit|/credits|remaining_limit" src/aeread/shared_runner src/aeread/cli.py` matches only comments (`execution.py:981-982`, `halt.py:8`). `account_fault` and the halt guard act only after a 402. | run |
| E15 | #292 (draft, head `0feb7e23`, 5 files, +751): `run/controlled_campaign.py`, `campaign_cli.py`, tests. Controller admits work only if known spend + active reserves + next reserve fits `cost_limit_usd`; has `concurrency` and the streak limit; stops queued work on account fault or streak; drains started callbacks. Housing caller refuses concurrency other than 1. It records `effective_max_output_tokens_ceiling`, `max_action_attempts`, `retryable_conditions` per cell. It does not read a provider balance, set `provider_stream`, or size ceilings. Spend guarantee `[read]` of `0feb7e23:src/aeread/shared_runner/run/controlled_campaign.py`: module docstring "Reserves govern admission, never accounting ... There is deliberately no resume or provider-dollar cap" (lines 1-6); scope `campaign_invocation` (l.119-121); spend sums only this invocation's results (l.113-114); a started cell is not capped by its reserve, the stop `campaign_known_cost_limit_exceeded` fires after the result is persisted (l.153-154); `cost_accounting` may be `lower_bound` (l.74). | `gh pr view 292`; `gh pr diff 292` lines 68-71, 105, 376, 468-477, 608-611 | read |
| E16 | #293 was closed 2026-10-21T23:35Z under the 24-hour failing-CI rule; branch `zeyu/budget-campaign-adoption-20261020` kept; to be reopened after #291 and #292 land. Its body says it does not close real account preflight, D4 resource comparability, #274 analysis policy or all-family #289 conformance. | `gh pr view 293 --comments` | read |
| E17 | #291 is open, not draft, no review decision; #256 (Housing v14) is MERGED; #210 (datacenter halt, DC-T-08) is open; #288 (SOP sizing, reliability and screen-plan calculations) is an open draft; #125 is closed. | `gh pr/issue view` 2026-10-22 | read |
| E18 | Landing order set by owner: #246 (merged), #291, #292, #293; #248 after part-1 repairs. | rulings register D-11; rulings register | row |
| E19 | Alympics/collusion: 6/6 + 6/6 cells ended `length` at a 2048-token request with `max_action_attempts=1`, `retryable_conditions=[]`. | REC `#135.d` (Zeyu repro); CL G04 | row |
| E20 | GLM 5.3 Flash, by record and window: DC-O-08 11/32 (length at 4,000, empty content; cap was 1,800 doubled); DC-O-12 25/128 (18 timeouts at 2,000 s + 7 cut at 93,000); DC-O-13 10/256 cut at 32,000 plus 2 GLM-vs-GLM timeouts at 1,200 s; DC-O-14 28/44 is the early window, the final arm is 35/72 valid (37 not valid: 17 cut at 120,000, 13 timeouts at 3,000 s, 6 `price_on_an_accept`, 1 `provider_rejected`); DC-O-16 6/60 (5 cut at 32,000, 1 provider rejection). Gemini lost none in DC-O-08/12/13 (records state it for those). | REC `DC-O-08/12/13/14/16` | row |
| E21 | Housing: single 120 s hang ends a cell because `timeout` is not retryable under v1 (HL-O-04: Gemini 47/48, GLM 42/48); HL-O-19 one 300 s call halted a range (Gemini v13 59 pairs); HL-O-20 five DeepSeek cells failed and ten worlds never started. | REC `HL-O-04/19/20` | row |
| E22 | Rate-limit and transport halts under parallel workers sharing a key: HL-O-09 (Parasail key, `--only-worlds` workers), HL-O-10 (nine clients on one OpenAI key, three Luna cells timed out at 120 s), HL-O-11, HL-O-12 (97 of 120 GLM v6 cells missing), HL-O-13, HL-O-14. | REC | row |
| E23 | CLI subjects: Codex service refusals lost 21 cells across three campaigns (14 capacity refusals, 4 x 503, 3 x 300 s), all Codex, none Opus (DC-O-21); DC-O-18 timeouts cluster under six concurrent negotiations; DC-O-20 2/160 capacity refusals. | REC `DC-O-18/20/21`; CL G08 | row |
| E24 | Balance: DC-O-15 214 of 348 cells HTTP 402 with the account at $545.30 of $545; fixed forward by a balance-checked v2 (696/696, $3.93). HL-O-21: 36 Gemini cells lost in 20 s, 161 unattempted; key had no limit of its own. CLI-O-01: Claude Code login out of credits answered 429. | REC `DC-O-15`, `#286.a`, `CLI-O-01`; issue #286 body | row |
| E25 | Routes: P-O-05 pinned NextBit fp8 route removed (404, no run root spent); P-O-06 replacement Morph refused, price above pin; HL-O-05 same three GLM cells hung twice on Parasail; HL-O-06 world 100021 seed 1 hung 4 of 5 runs across two routes; DC-T-14 76 calls cut at a constant 76 s on both routes (cause unconfirmed, no `chunk_count` under evidence/). | REC; issue #264 body | row |
| E26 | No run set among the seven reported used the `aeread` CLI; drivers call `resolve_run_plan`, `execute_plan_cell`, finalizer and replay directly; driver bytes are hashed into sealed plans, so adoption needs a new identity. | REC `#289.f`; issue #289 body; the review dispositions note (working note, unpublished) (`resolver.py:695,703`) | row |
| E27 | The agent profiles (retry policy, harness config, sampling) are entries of the sealed plan payload, so changing a recovery rule changes plan identity. | `src/aeread/shared_runner/run/resolver.py:690-698` (`add(f"agent:{profile.profile_id}", profile)`) | read |
| E28 | Arms that share an account: #288 draft SOP "Arms that share an account" adds the interleave-by-world rule; the balance preflight and spend limit as a contract field remain open in #286. | issue #286 comment by LEE-CHENYU 2026-10-14 | row |
| E29 | #264 checklist: datacenter world-panel driver halt in draft #210; Housing switch to the kernel guard "before it merges" (#256 has since merged with its own stop); procurement, refund and adapter drivers still to declare the field. | issue #264 body | row |
| E31 | Housing retries are declared replacement: v1 `RETRY_CONDITIONS_V1 = [length, rate_limit, provider_5xx, empty_response]`; campaigns seal `max_action_attempts` 4 or 8 (`price_campaign.py:374-456`, `backend_campaign.py:449-453`, `population_campaign.py:158-163`, `model_sensitivity.py:235-238`); v2 adds `timeout`, `transport`. | `price_campaign.py:689,704`; files cited | read |
| E32 | `ArenaChatClient` builds `temperature: request.temperature` unconditionally (`execution.py:2478`) and rejects `request.stream` (`:2445-2448`); the other clients add `temperature` only if not None (`:1658-1659,1841-1842,1960-1961`); the executor sets `temperature=None` when `sampling_controls.temperature == "unavailable"` (`:3119-3124`). So the Arena request carries `temperature: None` for such a profile. T1 hands #267.b to T2 ([T1 design](../T1_call_outcome_design.md); rulings register Q-14: design drafted, no owner ruling). Read only; the wire kwargs were not rerun here. | files cited; issue #267 body (`gh`) | read |
| E33 | EconEvals sends a validation error back to the model within the same attempt and loops while `rounds_used < budget`; an empty response instead raises `ProviderFailure("empty_response", retryable=True)` (outer retry). [T1 design](../T1_call_outcome_design.md) assigns Q-15 to T2. | `src/aeread_families/econevals/live.py:439-482`; [T1 design](../T1_call_outcome_design.md) | read |
| E30 | Owner said replacing only failed cells "can select survivors"; the first-response-only principle with replacements counted as exposure is an author principle. | rulings register Q-8 row (`docs/architecture/provider_reliability.md:69`) | row |

## 2. Member list

Clusters G04, G08, G21, G22, G23 (CL). "True at 1e2ae367" = the defect/gap still stands on main.

| Member | What | State | Owner | True at 1e2ae367 |
|---|---|---|---|---|
| #135.d | Alympics/collusion 12/12 `length` at 2048 | ruled awaiting impl (D1); issue | zeyusuntt | Partly: Arena growth exists (E4); profiles still `max_action_attempts=1`, no ceiling declared; declared ceilings are the gap |
| #264.b (G21 primary, G04 secondary) | No profile declares `provider_stream` | issue open, family | LEE-CHENYU | Yes (E7) |
| DC-O-08/12/13/14/16 | GLM ceiling/timeout losses, datacenter campaigns | open rows (non-PR branches, lower confidence) | none | Sizing practice unchanged; no sizing helper on main (#288 draft only) |
| HL-O-04 | Timeout not retryable ends a cell | open | none | Yes under v1; v2 exists (E12) |
| HL-O-11/12/13/14 | rate-limit/transport/timeouts halt a worker | open | none | Yes for v1 identities |
| HL-O-19, HL-O-20 | Timeout not retryable / range stopped | partly fixed | none | v2 on main (E12); v13 keeps v1 |
| DC-O-17, 20, 21, 22 | Codex service refusals, differential by subject | open | none | Yes; no retry for CLI refusals (T1 N2 covers typing) |
| #267.b | Arena client ignores declared sampling controls and `provider_stream` | issue #267 open (board: Theme T1, P0, kernel); assignee ychenfang | ychenfang | Yes (E32) |
| Q-15 | EconEvals corrective feedback: interaction or repair | open question | Chenyu to rule | Unruled (E33) |
| N1 | Retry estimand draft (unposted) | open question Q-8 | Chenyu to rule | Unruled |
| #289.f | No single launch path | issue open | LEE-CHENYU | Yes (E26, E8) |
| #264.a | Cases have not adopted halt guard | issue open, P0 on board | LEE-CHENYU | Yes (E8) |
| DC-T-08 | Datacenter world driver has no stop rule | partly fixed; PR #210 open | zeyusuntt | Not on main (E17) |
| #286.a | No balance/key-limit preflight; spend limit not a contract field | issue open, Backlog, kernel | LEE-CHENYU | Yes (E14); #292 covers only declared cost limit with reserves (E15) |
| DC-O-15 | 214/348 cells HTTP 402 | fixed forward | none | Fixed for that campaign by operator check, not by contract |
| CLI-O-01 | Claude Code out of credits (429) | open | none | CLI credit typing is T1/N2; quota preflight is T2 |
| HL-O-05/06/09/10 | route stalls; shared key concurrency | open | none | SOP gap; no kernel check |
| DC-O-07 | Grok route not usable | superseded | none | Finding stands, not actionable |
| DC-O-18 | CLI timeouts under six concurrent negotiations | open | none | Yes |
| DC-T-14 | 76 s cut | open | none | Root unconfirmed |
| P-O-05, P-O-06 | Pinned route removed / repriced | open | none | Yes |
| Board #286 | Issue, Theme T2, Backlog, kernel, blocked by "PR#288 merge; kernel lane" | OPEN | | Yes |
| Board #264 | Issue, T2, P0, Backlog, family | OPEN | | Yes |
| Board #292 | PR, T2, Blocked, "after #291; cli.py conflict", waiting on landing order | OPEN draft | zeyusuntt | n/a |
| PR #293 | adoption (closed for now) | CLOSED | zeyusuntt | n/a |

Cluster-scope note: HL-O-08, HL-O-17 and DC-O-14 truncation attribution belong to T1/N3 and Q-9/Q-6 interplay; they appear here only for the ceiling-setting part.

## 3. Rulings in force (labels as in rulings register)

| id | Ruling | Label |
|---|---|---|
| D-7 | HL-O-08, HL-O-19, DC-O-14 are different cases and must not share one recovery rule. | owner |
| D-11 | Landing order #246, #291, #292, #293; #248 after part-1 repairs. | owner |
| D-15 | Length growth strictly increasing under the explicit ceiling; cap or exhaustion ends in typed `length`. Implemented by #233. | owner (2026-09-10) |
| D-19 | HTTP 402 is `account_fault`; halt rule read from contract; unreached cells `not_attempted`. Merged on admin override with no non-author review (RN-O-01). | merged, owner-account series |
| D-29 | Design doc: limit doubles per `length` retry up to `max_output_tokens_ceiling`, "default: eight times the declared limit". | merged |
| D-5 / D-6 | Any recovery other than same-attempt re-send with proof needs an explicitly declared treatment; no framework default stands in for it. | owner (2026-10-21) |
| D-42 | A failed cell stays missing; changing the control or route is a new identity. Incident-log disposition; authorship not shown. | record |
| D-32, D-34, D-35 | Recovery is a declared treatment; missingness is never assumed ignorable; stop on 401/402/403/quota-429. | record (author proposals); D-35 only 402 implemented |
| C-8 | Conflict: #135 "explicit ceiling" vs 8x implicit default. | open |

Open questions (rulings register): Q-5 (account exhaustion attribution), Q-6, Q-8 (N1), Q-15 (EconEvals corrective feedback), Q-16 (is S6 campaign runner mandatory for new confirmatory campaigns; asked 2026-10-04, no answer recorded).

## 4. Conflicts between sources

| # | Source A | Source B | Resolution |
|---|---|---|---|
| X1 | rulings register D-42 and (working note, unpublished) say housing retry policy v2 exists only on `codex/housing-lemons-outside-demand`. | `price_campaign.py:702` on main defines `RETRY_POLICY_V2`, and #256 is merged. | Main wins: v2 is on main as a Housing-only opt-in constant `[read]`. |
| X2 | CL G04 proposes an Arena length state machine as new kernel work. | `execution.py:3315-3318, 3713-3727` already grows and bounds Arena length. | Remaining gap is ceiling sizing and declaration (the review dispositions note (working note, unpublished), row 4). |
| X3 | #264 lists Housing "switch to the kernel guard before it merges". | #256 merged with its own streak (E8, E12). | Housing is now a live case of per-driver halt that #292/#293 would replace on the next identity. |
| X4 | the theme assignment note (working note, unpublished) says #292/#293 are "the first step" in this direction. | #293 is closed pending #291/#292 (E16). | Treat #292 as the only live carrier; #293 needs reopening. |
| X5 | #286 board item "Blocked by PR#288 merge". | #288 is an open draft SOP/calculation PR, not the kernel preflight. | The kernel preflight (#286 items 1-2) is not in #288; #288 supplies sizing/interleave SOP. |

## 5. Not checked

Provider-side behaviour of balance endpoints (no network); whether any non-main branch declares `provider_stream`; DC-O and HL-O numbers beyond the rows; the unposted N1 draft text itself (cited only through rulings register).
