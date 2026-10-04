# Provider-call reliability: decision record

**Status:** accepted for implementation, slice by slice. Each slice is a separate kernel PR with its own review. Started 2026-10-04.
**Tracking:** #226 items 1, 3 and 4. Decisions are posted on #226 (comment 5958753497, update of 2026-10-04).

This record explains why the kernel handles failed provider calls the way it does, which alternatives were weighed, and what other evaluation frameworks taught us. Read it before changing retry, timeout, rate-limit, halt or campaign-runner behaviour.

## 1. Problem

Live campaigns lose cells to ordinary transient provider faults, and a person recovers them by hand. The housing lemons runs of 2026-10-01 to 10-03 are the evidence: HL-O-01..20 and HL-T-01..08 in the incident log on `codex/housing-lemons-outside-demand`. The faults themselves are unavoidable:

| Fault | Rows |
|---|---|
| Stalled calls | HL-O-04..07, 10, 14, 19 |
| Dropped connections | HL-O-03, 12, 13 |
| 429s from shared pools | HL-O-09, 11, 15, 16 |
| Routes that do not support the request shape | HL-O-08, 18 |

Three amplifiers turn those faults into lost work:

1. **No tolerance.** Contracts did not declare `timeout` or `transport` retryable, so one blip ended a cell.
2. **Halt on first failure.** The housing driver halted its whole range on the first failed cell. In HL-O-12, two `transport` errors in one second left 97 of 120 cells without a result.
3. **No load control.** Several worker processes shared one API key with no limiter (HL-O-09, HL-O-10).

One hang is still unexplained. World 100021 seed 1 hung in 5 of 5 GLM campaign runs, and in none of two diagnostic copies or 84 direct replays (HL-O-04..07). No call recorded where in the transport it stopped.

The current design, as built (`origin/main` 0993ac31), has these gaps:

| Gap | Where |
|---|---|
| Transport retries open a new `ActionAttempt` and share `max_action_attempts` with `length` retries. Shared runner design §4.1 says transport retries are separate `ProviderCall`s inside one attempt. | `task/execution.py:3141`, `:3507` |
| The only deadline is one `asyncio.wait_for` over a non-streamed request, so a dead connection, a queued request and a long answer look the same | `task/execution.py:2680` |
| The kernel has no concurrency primitive or limiter | none |
| Families declare different retry rules for the same physical event. govsim and econevals retry `timeout`; housing, procurement and refund do not; none retries `transport`. | family profile builders |
| Every campaign module re-implements scheduling, halting, resuming and retrying. None of the 56 `campaign` modules on `main` uses `OperationalHaltGuard`. Versioned modules are deliberate (`docs/families/campaign_modules.md`); re-implementing orchestration in each version is not. | `src/aeread_families/**/*campaign*.py` |

## 2. What other frameworks do

Three frameworks were read at pinned commits on 2026-10-03: UK AISI Inspect AI `9f6accda`, Harbor (Terminal-Bench 2.0) `3e30cca0`, and Prime Intellect verifiers `484e6de6` with prime-rl `d9adc1e8`.

| Concern | Inspect AI | Harbor | Prime Intellect | AERead decision |
|---|---|---|---|---|
| Call retry | Typed per-provider retry decision; exponential jitter; **unlimited by default**; a quota 429 is never retried | LiteLLM wrapped by two tenacity layers (3 x 3 calls); failed attempts are not counted | The proxy does not retry; the harness SDK does; failed exchanges are recorded | Retry only what the contract declares, with bounded attempts and time; every attempt is a recorded `ProviderCall` |
| Retry-After | Parsed, then unused | Not handled | Not relayed | Honoured; a long value pauses the whole route or key |
| Deadlines | `attempt_timeout`, a retry window, and `stream_idle_timeout`; `working_limit` excludes waiting | Per-phase agent and verifier timeouts | Connect 30 s, no read timeout | Layered deadlines (connect, first progress, idle, whole call), with waits excluded from the action deadline |
| Concurrency | Adaptive per provider and key (slow start, x0.8 on 429), in-process only | One semaphore over trials | Semaphore; adaptive only against vLLM pressure | A per-key and per-route limiter in one process; fixed limits first, adaptive later |
| Unit failure | `fail_on_error` threshold; errored samples leave the denominator | Missing reward counts as 0 | Error reward is 0, excluded from the "effective" mean | Typed missingness, never zero, with per-arm missingness reporting |
| Unit re-run | `retry_on_error` restarts the sample; `eval-retry` re-runs errored ones | Trial retry deletes the failed attempt's directory | Rule-based episode retry; one resume path drops errored episodes | No selective re-run in confirmatory campaigns; an attempt that never reached a provider may be re-dispatched |
| Bias stance | A written warning that re-rolls shift the distribution | None found | None found | Recovery is a declared treatment, reported, never assumed neutral |

**Adopted:**
- from Inspect: typed per-provider retry decisions, the quota carve-out, a stream-idle deadline, time budgets that exclude waiting, and a written bias stance;
- from Harbor: one process owns the run, every unit writes a typed result, and timing is kept per phase;
- from Prime: every failure is attributed to one boundary, and failed exchanges are kept as data.

**Refused:**
- unlimited or nested retries;
- deleting or rewriting failed attempts;
- scoring infrastructure failures as 0, or silently dropping them from a denominator;
- fabricated fallback messages after a failure (Harbor's terminus-2 does this);
- whole-unit re-runs that nobody declared.

AERead's typed failure conditions and append-only evidence were already stricter than all three frameworks, and they stay.

## 3. Principles

1. **Recovery is a declared treatment.** A re-sent call yields a survivor weighted by the chance that a draw completes. For independent actions, retrying a call and dropping the cell select the same distribution; what retrying changes is the denominator and the cost.
   - A retry is close to neutral only when the provider never began generating. Examples: a connect failure, or a 429 before any output.
   - Seeds do not make retries deterministic. The SDK documents "determinism is not guaranteed".
2. **Deadlines are operational guards.** An expired deadline means progress unknown, unless the transport shows the provider had not started. Deadlines are calibrated, and each expiry is reported as censoring.
3. **A transport retry re-sends the identical request.** A retry that changes the request (for example a larger output budget) is semantic and opens a new `ActionAttempt`.
4. **Recover at the lowest layer that suffices:** the call, then a route pause, then the cell, then a campaign stop. No layer is assumed unbiased.
5. **Missingness is never assumed ignorable.** The estimand, the denominator and the exclusion rules are frozen before confirmatory runs; missing outcomes are bounded, not imputed.
6. **One owner per concern.** The kernel retries, limits, schedules and halts; families declare. SDK retries stay at 0.
7. **Every limit is in the contract, through opt-in versioned policies.** A sealed contract never gains new behaviour.

## 4. Handling decisions

Each rule is derived from an existing convention, so no new convention is invented. Each applies only to contracts that opt in, through `harness.config["transport_policy"]` and new `execution` keys.

| When this happens | Handling | Derived from |
|---|---|---|
| The call fails before the model produced output: connect, DNS or TLS failure, 408, 429, 5xx | Re-send the identical request with backoff, only for conditions the contract declares. A 429 `Retry-After` pauses the route or key. | "Every limit that can terminate a run belongs in the contract"; design §4.1 (transport retries are `ProviderCall`s inside one attempt) |
| A streamed call gets no token within its first-progress deadline | Retried if declared; the transport phase is recorded | Design §4.2 (`timeout` is `retryable_infrastructure`); new opt-in knob beside `provider_stream` |
| The call breaks after output started, or returns `finish_reason: error` | Retried only if declared; counted as exposure; never a default | Principle 1 |
| 402, 401 or 403, or a 429 that states the quota is exhausted | Stop the campaign | `OperationalHaltGuard` already stops on `account_fault` |
| A rejected parameter or "no endpoints" before the route was proven | Stop the route; profile admission should catch it first | Unchanged `provider_rejected`. A 404 after proof keeps `provider_rejected_after_route_proven`. |
| Repeated transient failures on one route | Pause the route (a breaker), probe with the next real call, stop after a declared maximum outage | Generalises the consecutive-failure halt rule; `OperationalHaltGuard` stays the cell-level backstop |
| The process dies mid-campaign | Resume from evidence. Completed attempts never re-run. An attempt that started no provider call and no tool invocation is re-dispatched. Anything else is typed missingness. | "A failed cell is typed missingness and is never selectively rerun"; design §5 |
| The answer is only in `reasoning`, with null `content` (HL-O-08) | Stays `empty_response` | Today's client behaviour |
| Streamed-call defects: no terminal finish, lost error-frame status, dropped reasoning (#226 post-merge findings 3-5) | Plain bug fixes | No campaign on any branch declares `provider_stream`, so no frozen or published result changes |

**Open, pending confirmation on #226:** whether new confirmatory campaigns must use the kernel campaign runner. Building the runner does not need this answer; requiring it does, because it changes how every family runs campaigns.

## 5. Why S1 builds its own transport telemetry instead of OpenTelemetry

The diagnostic question behind HL-O-07 is where in the transport a call stopped. The candidates:
- the connection was never made;
- the request was never written;
- no response headers arrived;
- only keepalive comments arrived;
- tokens were flowing.

The standard OpenTelemetry httpx instrumentation (`opentelemetry-instrumentation-httpx`, read 2026-10-04) records one span per request. That span ends when the response headers are returned from `handle_async_request`, and it records no phase timings and nothing about the body or the stream. A hung call would appear as one long span ending in a timeout, which is what we already had.

Answering the question needs two things:
- httpcore's `trace` request extension, which gives connect, TLS, request headers and body, response headers, body and close;
- a tee over the response stream, which marks the first chunk, keepalives and the first content, reasoning or tool delta.

Both are the bulk of S1 and would be needed with OpenTelemetry too. What OpenTelemetry could replace is the storage and export layer, but:
- that layer assumes a collector or tracing backend, while campaigns run on laptops with file-based evidence;
- it would add runtime dependencies to the kernel.

S1 therefore writes local JSONL sidecars. They live under a hidden `.aeread-telemetry` directory, which publication manifests skip. They are read by `aeread provider-failures`.

If dashboards are wanted later, an optional exporter can map these records to OpenTelemetry spans; the field names should follow the `http.*` and `gen_ai.*` semantic conventions when that happens.

## 6. Delivery

| Slice | Content | Changes behaviour? | Status |
|---|---|---|---|
| S1 | Opt-in transport telemetry (`AEREAD_TRANSPORT_TELEMETRY_DIR`) and `aeread provider-failures` | No. Off by default; when on, results, events and receipts are byte-identical | Implemented; this PR |
| S2 | Streamed-call fixes (#226 post-merge findings 3-5) | Only streamed profiles; none exists | Spec written |
| S4 | Transport retries inside the attempt, with layered deadlines, a working clock and opt-in `transport_policy` | Opt-in only | Next |
| S5 | Per-key and per-route limiter, and the route breaker | Opt-in only | After S4 |
| S6 | Kernel campaign runner: evidence-first resume, budget reservations, gate protocol, missingness summary | New entry point | After S5; adoption pending |
| S3 | Profile-admission calibration of the deadlines | New fields in the admission artifact | Can follow S4 |

Each slice starts with a spec that is reviewed before implementation. Each is verified red-first, with mutation checks and the full bridged suite.

**Before any of this lands**, housing campaigns can cut most losses with contract changes alone:
- declare `transport` in `retryable_conditions` (and `timeout`, if the experiment owner accepts the selection risk);
- raise `max_consecutive_operational_failures` above 1;
- run one worker per route and key;
- size `timeout_seconds` from the full-trajectory gate;
- preflight each route with the exact request shape.

## 7. Review trail

**The design** went through six rounds of independent review: 27, 13, 9, 12 and 5 findings in the first five, then none open.

**The S1 specification** went through three rounds: 11, 7 and 5 findings. One round was answered by removing mechanisms rather than adding them: a watchdog thread and a `faulthandler` dump, which could block the interpreter.

**The S1 implementation** went through four rounds: 15, 11, 4 and 1 findings. Three were declined, each with a recorded reason:
- an exact patch-version pin. A later change removed version gating altogether: CI installs openai 3.x, which moved from httpx/httpcore to httpx2/httpcore2. Telemetry now resolves whichever pair the installed SDK uses and gates on capabilities, not version numbers. Its tests run under both openai 2.53 and 3.24, on Python 3.10, 3.11 and 3.12;
- a cold-import concern, because the SDK's own default client already imports `httpcore` on the calling thread;
- a family-level receipt fixture. It was first declined, then adopted, once it was shown that finalization depends on the runtime outcome.
