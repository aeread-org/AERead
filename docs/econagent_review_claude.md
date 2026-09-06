# econagent_v1 adapter — second-reviewer adversarial pass (Claude)

Scope: diff of `AERead/.worktrees/econagent` vs `origin/main` (26 files, ~7.4k
lines). Read `docs/econagent_adapter_spec.md` in full, `docs/research/verifier_taxonomy.md`
in full, then every changed source/test/case file. Independently re-derived
upstream facts against the actual pinned checkout at
`/Users/sunzeyu/Documents/econ benchmark/upstream-econagent` (git HEAD =
`bfada091eaa1fc8490f79d74ccc9467efad8875f`, matches pin `bfada09`), recomputed
`sha256` of `config.yaml`/`data/profiles.json` independently and diffed against
`cases/econagent_v1/pins.json`, re-ran `cases.import_all_cases` against the real
upstream checkout and diffed the result byte-for-byte against every committed
case file, and executed the actual test suite (`tests/test_econagent_*.py`)
against the real, already-provisioned bridge venv.

**Empirical result: 86/86 tests passed, 0 skipped**, i.e. the bridge-gated
goldens, replay, parity, and e2e suites all actually ran against the real
upstream engine in this environment, not merely against a hand-derived fixture.
Freshly-recomputed `pins.json`/case files/`scenario_manifest.json` match the
committed files byte-for-byte, and independently-computed file hashes
(`shasum -a 256 config.yaml data/profiles.json`) match the pinned digests
exactly. Gate-1 corpus admission (digests, dedup, no silent resampling) is
clean — no findings there.

## Summary

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| WARNING (major) | 2 |
| SUGGESTION (minor) | 2 |

No critical defects found. The adapter is unusually well-instrumented (mutation
tests for parity, replay-tamper, and Gate-1 dedup all present and passing) and
the "milestone correction" trail in the spec is honest about real gaps found
along the way. The two WARNING items below are genuine verifier/taxonomy
labeling and replay-completeness concerns, not fabricated evidence or
hidden-skip issues.

---

## WARNING 1 — `econagent_macro_trajectory` is declared `comparative`/`baseline_delta` with no comparator, which is exactly the mislabeling `docs/research/verifier_taxonomy.md` §6 warns against

**File:** `src/aeread_families/econagent_v1/measurement.py:194-235` (`build_macro_trajectory_leaf`), also `docs/econagent_adapter_spec.md:346-354`.

`docs/research/verifier_taxonomy.md` §6 defines `comparative`/`baseline_delta` as:
"Compare native outcomes with a named, versioned, executable policy under the
same design," and explicitly requires "The comparator, opponent population,
matching rule, and cluster structure are part of the estimand." Leaf 3 here has
**no comparator at all** — it is a pure descriptive time series (GDP-proxy,
price level, unemployment-proxy) with no baseline policy, no paired run, no
opponent. The code's own docstring admits this outright:

> "`reference_kind="baseline_delta"` is the closest-fitting `comparative`
> reference kind in the kernel's own grammar; ... there is no comparator to
> bind here at all this pass."

This is precisely the failure mode taxonomy §6 exists to prevent: "A win rate
against one opponent is not a universal capability score" — here there isn't
even a win rate, just a raw number being forced into the `comparative` family
because the kernel's `ReferenceSpec` grammar (`src/aeread/shared_runner/
measurement.py:27-57`) offers exactly five families and none has a clean
"descriptive value, no reference at all" slot. Taxonomy §5.1's
`objective_value_only` ("Only the native objective value is available.
Descriptive value; no optimality claim") is the far better semantic fit for
what this leaf actually is, but is correctly excluded here because it lives
under `objective_reference`, which requires a declared feasible policy class/
objective/bound (`ObjectiveScopeSpec`, `measurement.py:193-221`) that EconAgent
genuinely doesn't have — and the spec is right to avoid that framing error.

**Failure scenario:** a downstream consumer of the receipt (a leaderboard
builder, an aggregator across families) sees `verifier_family: comparative`,
`reference_kind: baseline_delta` and reasonably infers there is a named
baseline being compared against, per the taxonomy's own contract for that
reference kind — there isn't one, and nothing in the typed schema (only a
docstring) discloses that. This is a schema-level ambiguity, not a coding
mistake local to this adapter: the same tension would recur for any future
family with a purely descriptive diagnostic and no objective/comparator. Worth
raising to whoever owns `docs/research/verifier_taxonomy.md`/`aeread/shared_runner/
measurement.py` — either add a `descriptive_only`/`objective_value_only`-shaped
option outside the objective-scope requirement, or accept this as a documented,
known misfit rather than a silently-taken shortcut. As shipped, the risk is
contained by the surrounding prose (spec §2/§6 state the limitation loudly,
`build_macro_trajectory_leaf`'s docstring states it again), but the machine-
readable `VerifierSpec` itself does not carry that caveat.

---

## WARNING 2 — Offline replay's tax-bracket leaf accepts recorded responses without checking they correspond to the replayed episode's own incomes

**File:** `src/aeread_families/econagent_v1/replay.py:237-239` (`RecordedEconAgentBridge.recompute_tax`), used from `measurement.py:565-591` (`score_tax_bracket_arithmetic`) via `replay.py:568-575` (`score_replayed_episode`).

`RecordedEconAgentBridge.recompute_tax` is:
```python
def recompute_tax(self, incomes: Mapping[str, float]) -> Any:
    del incomes
    return self._next("recompute_tax")
```
It discards the `incomes` argument entirely and returns the next recorded
response purely by call order. `score_tax_bracket_arithmetic` (the function
being replayed) *derives* `incomes` from the replayed episode's own
`dense_log["PeriodicTax"][...]["income"]` and passes that into
`bridge.recompute_tax(incomes)` per agent-month — but during replay, that
derived value is never compared against what was actually recorded. The
replay-fidelity claim for leaf 2 is therefore: "we asked for `recompute_tax`
the same number of times, in the same order" — not "we asked with the same
inputs the original run asked with."

This is a real, not hypothetical, gap: `replay_and_verify`'s own docstring
(`replay.py:612-619`) documents a supported mode where `original` is `None`
("a genuinely offline replay from a previously written record, with no
original run in memory") — in that mode `comparison` is `None` and
`StateComparison.final_state_content_matches` (the check that *would*
independently catch a divergent replayed `dense_log`, and hence divergent
incomes) never runs at all. In that mode, `score_replayed_episode`'s leaf-2
result is the *only* check exercised, and it cannot detect a dense_log/income
divergence, because the double it depends on ignores its own input.

**Failure scenario:** a future bug in `EconAgentV1Plugin.step()`/
`compute_budget_identity_residuals` causes the replayed episode's
reconstructed `dense_log["PeriodicTax"][...]["income"]` to silently diverge
from what generated the original recorded `recompute_tax` responses (e.g. an
off-by-one in month indexing introduced later), while the *call count/order*
stays identical (which it will, since the loop structure is unchanged). Run
via the documented no-`original` offline-replay path, `score_replayed_episode`
would report `tax_bracket_arithmetic.status == "ok"` and reuse the stale
recorded `tax_due` values against the new (wrong) incomes, silently passing a
leaf whose input no longer matches its own trace. Today's actual test coverage
(`tests/test_econagent_replay.py`) always supplies `original` in-process, so
this gap is not currently exercised end-to-end, but it is directly reachable
through the module's own documented, supported API. Recommend: have
`RecordedEconAgentBridge.recompute_tax` assert its `incomes` argument equals
the recorded call's own `args["incomes"]` (it already stores `args` on
`RecordedBridgeCall`, so the data needed for this check already exists and is
simply unused) rather than silently `del`-ing it.

---

## SUGGESTION 1 — §2's verifier table claim ("all six terms read ... never recomputed independently") is stale against milestone-2 correction 3

**File:** `docs/econagent_adapter_spec.md:344` vs `docs/econagent_adapter_spec.md:175-189` and `measurement.py:308-340`.

Spec §2's verifier-declaration table states, for `econagent_budget_identity`:
"all six terms read from the executed upstream state/dense_log, never
recomputed independently." Milestone-2 correction 3 (same document,
lines 175-189) and `compute_budget_identity_residuals`'s own docstring both
correctly explain that the sixth term, `saving_interest`, is *not* read from
anywhere — it is derived as the closing residual of the other five terms, and
the leaf then checks a property of that residual (zero off-boundary, ≥0 on a
`world.period` boundary month) rather than an independent reading. I verified
this is a real, falsifiable, non-tautological check (confirmed `world.period
= 12` from the pinned `config.yaml`, so 11/12 or all 6/6 or all 3/3 months in
the three pilot scenarios are checked at the strict "must equal exactly zero"
level) — this is not a defect in the check itself. It is, however, a
self-inconsistency in the spec's own §2 summary table versus its own later
correction, which is exactly the kind of "derived field presented as if it
were an independently-read term" wording this review was asked to check for.
A reader who stops at §2 (the actual verifier-declaration section named in the
title) would be misled about how `saving_interest` is obtained; only a reader
who continues to milestone-2 correction 3 gets the accurate account. Recommend
updating §2's table wording in the same commit that next touches this file
(the project's own stated convention), e.g. "five terms read verbatim; the
sixth (`saving_interest`) is derived as the closing residual and checked
against its own documented invariant, not read directly."

## SUGGESTION 2 — Golden 3(a)'s "no protected state changed" claim is proven only against a hand-wired loop, not the real scheduler path

**File:** `tests/test_econagent_goldens.py:271-316` (`test_golden_invalid_action_never_reaches_step_and_touches_no_protected_state`).

I traced the real enforcement path in `src/aeread/shared_runner/scheduler.py`
(`_request_action`, line ~589: `if not valid and phase.invalid_action_policy
== "reject": raise SchedulerContractError(...)`) and confirmed structurally
that the real scheduler *does* refuse before ever calling `_step`/`plugin.step`
when any seat's action is illegal — so the golden's claim is true of the real
system, not just of the hand-rolled loop in the test. But the golden itself
(per its own docstring, "Simulate 'if this illegal/unauthorized action had
incorrectly been forwarded to step()'") only exercises `EconAgentV1Plugin.step`
directly with a hand-crafted incomplete-actions mapping, never
`aeread.shared_runner.scheduler.run_episode` itself. This is honestly labeled
as a defense-in-depth check, not a claim about the real scheduler path, so it
is not a false claim — but given this family already has a real e2e suite
(`tests/test_econagent_e2e.py`) that drives episodes through `run_episode`,
Golden 3(a)'s state-non-mutation claim would be materially stronger (and
future-proofed against a scheduler behavior change) if it also asserted
`SchedulerContractError` fires via one real `run_episode` call with a
deliberately-illegal seat response from a custom `ResponseSource`, rather than
relying solely on the hand-wired loop plus a separate, structural reading of
`scheduler.py`.

---

## What I did NOT find

- No judge-dependent leaf mislabeled as deterministic — all three leaves are
  genuinely computed deterministically (pure arithmetic over dense_log +
  fresh, RNG-free bracket recomputation); `evaluation_class="deterministic"`
  is accurate for all three.
- No fabricated/faked golden — all five §4 goldens are real, run against the
  real bridge in this environment (verified by executing the suite), and the
  "invalid action" golden's two layers (kernel-side reject-before-step,
  bridge-protocol-side ignored-extra-field) are both genuine, falsifiable
  checks, not tautologies (I independently confirmed
  `econagent_bridge_driver.py::_op_step_month` truly ignores any
  caller-supplied `"actions"` field on the wire).
- No hidden skip masking an unrun claim — every skip in every test file is
  gated on `_require_bridge()`/upstream-checkout presence with an explicit
  reason string, and in this environment all bridge-gated tests ran for real
  (86/86 passed, 0 skipped).
- Gate-1 corpus admission is clean: recomputed hashes match committed
  `pins.json` exactly; a fresh `import_all_cases` run reproduces every
  committed case file and `scenario_manifest.json` byte-for-byte; dedup logic
  (same-shape `world_seed` collision) is correctly scoped per milestone-1
  correction 6 and has a real mutation test
  (`test_import_all_cases_rejects_a_same_shape_world_seed_collision`).
- Replay for the *state/terminal/outcome* surface (as opposed to the leaf-2
  tax-bracket point raised in WARNING 2) is honest and genuinely
  re-executes the adapter's own orchestration code (`EconAgentV1Plugin.step`,
  `measurement.py` scorers) against recorded bridge responses, with a real
  tamper/mutation test (`test_replay_diverges_when_a_recorded_bridge_response_is_tampered_with`)
  proving the comparison is not vacuous.
