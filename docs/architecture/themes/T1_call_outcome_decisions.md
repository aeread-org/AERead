# Decision drafts for T1 (one GitHub issue each)

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5; a ruling is recorded here with its date and source.

One draft per decision; reply on the pull request or the board card citing the decision id. Labels: [owner] ruling, [merged] merged code or doc, [on behalf] adopted on the owner's behalf.

---

## [Decision] T1-D1: what execution witness permits a same-attempt re-send?

**Decider:** Chenyu. **Blocks:** #248 part 1 F2 beyond the inert default.

**Already ruled** [owner, #248, 2026-10-21]:
- An unknown-progress HTTP failure may be re-sent in the same attempt only with trusted evidence that nothing executed.
- No status exclusion stands in for that evidence.

**What the code can observe:**
- Two cases are proven not to have executed: a kernel refusal raised before the SDK call, and a CLI process that never spawned. Neither is an HTTP failure, so neither needs this decision.
- For an HTTP failure, no field parsed today proves the refusal came from the router before routing (`task/execution.py:2216-2274` reads code and message only).
- The openai SDK surfaces connect, write, read and protocol failures alike as `APIConnectionError`.

**Facts behind the options:**
- OpenRouter's documentation says that once a provider has started a response, later failures arrive inside an HTTP 200, and that its 503 means no available provider. It names no field that marks a router-native refusal.
- RFC 9110 and Cloudflare's 520-524 pages do not certify pre-execution.

| Option | Rule | Consequence |
|---|---|---|
| **A. None yet** | No same-attempt re-send. Every HTTP failure goes to the declared outer recovery (T1-D6) | Strict, and nothing invented. `transport_v1` re-send is inert, so #248 can land under the ruling with the predicate returning false |
| B. Named native attestation | Accept a provider- or router-native, machine-readable marker of pre-execution refusal, once identified, documented, version-pinned and probed | Fast re-sends come back where a provider really attests. Needs per-provider research first |
| C. OpenRouter status predicate | Treat OpenRouter's own 429/503 as pre-execution | Not verifiable from the response today; it is a status allowlist, which the ruling excludes |

**Recommendation:** A now; add B provider by provider.

---

## [Decision] T1-D2: charge witness and billing semantics

**Decider:** Chenyu. **Blocks:** honest spend claims, budget stops, #250, step 4.

**Already ruled:**
- [owner, #248] Missing usage proves neither no generation nor a zero bill.
- [owner, #135] Billed failed calls keep provider-reported usage and cost.
- [merged, #291] A valid provider cost stands on its own, and an unreported optional cache breakdown is zero.

**Today:**
- A usage-less 429/5xx is booked as exact `$0`.
- A success without usage is exact `$0` on Arena and Responses.
- Legacy failure events written with `0.0` read as settled (#226 finding 6). They carry no billing field, and their condition does not show whether anything was generated: a Claude Code non-zero exit is `provider_rejected` at `$0` without reading the usage and cost its stdout may carry (`task/execution.py:2803-2808`).
- Since #291, a failure event may carry a valid provider cost with no token counts and `token_accounting: "incomplete"`.
- Spend does not say whether a cost was provider-reported or priced locally.

**Sub-questions:**
- (a) What may prove a zero charge? This is separate from T1-D1: a call can run without being charged, or be charged later.
- (b) Are usage-less calls `unknown` rather than `$0` for new plans?
- (c) Does the spend reader re-qualify which legacy failures?

| Option | Rule | Consequence |
|---|---|---|
| A. Convention | Keep `$0`, documented as "no usage reported" | No change. `exact` keeps overstating what is known |
| **B. Evidence-based for new plans, one named legacy exception** | (a) Zero only for `proven_not_sent`, or with a charge witness: a provider's documented no-charge rule cited in the plan, or a billing lookup stating the charge. (b) Otherwise `unknown`, or `lower_bound` with partial usage; a valid provider cost is always kept. (c) The reader marks a legacy failure event as unsettled when its cost is `0.0` and it carries neither token counts nor the #291 `token_accounting` marker, whatever its condition (the #226 finding 6 proposal). That is the shape of a usage-less failure. A cost written from reported usage stays settled, including a reported zero. This is the only exception to T1-D5's legacy reading. Spend output says the re-qualification was applied and how many events it touched | Spend stops claiming knowledge it lacks. Old bytes and hashes are unchanged. Historical spend for any run with a usage-less failure becomes a lower bound, including failures that in fact cost nothing: legacy bytes cannot tell a kernel pre-send refusal or an HTTP 4xx rejection from a billed failure |
| C. B for every run at once | as B, including frozen plans mid-run | Honest at once, but contrary to "a sealed contract never gains new behaviour" |

**Recommendation:** B, with spend reporting what each cost source contributed.

---

## [Decision] T1-D3: does the call record carry the wire fact, with policy only on the attempt? (#254)

**Decider:** Chenyu. **Blocks:** step 2, #254.

**Today:** after a proven route, a 404's terminal event says `provider_rejected`, while its call record and attempt say `provider_rejected_after_route_proven` (`model_call/harness.py:353-372` vs `task/execution.py:3777-3781`).

| Option | Rule | Consequence |
|---|---|---|
| **A. Call = wire fact, attempt = policy** | Call event and record keep the raw condition. Retyping by route proof or retry policy lives on the attempt | One meaning per level; audits recompute policy from facts. Readers that took the call's condition as the policy outcome move to the attempt |
| B. Port learns route proof | The port writes the retyped condition on the call | Fewer reader changes; policy leaks into the wire record and the writers stay coupled |

**Recommendation:** A, as #254 already leans.

---

## [Decision] T1-D4: content typing

**Decider:** Chenyu. **Blocks:** #267 parity, HL-O-08 follow-ups (N3), #226 finding 2, step 3.

**Already ruled** [owner]:
- Completed, non-truncated malformed output is model behaviour with no invented repair (#135).
- Truncated and unparseable output is `length` (#152).
- #135 also says parseable content reported as truncated is rejected before parsing. Merged #233 instead accepts a complete-JSON truncated reply when no retry remains.

| Sub-question | Options | Recommendation |
|---|---|---|
| (a) Truncated reply that is complete JSON | accept (merged, only when no retry remains); always resample; always reject (#135 wording) | Reject, typed `length`. Today inclusion depends on how many attempts remain. Affects every family; single_offer, with no retries, on every such reply |
| (b) Reasoning-only reply: answer in `reasoning`, `content` empty (HL-O-08) | content type `reasoning_only` or not; condition `empty_response` or a new one; parsed or not | Content `reasoning_only`. Condition stays `empty_response`, so frozen retry lists keep their meaning. Not parsed. Reasoning is never copied into the answer. Attribution waits on #264. Whether another sample is allowed stays with N1 (T2) |
| (c) Refusal field with empty content; provider content filter | as for (b) | Content `refused` or `filtered`. Condition stays `empty_response`. Not parsed. The `refusal` text is recorded on the call but never copied into the answer. A refusal written as ordinary content is just content and goes to the parser. The Responses policy codes (design rule 2) take the same typing. Today nothing reads `refusal` or `content_filter`: a filtered reply with non-empty content is parsed and scored on OpenRouter and Arena, as is a Responses policy failure that carries text, so under this option a filtered reply that carried a parseable action is no longer scored and becomes retryable where `empty_response` is declared |
| (d) Completed answer without usage. Today OpenRouter and Claude CLI exclude it; Arena and Responses score it and book an exact `$0` | measured; excluded | Split by whether the served model is verified. If it is (OpenRouter route proof, which must then run before the usage check; Arena/Responses `model`): measured, billing `unknown`. If it is not: operational. That keeps Claude CLI without `modelUsage` excluded, as today, and newly excludes Arena replies that omit `model` (today the requested model is filled in, `task/execution.py:2573`) and Responses replies without `model` (`:1678`), which today are scored at exact `$0` |

---

## [Decision] T1-D5: how do contract changes reach frozen plans, and how are records without a version read?

**Decider:** Chenyu. **Blocks:** every behaviour-changing step.

**Already recorded:**
- [repository rules] A changed frozen control requires a new campaign identity, never a rerun in place.
- [record] A sealed contract never gains new behaviour.

**Constraint:**
- Adding a field to an old plan's canonical payload would break its hash (`run/resolver.py:703-747`).
- A reader that starts requiring new fields would turn historical `exact` totals into `unknown`.

| Option | Rule | Consequence |
|---|---|---|
| **A. Versioned; absent means legacy** | New plans carry `call_outcome_contract` in their design identity. Absent-version plans and events are read under legacy semantics, with bytes and hashes unchanged; the only reader exception is T1-D2(c). The kernel runs only the current version, so a new run of an old plan needs a new identity | No frozen identity silently changes meaning. A campaign in progress finishes on its pinned kernel or re-freezes |
| B. Apply to all new runs, with errata | Every run uses the current table; differences from earlier runs of one identity get an erratum | Simpler; runs of one identity mean different things |
| C. Per-family opt-in | Families adopt the contract when they re-freeze | Gradual; divergences persist until every family moves |

**Recommendation:** A.

---

## [Decision] T1-D6: what form does a declared recovery treatment take?

**Decider:** Chenyu. **Blocks:** recovery for unknown-progress failures in new identities, T2.

**Already ruled** [owner, #248]: any recovery other than a witnessed same-attempt re-send needs "a recovery treatment the profile explicitly declares, with its bound in the contract". The form was not given.

| Option | Rule | Consequence |
|---|---|---|
| A. The existing retry policy | `retryable_conditions` plus `max_action_attempts` (per logical action) and the optional backoff is the declaration | No new syntax; frozen profiles already declare it. Those lists were written as retry lists, not as decisions about unknown-progress recovery |
| **B. A dedicated declaration** | `retry_policy.unknown_progress_recovery: {conditions: [...], max_per_action: N, max_per_cell: M}`. Conditions are drawn from `timeout`, `transport`, `provider_5xx`, `rate_limit`, `provider_choice_error`. A failure of one of these conditions is retried only if it is in both this list and `retryable_conditions`, while both bounds hold. Completed-reply conditions (`length`, `empty_response`) keep today's rules. Applies to new identities | Recovery that can select survivors is declared and bounded per action and per cell, as the ruling asks. One more block per profile |

**Recommendation:** B for new identities; existing frozen profiles keep reading under A.

---

## [Decision] T1-D7: refusal typing for quota and CLI subjects

**Decider:** Chenyu. **Blocks:** N2, RN-T-06, #286, step 5.

**Today:**
- 402 is `account_fault` and halts the run [merged #232].
- A Codex CLI usage-window refusal is retryable `rate_limit`.
- Claude Code turns any non-zero exit into non-retryable `provider_rejected` without reading its stdout error JSON.
- A CLI spawn failure is untyped.
- Neither CLI exposes its internal reconnects.

| Sub-question | Recommendation |
|---|---|
| (a) Permanent quota vs temporary window | Only an explicit permanent signal (402, or a provider message that the account has no credit) is `account_fault`. It halts the run where the halt guard is adopted, leaving cells `not_attempted`. Usage windows stay `rate_limit` |
| (b) CLI precedence | A well-formed stdout JSON envelope first, then the exit code, then stderr |
| (c) CLI spawn and I/O | A spawn failure (`create_subprocess_exec` raising) is `proven_not_sent` and charged zero. An I/O error after the process started is `transport`, with unknown progress |
| (d) CLI observability | Record one observable invocation per CLI call, with provider-internal reconnects declared unknown, as `shared_runner_design.md` allows when SDK retries cannot be disabled |
