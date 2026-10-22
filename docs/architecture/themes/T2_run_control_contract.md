# T2: Run-control contract

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5 and is decided in [issue #317](https://github.com/aeread-org/AERead/issues/317); a ruling is recorded here with its date and source.

**Summary.** Output-token and wall-clock ceilings, retry and replacement rules, halt guards, balance limits and concurrency are set by hand in each campaign driver. Some are already sealed into the plan through agent profiles, others rest on kernel defaults or driver constants, and no single admission step requires or checks them. Cells are therefore lost to caps, timeouts and dead accounts, and the loss depends on the subject (GLM loses cells where Gemini loses none), which biases cross-subject contrasts. The direction is one declared run-control block per campaign, frozen into the plan identity and applied only by the controlled launcher (#292 is its first carrier; its adoption PR #293 is closed until #291 and #292 land). The theme ruling requested: may the declared run-control block, including how a replacement response counts (retry estimand N1), be mandatory for every new confirmatory campaign, and which estimand does it freeze.

Evidence and per-claim labels: [ledger](ledgers/T2_ledger.md) (E-numbers below). All source references are at `origin/main` `1e2ae367`.

## 1. Problem and root cause

**Root cause.** The controls that decide whether a cell is measured are not one declaration with one admission check. Three states coexist. Sealed today: agent profiles, with sampling, timeout and retry policy, are entries of the plan payload (`resolver.py:695-696,712`) `[read]` E27, and Housing declares a control contract (E12). Resting on a default or a driver constant: the 8x ceiling (E3), `provider_stream` (E6), halt streaks, concurrency. Unchecked: nothing requires a ceiling to be declared, sized, or consistent with the kernel, and no balance is read. The new block closes the third gap and moves the second into the first. Each driver sets them itself: `max_action_attempts=1` with `retryable_conditions=[]` in the datacenter profiles (E11), a Housing-only `RETRY_POLICY_V2` constant (E12), a private three-in-a-row stop in Housing against an unused kernel halt guard (E8), no account check before launch (E14), concurrency as a driver argument. The kernel supplies the mechanisms (length growth, halt guard, `account_fault`, `provider_stream`) but each is opt-in, and driver bytes are sealed into the plan, so a campaign gets a fix only by taking a new identity (E26, E27). No rule says how a ceiling is sized, so it is copied from a smoke of another model or run.

| Symptom | Where it shows | Evidence |
|---|---|---|
| Subject-dependent loss at a hand-set cap or timeout (windows differ). GLM: DC-O-08 11/32 (length); DC-O-12 25/128 (18 timeout, 7 length); DC-O-13 10/256 length plus 2 timeouts; DC-O-14 28/44 in the early window, final arm 37/72 not valid (17 length, 13 timeout, 7 other); DC-O-16 6/60 (5 length, 1 rejection). Gemini lost none in DC-O-08/12/13 | DC-O-08/12/13/14/16 (cluster G04) | E20 `[row]`; sizing from another run's smoke, no helper on main (#288 is a draft) `[read]` E17 |
| Arena `length` ends 12/12 cells at a 2048-token request | #135.d (G04) | E19 `[row]`; growth itself already exists, `execution.py:3315-3318` `[read]` E4; ceiling undeclared, 8x fallback `execution.py:995-1001,3738-3740` `[read]` E2, E3 |
| Timeout or transport error ends a cell or a range; replacement not declared as measurement policy | HL-O-04/11/12/13/14/19/20, DC-O-17/20/21/22 (G08) | E21-E23 `[row]`; `retryable_conditions` and attempts alone decide `execution.py:3849-3853` `[read]` E5 |
| Same-condition recovery differs per driver and per contract version (v1 stops a range at the first failure, v2 at three) | HL-O-19/20; `price_campaign.py:702-755` | `[read]` E12 |
| Halt guard exists and no family uses it | #264.a, #289.f, DC-T-08 (G21) | no importer outside `shared_runner/__init__.py:93-104` `[run]` E8; none of seven run sets used the CLI `[row]` E26 |
| Streaming declared by no profile | #264.b (G21/G04) | `[run]` E7; whether streaming cures the 76 s cut is unshown `[row]` E25 |
| Runs launched on an empty account: 214/348 cells HTTP 402; 36 cells in 20 s; CLI out of credits | DC-O-15, HL-O-21, CLI-O-01, #286.a (G22) | E24 `[row]`; no balance or key-limit reader `[run]` E14 |
| Pinned route removed or repriced; workers sharing a key hit rate limits; constant 76 s cut | P-O-05/06, HL-O-05/06/09/10, DC-O-18, DC-T-14 (G23) | E22, E25 `[row]` |

Two points that change the shape of the fix. First, Arena length growth and the profile ceiling are on main (E1-E4); the gap is how the ceiling is set and whether a campaign declares it, not new kernel logic. Second, #292 supplies a controller with a declared invocation-scoped cost limit, reserves, concurrency and a failure streak (what the limit guarantees is stated in section 2), and it records the effective ceiling and retry fields per cell (E15). It does not read a provider balance, does not size ceilings, does not set `provider_stream`, and does not state the replacement estimand.

## 2. Direction

**One declared run-control block, one launcher.** A campaign plan freezes a block with these parts, and the launcher enforces them. A change to any part is a new identity.

| Part | Declared in the plan | Enforced by | Exists today |
|---|---|---|---|
| Output ceilings | per-subject `max_output_tokens`, `max_output_tokens_ceiling`, `timeout_seconds`, `provider_stream`, each with its basis (the subject's own smoke output-length quantile and margin, recorded) | kernel executor (`_length_retry_ceiling`) and launcher admission refuses an undeclared ceiling | executor logic `[read]` E1-E3, E6; sizing basis: no |
| Replacement rule (N1) | per failure condition (`length`, `timeout`, `transport`, `empty_response`, `provider_choice_error`): which response is the measured one, and what a replacement is | executor retry decision; per-cell record of calls, attempts and cost | retry decision `[read]` E5; estimand: unruled |
| Halt | `max_consecutive_operational_failures`, account-fault stop | `run/halt.py` guard inside the launcher | `[read]` E9; adopted by no family |
| Spend and balance | declared spend limit with a stated guarantee (see below); balance and key-limit preflight with a refuse-below-projected-cost rule | launcher preflight, then #292 admission | #292: admission gate on known spend plus reserves, one invocation only, `[read]` E15; preflight: no |
| Sampling controls actually sent | declared `sampling_controls` and `provider_stream` match the request on the wire | client; launcher refuses a profile the client cannot honour | Arena client sends `temperature` unconditionally (`execution.py:2478`) and rejects streaming (`:2445-2448`) `[read]` E32 (#267.b); other clients guard `None` (`:1658`) |
| Concurrency and route | per-key worker cap below the provider limit; arm interleave when arms share an account; pre-launch strict probe of the pinned route | launcher; route probe | concurrency in #292 `[read]` E15; Housing refuses non-serial; probe and interleave: SOP only (E28) |

**What the spend limit guarantees today (E15).** #292's controller admits a cell only if known spend, active reserves and the next reserve fit the limit. It does not cap provider charges: a started cell can exceed its reserve and the controller stops after the fact (`campaign_known_cost_limit_exceeded`); known spend may be a lower bound when a call's cost is unknown; the limit is per invocation and its docstring says there is no resume or provider-dollar cap. Stronger guarantees (campaign-cumulative across invocations, a provider-side key limit) are not built and are listed in section 6 as an owner choice.

**What this replaces.** Per-campaign driver constants (Housing `RETRY_POLICY_V2`, datacenter `max_action_attempts: 1`), private halt streaks, hand-copied caps, and operator tracking of balances. The Housing v2 check that the kernel growth equals the declared growth (E13) is the right shape: the declaration is checked against the kernel.

**Compatibility.** `require_halt_rule(required=False)` lets a contract schema that predates a control stay unchanged (E9). Frozen identities keep their v1 controls; the block applies to the next identity of each family. No historical evidence is edited.

**Alternatives considered.**

| Alternative | Why not recommended |
|---|---|
| Keep fixing per ticket (raise the GLM cap, add a retry list per driver) | Each fix changes identity anyway, sets no rule for sizing the next cap, and keeps replacement semantics driver-specific; G04 and G08 show the same loss recurring across five campaigns |
| Make the kernel apply guards by default to existing identities | Changes sealed behaviour of frozen plans, which the identity rule forbids (E27) |
| Rewrite Arena length handling as a new state machine (G04 original scope) | Already on main (E4); it would duplicate it |
| Treat route and concurrency incidents as code defects | Several look like local egress or shared-key limits (E25); they need an SOP and a probe, not a kernel branch |

## 3. Scope

**In scope.** Clusters G04, G08, G21, G22, G23. Issues #286, #264 (a and b), #289 item f, #135.d (ceiling part), #267.b (sampling controls and `provider_stream` in the Arena client; handed to T2 by [T1 design](T1_call_outcome_design.md) `[read]`). PR #292, PR #293. Rows DC-O-08/12/13/14/15/16/17/18/20/21/22, DC-T-08, DC-T-14, HL-O-04/05/06/09/10/11/12/13/14/19/20, P-O-05/06, CLI-O-01 (quota part).

**Out of scope.**

| Item | Destination |
|---|---|
| Call-outcome typing, billing of provider calls, retries inside one attempt, terminal writer; same-attempt re-send witness (T1-D1) and the form of a recovery declaration for unknown-progress conditions (T1-D6, `retry_policy.unknown_progress_recovery`) | T1 (T2 builds on them). #267.a (completed invalid JSON kept as evidence) also stays in T1 |
| Reasoning-only replies (HL-O-08, HL-O-17 as a capability question), CLI refusal typing and credit-exhaustion 429 typing (N2, Q-10) | T1 |
| Plan-identity hashing granularity and driver-byte hashing | T3 |
| D4 resource comparability and #274 analysis policy | analysis themes, named in #293 body (E16) |
| HL-O-08 route change as new control | stays a new identity per D-42 `[record]` |

## 4. Already decided

| Item | Ruling | Label | Source |
|---|---|---|---|
| Landing order #246, #291, #292, #293; #248 after part-1 repairs | fixed | `[owner]` 2026-10-21 | [rulings register](ledgers/rulings_register.md) D-11 |
| Length growth strictly increasing under the explicit ceiling; cap or exhaustion ends in typed `length` | in force; implemented on main | `[owner]` 2026-09-10 | rulings register D-15; `execution.py:3713-3750` `[read]` |
| HTTP 402 is `account_fault`; halt rule read from the contract; unreached cells `not_attempted` | merged | `[merged]` (admin override, no non-author review) | rulings register D-19; `halt.py:40-79` `[read]` |
| Design doc: doubling to `max_output_tokens_ceiling`, "default: eight times the declared limit" | merged doc | `[merged]` | rulings register D-29 |
| Any other recovery needs a declared treatment; no framework default stands in | in force | `[owner]` 2026-10-21 | rulings register D-5, D-6 |
| HL-O-08, HL-O-19, DC-O-14 must not share one recovery rule | in force | `[owner]` 2026-10-21 | rulings register D-7 |
| A failed cell stays missing; changing control or route is a new identity | incident-log disposition | `[record]` | rulings register D-42 |
| Missingness never assumed ignorable; recovery is a declared treatment; stop on 401/402/403/quota-429 | author proposals; only 402 implemented | `[record]` | rulings register D-32, D-34, D-35 |

Still conflicting: C-8 (the implicit 8x ceiling against the owner's "explicit ceiling"), recorded as Q-6.

## 5. Theme ruling requested

**Question.** Should every new confirmatory campaign freeze a declared run-control block (ceilings with their sizing basis, replacement rule per failure condition, halt, spend limit with balance preflight, concurrency and route) in its plan and run only through the controlled launcher, and what does the block say about how a replacement response counts?

Sub-questions (each is an existing open item):

- **2a. Retry estimand (N1, Q-8).** Which responses stay measured outcomes and which may be replaced, for `length`, `empty_response`, `timeout`, `provider_choice_error`.
- **2b. Ceiling semantics (Q-6, C-8).** Is the declared ceiling the explicit `max_output_tokens_ceiling` only, the sampling cap, or the historical 8x default.
- **2c. Mandatory launcher (Q-16).** Is the kernel campaign runner / controlled launcher required for new confirmatory campaigns: yes, no, or only new campaigns.

Estimand, ceiling meaning and launcher scope are three separate questions; no answer to one implies another.

**2a. Retry estimand: options.** Existing practice is replacement, not first-response: Housing v1 retries `length`, `rate_limit`, `provider_5xx`, `empty_response` with 4 or 8 attempts (`price_campaign.py:689`, `backend_campaign.py:449-453`), and v2 adds `timeout`, `transport` (E12, E31) `[read]`. Datacenter profiles seal one attempt and no retries (E11). So A or C is a new measurement rule, not a continuation, and needs first-response recording that does not exist yet.

| Option | Rule | Effect on measured results | Frozen identities | Cost and work |
|---|---|---|---|---|
| A. First response is the measured outcome | A replacement is recorded as exposure and not as the measured answer; a lost first response is typed missingness, reported by subject | No survivor selection; reported loss stays differential (GLM vs Gemini) and has to be shown, not repaired | Housing v1/v2 evidence measured replaced responses; under A it is not comparable. Datacenter v1 (one attempt) already reports first responses | Medium; needs per-cell recording of first response, calls and attempts (#292 starts the per-cell fields) |
| B. Declared replacement is the measured response | The estimand is the response after a declared recovery policy (per condition: retry set, growth, bound) | Recovers more cells; the contrast is between subjects under the same recovery policy, and completion after growth is not evidence of an equivalent condition (HL-O-17 reading) | Housing v1/v2 are already of this kind; other families adopt with a new identity | Higher; per-condition table, bounds and cost for each replacement need review (T1-D6 form) |
| C. Per-condition mix | A for capability-bearing conditions (`length`, `empty_response`), B for transient service conditions (`timeout`, `transport`, `rate_limit`) | Mixed: transient faults repaired, capability losses reported | No existing instance: v1 and v2 replace `length` and `empty_response` too. New identity everywhere | Medium to high; the owner must name the condition split, because only the owner can |

The owner has not enumerated these options (rulings register Q-8). The recorded owner position is that replacing only failed cells "can select survivors" (E30).

**2a also covers corrective feedback (Q-15).** EconEvals returns a validation error to the model inside the same attempt, bounded by the period's round budget, and continues (`econevals/live.py:468-482`, `rounds_used < budget` at `:439-441`) `[read]` E33. This is not an outer retry, so the table above does not govern it. Options: (i) corrective rounds are part of the task; the measured result is the final answer and the declaration states the round bound and records the first invalid response and every correction; (ii) a format failure is a measured failure; the first invalid answer is the outcome and later rounds are exposure. Under (ii) a first-response rule (A or C) would otherwise be undone by repair inside the attempt. Q-15 is not enumerated beyond these two framings in rulings register.

**2b. Ceiling meaning (Q-6, C-8): options.** Example: cap 4,096 and no declared ceiling; the kernel grows to 32,768 (E2, E3).

| Option | Consequence for a `length` stop |
|---|---|
| (a) Explicit declared `max_output_tokens_ceiling` only | A stop below any declared ceiling is not attributable to the model at its ceiling; a profile with no ceiling has no model-attributable `length`. Needs admission to refuse undeclared ceilings for new identities |
| (b) The sampling cap | `length` at 4,096 is the model's; growth to 32,768 becomes a replacement and falls under 2a |
| (c) The historical 8x default | Stopping at 4,096 reads as harness-below-32,000, so #264's rule ("model's unless the cap was below the declared ceiling") makes it harness-attributed; changes attribution of existing EconEvals rows |

**2c. Launcher scope (Q-16): options.**

| Option | Consequence |
|---|---|
| Yes, all confirmatory campaigns | Frozen identities cannot be re-run under their sealed drivers; every family pays a migration before its next confirmatory run |
| Only new campaigns | Frozen identities keep sealed behaviour (driver bytes are in the plan, E26, E27); two run paths coexist until the old identities retire |
| No | Ceilings, halt and replacement stay per-driver; each campaign needs its own N1-style ruling |

**Recommendation (a recommendation, not a ruling; each line stands alone).** 2a: Option C, with Option A for any condition the declaration does not name, so that no framework default decides (D-6); the condition split is the owner's to name, and corrective rounds should be option (i) with the bound declared. 2b: (a), with undeclared ceilings refused at admission for new identities and the 8x fallback kept only for frozen identities. 2c: "only new campaigns".

Consequence of ruling "no" to the block: ceilings and replacement semantics stay per-campaign and each new campaign needs its own N1-style ruling before it can be read.

## 6. Issue-level decisions that follow

| Decision | Decider | Blocks | Issue exists |
|---|---|---|---|
| Corrective feedback in EconEvals: task interaction or repair (Q-15, sub-question 2a) | Chenyu | EconEvals confirmatory reading; first-response rule | Open in rulings register; no issue |
| Sampling controls honoured by the Arena client: omit `temperature` when declared unavailable, reject or implement `provider_stream` (#267.b; design drafted, no owner ruling, rulings register Q-14) | Chenyu (kernel); Yuchen owns the issue | #264 adoption, Refund V2.5 | #267 (board Theme T1; #267.b is T2's by [T1 design](T1_call_outcome_design.md)) |
| Spend-limit guarantee: admission gate per invocation (#292 today), campaign-cumulative across invocations, or provider-side key limit; and how unknown call cost counts | Chenyu (kernel) | #286 scope, #293 reopening | #286 |
| N1 estimand per condition (sub-question 2a) | Chenyu | every confirmatory run's reading; HL-O-17, HL-O-19, DC-O-14; Q-15 | Draft unposted (rulings register Q-8) |
| Declared-ceiling semantics (Q-6, C-8) | Chenyu | length attributions; #264 wording "model's unless cap below ceiling" | Open in rulings register; no issue |
| Is `timeout` retryable for the next frozen identity (HL-O-19) | Chenyu, under 2a | Housing next identity; DC-O-12 next identity | Row note only |
| Launcher mandatory for new confirmatory campaigns (Q-16) | Chenyu | #264 adoption, #289.f | Asked 2026-10-04 (issue #226), no answer |
| Ceiling sizing rule: quantile of the subject's own smoke output length, margin, recorded in the plan | Zeyu proposes (SOP), Chenyu approves | G04 next identities; DC-O-08/12/13/16 re-runs | #288 draft carries SOP calculations; the ceiling rule itself: no issue |
| Balance and key-limit preflight, spend limit as a contract field (provider reads: OpenRouter key/limit, CLI quota) | Chenyu (kernel) | #286 | #286 |
| `provider_stream` declaration for reasoning-heavy profiles, and chunk-count evidence for the 76 s cut | Family owners; Zeyu for evidence | #264.b, DC-T-14 | #264 checklist |
| Halt-guard adoption per family on the next identity | Family owners | #264.a | #264, #210 (datacenter) |
| Per-key worker cap, arm interleave, route probe and route changelog | SOP owner | HL-O-09/10, P-O-05/06 | #288 (interleave); route probe: no issue |
| Whether DC-O-14 (over 120,000-token deliberation moves) needs a streaming/checkpoint harness | Chenyu | DC-O-14 arm | #223 mentioned in cluster |
| Account exhaustion as operator fault in attribution (Q-5) | Chenyu | failure registers | Open in rulings register |

## 7. Delivery

| Step | What | Owner | Lane | Depends on | Can start now |
|---|---|---|---|---|---|
| 1 | Land #291, then #292 in the owner's order | Zeyu; non-author approval by Chenyu | kernel | D-11 | In flight; #291 open, #292 draft |
| 2 | Post N1 and the Q-6/Q-16 questions as one ruling request | Zeyu drafts | n/a | this charter | Yes |
| 3 | SOP: ceiling sizing helper and rule, per-key worker cap, route probe and changelog, arm interleave | Zeyu | SOP/tooling | #288 draft; no kernel needed | Yes |
| 4 | Kernel: declared run-control block validated at admission (undeclared ceiling refused for new identities); balance and key-limit preflight; spend-limit guarantee; #267.b sampling-control fix (Yuchen's issue) | Zeyu; Yuchen for #267.b | kernel | steps 1 and 2 answered; #286 approach and spend-guarantee choice to Chenyu | After steps 1 and 2. Can start now: drafting the #286 approach and the spend-guarantee options |
| 5 | Reopen and rebuild #293 on main; family adoption of halt guard, `provider_stream` and the block per next identity | Zeyu and Yuchen (Refund, Arena) | family | steps 1, 4 | After steps 1 and 4. Can start now: only preparing the branch from the closed #293 |
| 6 | Re-size ceilings from each subject's own smoke for the next datacenter and Housing identities | family owners | family | steps 2, 3 | Smoke can start now (no paid calls without approval) |
| 7 | Chunk-count probe for DC-T-14 in the first campaign that declares streaming | Zeyu | family | step 5 | After step 5 |

Nothing in steps 3 and 6 changes a frozen identity. Family adoption always costs a new identity, so each family batches its adoption with its next planned identity.

## 8. Not verified

- Provider balance and key-limit endpoints (OpenRouter, CLI quotas): no network, so what a preflight can read is unchecked.
- The incident rows (DC-O, HL-O, P-O, DC-T-14) are `[row]`; most DC-O rows are on non-PR branches (lower confidence). No cell counts were recomputed from evidence.
- Whether #292's controller composes with #291 and #248 as claimed: the 267-test composition result is from the PR body, not rerun.
- The unposted N1 draft was not read directly; its content comes through rulings register Q-8 and the case-review citations.
- Whether streaming prevents the 76 s cut and whether it removes the 300 s timeouts: no streamed receipt exists.
- Whether any branch other than main declares `provider_stream` or a ceiling.
- Cost and schedule estimates for steps 4 and 5 are not given; they have not been sized.
