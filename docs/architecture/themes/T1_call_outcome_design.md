# T1: one call-outcome contract for every model call

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5; a ruling is recorded here with its date and source.

**Summary.** Six components each decide what happened on a provider call: the clients, the executor's response path, its failure path, the harness port, the receipt classifier and the spend reader. They disagree. A probe of 18 outcome classes across the kernel's five client paths finds 31 divergences. Family-owned clients add more, and some of these divergences change which cells are measured.

This design records each call once, in a typed form, at three levels:

- **the call**: what was observed, the bill, the content;
- **the attempt**: what policy did with it;
- **the cell's terminal cause**: what ended the cell.

One classifier fills the call record from what each client can actually observe, using a fixed precedence of rules, and every reader uses these records. Existing rulings and merged code settle most of the table (section 2). Seven owner decisions remain (section 4). Section 5 lists every change to a measured result or a frozen identity. Delivery keeps the owner's landing order and starts with a conformance test that changes no behaviour (section 6).

## 1. Problem

### 1.1 What the code does today

Line references are at main `6d76731d`; the kernel files are unchanged through `1e2ae367`. `X` = `src/aeread/shared_runner/task/execution.py`, `H` = `src/aeread/shared_runner/model_call/harness.py`, `EV` = `task/evaluation.py`. Rows were reproduced in memory (no network, no paid call) unless marked *read*.

| # | Same outcome | Different answers | Consequence |
|---|---|---|---|
| 1 | Completed, non-truncated reply whose JSON is malformed | OpenRouter and Responses hand the raw text to the family parser (X:1898-1906, X:1679). Arena first rescues an embedded object (`Result: {"offer":7}` becomes `{"offer":7}`) and otherwise raises `provider_contract` (X:2585-2620). The CLI adapters reject a missing envelope or structured output, but pass through some structurally wrong objects (X:2811-2872; `tools/cli_subjects/codex_exec_client.py:220-237`). The kernel's one-call harness types it `provider_contract` (`model_call/open_harnesses.py:66-84`) | The same bad answer lowers a score on one client, is silently repaired on another, and drops out of the denominator on a third. The #135 ruling makes completed malformed output model behaviour and forbids invented repair. #267 covers Arena |
| 2 | Usage missing on a successful reply | OpenRouter: `provider_contract`, billing `unknown`, cell excluded (X:2277-2290). Claude CLI: `provider_contract`, billing left at the default `not_billed`, so `$0` (X:2830-2836, default X:96); `modelUsage` is also its only evidence of the served model. Arena and Responses accept the answer and book an exact `$0` (X:2538-2552, X:1675-1688) | Whether the answer is measured, what the books say, and whether the served model is verified all depend on the client |
| 3 | Usage-less HTTP 429/5xx | `billing="not_billed"`, cost `0.0`, spend `exact` (X:96, X:143-161) | Contradicts "missing usage proves neither no generation nor a zero bill" (owner ruling on #248). A gateway 504 can follow a finished generation |
| 4 | Usage in an HTTP error body | Dropped (X:1691-1740) | Billed failures read as `$0` (#250; fixed only on the unmerged #248 head) |
| 5 | One mid-stream upstream failure | Three billing states, depending on whether it arrives as an SDK error frame, an error chunk, or a read error after a usage chunk (X:1154-1181, X:1039-1130, X:2192-2198). A top-level usage on an SDK error frame is dropped by the SDK itself | Three spend qualifiers for one event |
| 6 | Error inside an HTTP 200 body | OpenRouter types integer codes by status (429 `rate_limit`, 5xx `provider_5xx`) and symbolic codes as `provider_rejected` (X:2216-2275). Arena: `provider_contract`, never retryable (X:2511-2517). Responses ignores `response.error`, whose `code` is a string such as `server_error` or `rate_limit_exceeded`; the call succeeds with empty text and then becomes `empty_response`, which Refund retries (X:1669-1688; `refund/runner.py:926`) | A 429 is retried on one client and final on another. Missingness differs by client |
| 7 | `finish_reason: error` | OpenRouter: `provider_choice_error` (X:2229-2247; integer codes first typed by status, as #235 specifies). Arena: `empty_response` when the content is empty, a successful answer when it is valid JSON (X:2517-2536, X:2570-2581). Responses: not typed | A reply the upstream marked as failed is scored on Arena |
| 8 | Failure after a round already succeeded (text plus tool calls) | The port writes `provider_call_succeeded`, then the executor writes `provider_call_failed` for the same call id (H:400-448, X:3810) | Two terminals for one call; `audit_reconciliation` fails (#249) |
| 9 | 404 after a proven route | Direct executor: `provider_rejected_after_route_proven` on the event and the record. Port: event `provider_rejected`, record the retyped name (H:353-372, X:3777-3781) | Event and record disagree (#254) |
| 10 | Unknown cost | The event says `"unknown"`, the attempt record `0.0` (X:164-184 vs X:3807) | Readers of records see a number where there is none |
| 11 | Caller cancellation vs outer timeout | A timeout (`ProviderFailure("timeout")`, retried if declared) leaves an attempt record and an event cost. A cancel leaves no cost key and no attempt record (X:3908-3943 vs X:3810-3846). On Python 3.10 and 3.11, a cancellation that `wait_for` swallows is never recorded (H:1185; PRV-D-06) | Two shapes for an interrupted call, and one that vanishes |
| 12 | CLI quota refusal or spawn failure | Claude Code: any non-zero exit is non-retryable `provider_rejected`, and the stdout error JSON is not read (X:2802-2808). Codex CLI: `rate_limit`, retryable (`codex_exec_client.py:207-215`). A spawn `OSError` escapes untyped (X:2795-2801) | The same account state is a different outcome per subject (RN-T-06, N2) |
| 13 | What ended the cell | The receipt `failure_class` is `any()` over the whole attempt history (EV:1135-1152). A final `provider_rejected` after any earlier `timeout` becomes `retryable_infrastructure` (*read*) | Exclusion reasons follow history, not the cause that ended the cell |
| 14 | Family-owned clients (*read*) | Refund's `GeminiProviderClient` types every error as non-retryable `provider_rejected`, hard-codes `finish_reason="stop"` (so truncation is never `length`, contrary to #152) and books missing usage as `$0` (`refund/runner.py:157-195`). The datacenter `ParameterCompatibleOpenRouterClient`, referenced in 29 modules, types completed malformed JSON as `provider_contract` and raises without the reported usage (`datacenter_development/objective_openrouter.py:25-145`). Wrapper clients in housing and procurement re-raise their own exceptions (`housing/provider_pacing.py:93`, `procurement_allocation/continuous_recovery.py:92-110`, `procurement_grounding/bakeoff.py:453`) | The kernel's rules do not reach these arms |

The full matrix (18 classes by five kernel client paths, 31 divergences, 79 probed cells) and the probe scripts are available on request. They were produced on 2026-10-21 against main, main plus #291, and the #248 head.

### 1.2 Why fixing tickets one at a time has not converged

#249, #250, #253/#291, #254 and #267 each fix one slice correctly, but each sets a local rule, and the rules do not compose. Missing usage shows it. #291 says it never becomes an exact zero, the classifier still books a usage-less 5xx as `$0`, and the 2026-10-21 ruling says it proves neither no generation nor a zero bill. All three are in force at once.

## 2. Already decided

Labels: **[owner]** a ruling by Chenyu; **[merged]** merged code or doc with owner approval; **[on behalf]** adopted on the owner's behalf and merged, with his own confirmation not recorded; **[record]** an author decision record, not a ruling.

- **[owner] #248 part 1** ([ruling, 2026-10-21](https://github.com/aeread-org/AERead/pull/248#issuecomment-6305443199)):
  - Record the real denial reason.
  - A time-only denial before the first actual re-send falls back to an eligible outer attempt.
  - Declaration, count, spend, route and cancellation gates stay.
  - Invalid admission is rejected before persistence.
  - Same-attempt re-send of an unknown-progress HTTP failure is allowed only with trusted evidence that nothing executed.
  - Any other recovery is a recovery treatment the profile explicitly declares, with its bound in the contract. The form is open (T1-D6). No framework default or status exclusion stands in for it.
  - HL-O-08, HL-O-19 and DC-O-14 do not share one recovery rule.
  - Frozen-version applicability is established first.
  - Every call and its original failure stay visible.
  - Parts 2-4 of #248 each need their own final-head review.
  - Kernel landing order: #246, #291, #292, #293. #248 lands after its part-1 repairs; its order relative to #292 and #293 is not set.
- **[owner]** Completed, non-truncated malformed output is billable model behaviour and reaches the family parser, with no invented repair (#135, 2026-09-10).
- **[owner]** Truncated and unparseable output is typed `length` on every client and never scored (#152 option 1). Growth is bounded and accounted (#135; merged in #233). #233 still accepts a truncated reply that is complete JSON. That conflicts with the #135 wording and is left to T1-D4(a).
- **[owner]** Billed failed calls keep provider-reported usage and cost. An unknown cost is not replaced by a local estimate to justify retrying (#135).
- **[owner]** One terminal per started call, attempt or tool invocation (#101 invariant). Every tool-dispatch intent gets a disposition, at most one terminal, and abandonment is typed `tool_dispatch_abandoned` (#102).
- **[on behalf]** `provider_choice_error` (#223, merged in #235):
  - Covers `finish_reason: error` with no integer status, and a choice-level error object whose code is not an integer.
  - Retryable only for a profile that names it.
  - A choice error carrying an integer code is still typed by that code.
- **[merged]** HTTP 402 is `account_fault`, never retryable, and drives the halt rule (#232).
- **[merged]** Streamed-path typing (#247): error-frame codes are mapped like HTTP statuses; a stream that ends without a terminal finish is retryable `transport`; usage seen before a failure is kept.
- **[merged]** An unreported optional cache breakdown (`{}`, `cached_tokens: null`, audio-only details) is no cached input, priced at the full input rate, next to valid prompt and completion counts (#291 CI repair).
- **[merged]** Calls and retries (`docs/architecture/shared_runner_design.md`):
  - Transport re-sends are separate calls.
  - SDK retries are disabled where possible; otherwise each request is exposed or the observability limitation is declared.
  - Retry happens only under the declared policy.
  - The family owns parsing.
- **[record]** `docs/architecture/provider_reliability.md`: recovery is a declared treatment, and missingness is never assumed ignorable. Its S1 approval does not cover retry eligibility or stopping policy. Its 5xx handling row is superseded by the 2026-10-21 ruling.

## 3. Proposal

### 3.1 Three levels of record

| Level | Written by | Carries | Read by |
|---|---|---|---|
| **Call**: one terminal per started provider call or tool invocation | the component that opened it | sent and progress evidence, error condition, billing, content type and derived condition | spend, research, publication, census |
| **Attempt** | the executor | the policy applied to the call: recovery decision, denial reason, retyping such as route proof (T1-D3) | retry logic, audit |
| **Cell terminal cause**: once per cell | the executor or scheduler | what ended the cell: the final attempt's policy outcome, a budget stop, a harness contract failure, a cancellation, a halt | the receipt classifier |

The receipt reads the cell's terminal cause, not `any()` over the history (row 13) and not the last call. A call can succeed while the cell ends on a budget stop (#253/#291) or a harness contract failure (row 8).

Attribution (model, provider, environment, budget and so on) is not a field here. Mapping terminal causes to the incident register's vocabulary waits on #264 and its open rulings on taxonomy and declared-ceiling semantics (questions 1-2 of a working note, unpublished).

### 3.2 What each client can actually observe

The classifier uses only what a client can observe. What it cannot observe is recorded as `unknown`, never assumed.

| Observation | Non-streamed HTTP (OpenRouter, Responses, Arena; openai SDK over httpx) | Streamed OpenRouter | CLI subjects |
|---|---|---|---|
| Request provably not sent | only for a kernel pre-send refusal raised before the SDK call (Responses X:1621-1647, Arena X:2440-2463). An SDK exception never proves it: connect, write, read and protocol failures all surface as `APIConnectionError`, and connect, read, write and pool timeouts as `APITimeoutError`, with the cause chained | same | a spawn failure in `create_subprocess_exec` proves nothing ran. An I/O error after the process started proves nothing |
| Status, headers, parsed error body | yes | yes, before the stream starts | stdout JSON and exit code only |
| Content progress | **unknown** until a final reply arrives | decoded deltas and usage chunks. No first-byte, keepalive or server-side generation-start signal | **unknown**; only the final envelope |
| Usage | final usage | usage chunk if one arrives. A top-level usage on an SDK error frame is dropped by the SDK | final envelope |
| Provider- or gateway-internal retries | **unknown**. SDK retries are off and OpenRouter `allow_fallbacks: false` (X:2144) narrows routing, but gateway-internal retries cannot be observed | unknown | **unknown**: a declared observability limitation, so one kernel call may be several provider calls |

### 3.3 The call record and its precedence rules

Fields:
- `sent`: `proven_not_sent` · `sent` · `unknown`
- `progress`: `none_observed` · `observed` · `unknown`, set strictly from section 3.2's capabilities
- `condition`: the existing names, so frozen profiles' `retryable_conditions` keep working
- `billing`: cost and cost source, and token completeness, recorded separately
- `content`: `valid` · `malformed` · `truncated` · `empty` · `reasoning_only` · `refused` · `filtered`, only for completed replies and for a policy refusal typed under rule 2. Content is the raw reply with no kernel repair; whether it is a valid action is the family's judgement

Rules, in order:

1. **Progress is what was observed.** A streamed delta makes `progress: observed`, whatever follows. A later 402 or 5xx sets the condition but never "not executed". A non-streamed call with no completion body (an exception or an error status) has `progress: unknown`; a completion body sets progress from what it carries. A stream that ended with no delta is `none_observed`. Table cells below that say "as observed" apply this rule and never fix a value.
2. **Error-condition precedence**, as merged and extended to every client:
   - An integer status or code is typed by it (#235, #247).
   - A choice-level error with no integer code, or `finish_reason: error`, is `provider_choice_error`.
   - A response-level or top-level error with a symbolic code maps by an explicit table. For the Responses codes: `server_error` → `provider_5xx`; `rate_limit_exceeded` → `rate_limit`; policy codes (`bio_policy`, `misalignment_policy_violation`, `image_content_policy_violation`) → condition `empty_response`, content `filtered`, as T1-D4(c) (today Responses ignores `response.error`: a failed response with empty text is `empty_response`, and one with text goes to the parser, X:1669-1688, X:3467-3470); other `invalid_*` and image codes → `provider_rejected`. Unlisted codes → `provider_rejected`. The table is reviewed with step 3.
   - A stream that ends without a terminal finish is `transport`.
3. **Not-sent evidence.** `sent: proven_not_sent` comes only from a kernel pre-send refusal or a CLI spawn failure. Same-attempt re-send of anything else needs an execution witness (T1-D1).
4. **Interruption.** An outer timeout keeps condition `timeout`, retried if declared. A caller cancellation is `interrupted_during_provider_call`, never retried. Only the record shape is unified (3.5).
5. **Account and quota.** 402 stays `account_fault`; a temporary usage-window or rate refusal stays `rate_limit`. Permanent quota exhaustion is T1-D7.

### 3.4 Billing

1. **A valid provider-reported cost is kept**, whether or not the token counts are valid (#291).
2. **Token completeness is recorded separately.** Invalid required counts (prompt, completion) are never written as zeros. An unreported optional cache breakdown is zero next to a valid prompt count, as merged in #291. This is consistent with #291 after its branch-review fix F1.
3. **Complete, valid counts with declared pricing** are priced locally, and the cost source is recorded as `local`.
4. **Partial usage**, including usage in an error body, is a qualified observation: `lower_bound` if the known part can be priced, else `unknown`.
5. **No usage at all** is `unknown`, except for `sent: proven_not_sent`, which is a zero charge, or a call with a charge witness (T1-D2).
6. **Spend** is `exact` only if every call's cost is provider-reported, completely priced, proven not sent, or witnessed zero. It states what each cost source contributed.
7. **Legacy events** are read as today. The one named exception is T1-D2(c).

### 3.5 One writer, one interruption shape

- **Terminals.** The component that opened a call writes its single terminal (#249, #254 per T1-D3).
- **Tool-dispatch intents** follow the #102 ruling.
- **Events and records agree.** An unknown cost is unknown in both (row 10).
- **Interruptions share one record shape.** A caller cancellation, an outer timeout and a cancellation during backoff each write the same record shape. Usage already observed is kept as a lower bound (N6, PRV-D-07). Their conditions differ, per rule 3.3(4).
- **Cancellations are never swallowed.** A cancellation-safe wait replaces `asyncio.wait_for` for all profiles, so a cancellation is not lost on Python 3.10 and 3.11 (PRV-D-06). #248 part 4 does this only for stream-deadline profiles.
- **Callers outside the executor** use the same classifier and records, including the adapter canary.

### 3.6 Family-owned clients

These real provider clients either move onto the kernel classifier or are recorded as declared divergences in the conformance test:

- Refund `GeminiProviderClient`;
- datacenter `ParameterCompatibleOpenRouterClient`;
- the housing, procurement and procurement-grounding wrappers (row 14).

Scripted providers are out of scope: baselines, fixtures, `FixedResponseProvider`, and similar. The full inventory is the 20 modules that implement `complete()` under `src/aeread_families` and `tools/`.

### 3.7 The table

The conformance test reads this table as data. The billing column applies 3.4 rules 1-5 for every row. A reference such as T1-D4 marks a cell that waits on that decision.

| Observation | sent / progress | condition | content |
|---|---|---|---|
| kernel pre-send refusal; CLI spawn failure | proven_not_sent / none_observed | existing condition; spawn failure `transport` | – |
| connect, read, write or protocol failure; SDK timeout | unknown / as observed | `transport` / `timeout` | – |
| HTTP 402 | sent / as observed | `account_fault` | – |
| HTTP 429 or 5xx, gateway 502, 504 or 520-524, HTML body | sent / as observed (non-streamed: unknown) | `rate_limit` / `provider_5xx` | – |
| error in a 200 body, a response-level error, an SSE error frame | sent / as observed | rule 2 on every client | – (a policy code: `filtered`, rule 2) |
| stream ends without a terminal finish | sent / as observed (no delta: none_observed) | `transport` | – |
| outer timeout | sent / as observed | `timeout` | – |
| caller cancellation | sent or unknown / as observed | `interrupted_during_provider_call` | – |
| completed, valid | sent / observed | – | `valid` → parser. Missing usage: T1-D4(d) |
| completed, malformed, not truncated | sent / observed | – | `malformed` → parser on every client (#135), raw and unrepaired. A missing CLI envelope is operational |
| truncated, unparseable | sent / observed | `length` | `truncated`, never scored (#152) |
| truncated, complete JSON | sent / observed | T1-D4(a) | T1-D4(a) |
| reasoning only, empty content | sent / observed | `empty_response` (T1-D4(b)) | `reasoning_only`, not parsed |
| `finish_reason: error`, no integer code | sent / as observed (an error with no content delta: none_observed) | `provider_choice_error` on every client | not scored |
| refusal field with empty content; provider content filter | sent / observed | T1-D4(c) | `refused` / `filtered`, not parsed |
| kernel one-call harness reply cut off | sent / observed | `length` (Q-20) | `truncated` |

Recovery is not a column. The executor decides it from the call record and the profile's declaration (form: T1-D6). A same-attempt re-send also needs an execution witness (T1-D1).

## 4. Decisions

There are seven decision packets, each with its options in [T1_call_outcome_decisions.md](T1_call_outcome_decisions.md). Appendix A records the disposition of every open question in the [rulings register](ledgers/rulings_register.md).

| Id | Question | Recommendation | Blocks |
|---|---|---|---|
| T1-D1 | What execution witness permits a same-attempt re-send? | None until a verifiable witness exists. Ship the predicate returning false | #248 F2 (inert under this choice) |
| T1-D2 | Charge witness; usage-less calls; legacy usage-less failures | `proven_zero` only with a charge witness or `proven_not_sent`. Otherwise `unknown` or `lower_bound`. A valid provider cost is always kept. Legacy usage-less failure events at `$0` are re-qualified by the reader, whatever their condition, without changing their bytes | spend claims, budget stops, #250 |
| T1-D3 | #254: is the call record the wire fact, with policy only on the attempt? | Yes, option (a) | step 2 |
| T1-D4 | Content typing: (a) truncated complete JSON; (b) reasoning-only; (c) refusal and filter; (d) a completed answer without usage | (a) never scored; (b) content `reasoning_only`, condition `empty_response`, not parsed; (c) content `refused` / `filtered`, condition `empty_response`, never copied into the answer; (d) measured with billing `unknown` when the served model is verified, operational when it is not | #267 parity, HL-O-08, #226 finding 2 |
| T1-D5 | How do contract changes reach frozen plans, and how are records without a version read? | The version enters design identity for new plans. Absent-version plans and events are read under legacy semantics, bytes and hashes unchanged. The only reader exception is T1-D2(c) | every behaviour-changing step |
| T1-D6 | The form of a declared recovery treatment (Q-2) | A dedicated, bounded declaration for unknown-progress conditions, for new identities | #248 F2 beyond inert, T2 |
| T1-D7 | Quota typing and CLI precedence | Permanent quota only on an explicit signal. CLI: stdout JSON, then exit code, then stderr. Spawn failure is `proven_not_sent`; a post-start I/O error is `transport` | N2, RN-T-06, #286 |

## 5. Changes to measured results and identities

Each change ships only under T1-D5's rule, gated by its decision. Two kinds of change are listed.

**Changes to which cells are measured, or how they are scored or retried:**

| Change | Before → after | Affected | Gate |
|---|---|---|---|
| Arena and CLI malformed replies reach the parser | excluded → measured, scored by the family | Arena and CLI arms | step 3, T1-D5 |
| Arena embedded-object rescue removed | repaired and valid → raw. The family decides, and repaired actions may become invalid | Arena arms | step 3, T1-D5 |
| One-call harness: malformed reply and cut-off reply | `provider_contract` → parser; `provider_contract` → `length` with growth | housing and procurement-grounding bake-off arms | step 3, T1-D5 |
| Arena choice error carrying valid JSON | scored answer → `provider_choice_error` | Arena arms | step 3, T1-D5 |
| Truncated reply that is complete JSON | accepted when no retry remains → `length`, not scored | every family; single_offer (no retries) on every such reply | T1-D4(a) |
| Errors inside a 200 body or response-level errors | Arena: final → retryable if declared. Responses: a failed response with empty text is `empty_response`, retried by Refund, and one with text is parsed and scored → typed by code, so Refund (which declares only `length`/`empty_response`) no longer retries a 5xx or rate-limit error, and a failed response with text is no longer scored | Arena arms, Refund | step 3, T1-D5 |
| Filtered or refused replies | nothing reads `refusal` or `content_filter` today: a filtered reply with non-empty content is parsed and scored → content `filtered`/`refused`, condition `empty_response`, not parsed, so it is no longer scored and is retried where `empty_response` is declared. The same holds for a Responses policy failure with text. Empty filtered replies, and Responses policy failures with empty text, are already `empty_response` | OpenRouter, Arena and Responses arms | T1-D4(c) |
| Answers without usage, served model verified | OpenRouter excluded → measured | OpenRouter arms | T1-D4(d) |
| Answers without usage, served model not verified | Arena reply omitting `model` (the requested model is filled in, X:2573) or Responses reply without `model` (X:1678): scored at exact `$0` → operational, not scored | Arena and Responses arms | T1-D4(d) |
| CLI refusals | Claude non-zero exit carrying a 429 → retryable `rate_limit`; "no credit" → `account_fault`, halting where the guard is adopted; spawn failure → `proven_not_sent` | CLI subjects | T1-D7 |
| Receipt `failure_class` | follows the terminal cause instead of history | exclusion-reason counts | step 2, T1-D5 |
| Family-owned clients | per client, once migrated | Refund, datacenter, housing, procurement | step 1 inventory, T1-D5 |

**Changes to the books and to identity:**

| Change | Effect | Gate |
|---|---|---|
| Usage-less failures and successes | exact `$0` → `unknown` or `lower_bound`. Spend totals become lower bounds where gateway errors occurred; budget stops can fire later | T1-D2 |
| Legacy usage-less failure events (`$0`, no token counts, no `token_accounting` marker), any condition | settled → unsettled in the reader; a cost written from reported usage, including zero, stays settled. Bytes unchanged | T1-D2(c) |
| `call_outcome_contract` version | enters design identity, so every new plan gets a new identity | T1-D5 |
| Plans that pin all of `execution.py` (Refund) | new identity on every kernel change | tracked under T3 |
| Sealed evidence | none: bytes untouched. Replay re-executes family steps and does not re-issue provider calls; verified for the kernel replay path, not per family | – |

## 6. Delivery

Each step is one kernel PR with a non-author approval, run against the merged families.

| Step | Content | Depends on |
|---|---|---|
| 0 | In the owner's order: #291 with its branch-review fixes. Then #248 part 1: F1, admission, and F2 inert under T1-D1 (a typed no-execution fact defaulting to false, no producer), which meets the ruling's landing condition. Whether parts 2-4 land with #248 or are split is #248's scope (Q-18). Each part keeps its own final-head review | landing order |
| 1 | Conformance test: the table as data, every kernel client, the one-call harness and the real family clients (3.6) driven through every observation; today's divergences recorded as expected failures. No behaviour change | none |
| 2 | Three record levels, single terminal writer (building on #248 part 3 if it has landed), tool-intent dispositions (#102), one interruption shape, cancellation-safe wait for all profiles, adapter canary on the same records | T1-D3, T1-D5 |
| 3 | Content typing and rule-2 precedence on Arena, Responses, the CLI adapters and the one-call harness; Arena rescue removed | T1-D4, T1-D5 |
| 4 | Billing: rows 2-5 and 10, #250, N6, cost source, spend token completeness, legacy re-qualification | T1-D2, T1-D5 |
| 5 | Recovery declaration (T1-D6), named attestations if any (T1-D1 option B), CLI refusal typing (N2, RN-T-06), family clients migrated | T1-D1, T1-D6, T1-D7 |

## 7. Not verified

- Responses cells were probed with constructed SDK objects, not live responses.
- Family-owned clients were read, not probed. Families with their own failure registers (econevals) were not re-read.
- That replay never re-issues provider calls is verified for the kernel path only.
- Rows 11 and 13 and cancellation during backoff were read, not run.

## Appendix A. Disposition of the decision register's open questions and conflicts

| Item | Disposition |
|---|---|
| Q-1 execution witness | T1-D1 |
| Q-2 recovery declaration form | T1-D6 |
| Q-3 usage-less billing | T1-D2 |
| Q-4 #254 | T1-D3 |
| Q-5 taxonomy, Q-6 ceiling semantics, Q-7 legacy register evidence | out of T1: #264 (questions 1-3 of a working note, unpublished) |
| Q-8 retry estimand (N1), Q-15 econevals corrective rounds, Q-16 kernel campaign runner | out of T1: T2, run-control contract |
| Q-9 reasoning-only | T1-D4(b) |
| Q-10 CLI precedence | T1-D7 |
| Q-11 budget-stop condition | in #291 (`cost_budget_exceeded`, class `environment_failure`), awaiting its non-author approval |
| Q-12 cancelled-stream usage | 3.5, step 2 (follows the #135 rule on billed failed calls) |
| Q-13 truncated complete JSON | T1-D4(a) |
| Q-14 #267 | parsing: step 3; sampling controls (#267.b): T2 |
| Q-17 `transport_v1` naming | #248 part 1 (unmerged, no frozen user) |
| Q-18 #248 split | #248 PR scope; step 0 |
| Q-19 legacy events as exact zero | T1-D2(c) |
| Q-20 one-call harness truncation | table row, step 3 |
| Q-21 #289 subject-client fields | observation capabilities (3.2); the rest stays in #289 |
| C-1 reliability doc 5xx row; C-2 S4 spec | superseded by the ruling; both documents revised with step 5 |
| C-3 missing usage | T1-D2 |
| C-4 truncated complete JSON | T1-D4(a) |
| C-5 status exclusion | superseded by the ruling |
| C-6 #254 | T1-D3 |
| C-7 stale DC-T-15 row | incident-log update with step 3 |
| C-8 implicit 8x ceiling | T2 and #264 |
| C-9, C-10 receipt class vs attribution vocabulary | #264 |
| #128 claimed-tool counter; #130 billed-input divergence; `inference/llm_agent.py` legacy retry | outside the contract: a diagnostic, an investigation, and outside the shared runner |
