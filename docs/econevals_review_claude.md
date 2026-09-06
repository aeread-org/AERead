# econevals adapter — second-reviewer findings (Claude)

Scope: `docs/econevals_adapter_spec.md` + full diff vs `origin/main` (branch
`zeyu/econevals-adapter`, 11 commits, working tree clean). Focus per
assignment: QC Gate-2 compliance (five goldens), verifier-declaration
correctness against `docs/research/verifier_taxonomy.md`, replay honesty, Gate-1
corpus admission.

Overall: the Gate-1 corpus-admission machinery (digests, double-generation
byte-compare, typed exclusions, manifest dedup) is solid and well-tested.
The verifier declarations are internally consistent with
`verifier_taxonomy.md` (nothing judge-dependent is mislabeled deterministic;
the numerical-tolerance caveat for pricing is explicitly flagged, not
hidden). But two claims central to this milestone's own stated deliverable —
"the five QC Gate-2 goldens" and "offline replay" — do not hold up under
direct reading of the code, and neither deviation is flagged anywhere in the
adapter's own (otherwise very disciplined) habit of writing down every other
known deviation.

## CRITICAL

### 1. "Offline replay" silently requires a live upstream bridge subprocess every period — contradicts the spec's own explicit requirement, and the deviation is undocumented

`docs/econevals_adapter_spec.md:181-186` (section 5, "Offline replay" bullet)
states, unambiguously: *"Network disabled, no bridge subprocess spawned...
Only Gate 1's admission-time and parity-time checks call the bridge; replay
reads sealed evidence only, exactly as tau3's replay reads recorded judge
verdicts rather than re-invoking a judge."*

The actual implementation does the opposite. `replay.py`'s own module
docstring says so plainly (`src/aeread_families/econevals/replay.py:9-13`):
`EconevalsPlugin.step()` "already re-executes every recorded tool call
through `dispatch_read_only`/`dispatch_submit` (which delegate to the pinned
upstream bridge for the one terminating submit call per period)." Tracing
the call chain: `replay_episode()` (`replay.py:212-242`) calls
`run_episode(..., plugin=plugin, ...)`, which drives the SAME
`EconevalsPlugin.step()` (`environment.py:462-504`) that unconditionally
calls `self.dispatch_submit(...)` for every period's last tool call, which
in turn calls `self._require_bridge()` and a real subprocess round-trip
(`environment.py:697-703` procurement, `733-737`/`750-754` scheduling,
`812-815` pricing). `tests/test_econevals_replay.py:264-271` confirms this
concretely: replay is exercised by constructing a **second, independent live
`EconevalsBridge`/`EconevalsPlugin(bridge=replay_bridge)`** and handing it to
`replay_episode` — there is no bridge-free code path anywhere.

Consequences this creates, none of which are mentioned in
`docs/econevals_adapter_spec.md` section 6's build notes or
`docs/econevals_adapter_status.md`'s "Known limits" (both of which otherwise
diligently record every other known deviation):

- A sealed episode record cannot actually be replayed once the pinned
  bridge venv/upstream checkout/Gurobi license becomes unavailable — the
  entire point of "sealed evidence" (auditable independent of the original
  run's infrastructure) is defeated for this family.
- Replay cost is not reduced vs. a live run: it still pays the ~1s/call
  (procurement) / ~0.4s/call (pricing) / ~0.2s/call (scheduling) bridge
  round-trip per period that `docs/econevals_adapter_status.md:73-76` itself
  measures for a *live* run — "offline" here does not mean "cheap" or
  "network/subprocess-free," it only means "no model call."

**Failure scenario:** eight months from now the bridge venv is deleted (or
the free Gurobi license changes, or the upstream checkout is unreachable)
and someone tries to replay a previously-sealed procurement episode to
confirm a reported score. `dispatch_submit` calls `self._require_bridge()`,
which raises `RuntimeError("econevals execution requires a provisioned
EconevalsBridge")` — the "offline, sealed-evidence-only" replay this
family's own spec explicitly promises simply cannot run, and nothing in the
docs warned that this was the actual contract.

This is either a spec bug (the promise in section 5 was never achievable
given `step()`'s cross-check design and should be corrected) or a code bug
(replay was supposed to skip re-invoking the bridge and only verify against
sealed `tool_executions`, the way `tau3`'s replay reads recorded judge
verdicts without re-invoking the judge). Either way, the current state is an
undocumented, load-bearing gap between what is claimed and what is shipped.

### 2. None of the "five QC Gate-2 goldens" are real episodes — they never touch `parse_action`/`legal`/`step`/`run_episode`, are never sealed, and are never offline-replayed

`docs/econevals_adapter_spec.md:170-178` frames the five items as "One
scripted (gold-trajectory) **fixture**" per category, and section 5's
"Offline replay" bullet explicitly requires: *"replay each of the 5 goldens
from its sealed episode record."*

What's actually implemented, in `tests/test_econevals_measurement.py`, is
five ordinary unit tests against `measurement.py` alone:

- Golden 1 (`:142-160`), golden 2 (`:171-207`), golden 3 (`:219-249`),
  golden 4 (`:279-293`), golden 5 (`:348-397`) each hand-construct a Python
  `attempt` dict (and, for golden 5, a hand-built `instance` dict) and call
  `EconevalsScorer.score_terminal_state({"attempts": [attempt]})` directly.
- None of them call `plugin.parse_action`, `plugin.legal`, `plugin.step`, or
  `aeread.shared_runner.scheduler.run_episode`.
- None of them produce a `RecordedEpisode`/sealed evidence record, and
  nothing in `tests/test_econevals_replay.py` ever replays any of these five
  specific scenarios (that file's only live scenario is a generic 3-period
  uniform-price pricing episode, unrelated to any of the five golden
  categories).

So the explicit spec requirement "replay each of the 5 goldens from its
sealed episode record" is not implemented for any of the five goldens.

This directly answers the assigned question — **"does the invalid-action
golden actually prove no protected state changed?"** — in the negative:
`score_terminal_state` is a pure function over an already-assembled dict; it
has no way to observe, and this test suite never checks, whether
`family_case["generated_instance"]` (e.g. `budget`/`menu`), `state["period"]`,
or `state["attempts"]` end up correct/unmutated after golden 3's actual
over-budget submission is run through the real `dispatch_submit`/`step()`
path. (Two adjacent, narrower scenarios — golden 3's "companion" unknown-
offer-id case and golden 4's malformed-scheduling case — do have separate
environment-level tests in `tests/test_econevals_environment.py:320-351` and
`:393-423` that exercise `step()` for real and would catch a tool-replay
mismatch; but golden 3's actual spec'd scenario (the over-budget
allocation), golden 1, golden 2, and golden 5 have **zero** environment-level
coverage.)

**Failure scenario:** a future refactor of `_submit_procurement`
(`environment.py:653-714`) accidentally introduces an aliasing bug that
mutates `family_case["generated_instance"]["budget"]` in place when handling
an infeasible/over-budget submission. Nothing in the test suite would catch
it: golden 3 bypasses `_submit_procurement` entirely by hand-typing the
`attempt` dict `_submit_procurement` is supposed to produce, and no test
anywhere asserts that `generated_instance` is unchanged before/after any
submission (checked by grep: no such assertion exists in
`tests/test_econevals_environment.py`).

The commit that introduced these tests is literally titled *"add the five QC
Gate-2 goldens and component parity checks"* (`f2ab537`), so this is an
affirmative compliance claim, not an incidental gap.

## MAJOR

### 3. `conftest.py`'s bridge-required skip detector has an incomplete marker list for econevals — a documented failure mode the project has hit before

`conftest.py:11-16` explains the exact hazard this mechanism exists to
close: *"Both ways a bridge-gated test can go unrun belong in one family's
markers tuple: no interpreter that can import upstream, and (where
applicable) no upstream checkout to import at all. Matching only the first
left the second silent, which is the same hole one level up."* The `tau2`
entry (`conftest.py:19-28`) accordingly carries two markers. The `econevals`
entry (`conftest.py:29-35`) carries only one: `"pinned upstream econ-evals
Python interpreter"`.

But `tests/test_econevals_cases.py:79-82` gates
`test_module_sha256_table_matches_the_checkout_on_disk` — the one test that
actually re-verifies the seven pinned module hashes (`cases.MODULE_SHA256`)
against a live upstream checkout on disk — behind a *separate*
`pytest.mark.skipif(not _upstream_available(), reason="pinned upstream
checkout not found")`. That reason string does not match the one marker
econevals has, so this specific test's skip is invisible to
`pytest_terminal_summary`'s `AEREAD_ECONEVALS_BRIDGE_REQUIRED=1` gate.

Compounding this: `tests/test_econevals_cases.py:30` hardcodes
`UPSTREAM_ROOT = Path("/Users/sunzeyu/Documents/econ benchmark/upstream-econevals")`
with no environment-variable override, unlike the established
`tau2`/`tau3_retail` convention (`_upstream_root()` reads
`AEREAD_TAU2_UPSTREAM_ROOT` first, falling back to a default) — so a CI
machine with a different layout has no way to point this one test at the
right checkout even if it wanted to.

**Failure scenario:** CI sets `AEREAD_ECONEVALS_BRIDGE_REQUIRED=1` to certify
that the pinned module-hash table is still honest. The bridge venv/
interpreter resolves fine (so every other bridge-gated econevals test runs
for real), but the hardcoded upstream-checkout path doesn't exist on that
machine. `test_module_sha256_table_matches_the_checkout_on_disk` silently
skips; the terminal-summary hook never flags it (its marker string doesn't
match); the run reports green. The one test verifying "the pinned hashes in
`cases.py` still describe the code that actually runs" never ran, and no one
is told — the exact "skips hide unrun claims" failure mode this project has
already been burned by once, reproduced here for a different test.

## MINOR

### 4. Golden 1's own test is tautological in isolation

`tests/test_econevals_measurement.py:142-160`: `attempt["profits"]` is
copied directly from `gold_optimum["profits_by_period"][period]` — the same
array `score_pricing` sums to produce `v_star`. So
`objective.primary.value == v_star` holds by construction regardless of
whether `get_monopoly_prices`/`get_profits` were ever correctly invoked for
this instance; the test's own comment concedes "No bridge call is needed to
construct this golden" and defers real verification to the adjacent
`test_parity_pricing_profit_matches_an_independent_bridge_call`
(`:407-423`), which does independently re-derive profits via a live bridge
call. Not a standalone defect (the parity test does supply real evidence),
but golden 1 alone proves nothing about upstream's actual pricing logic —
worth not citing it in isolation as evidence of "gate pass and objective
pass within tolerance" the way spec section 4 item 1 implies.

### 5. Hardcoded, machine-specific absolute paths with no env-var override

`src/aeread_families/econevals/econevals_bridge.py:43-45`
(`DEFAULT_BRIDGE_VENV`) and `tests/test_econevals_cases.py:30`
(`UPSTREAM_ROOT`) are literal paths under `/Users/sunzeyu/...`. The bridge
venv path is at least overridable via `$AEREAD_ECONEVALS_BRIDGE_PYTHON`; the
test file's `UPSTREAM_ROOT` is not overridable at all (contrast
`tau2`/`tau3_retail`'s `_upstream_root()`, which reads
`AEREAD_TAU2_UPSTREAM_ROOT` first). Portability/CI concern, feeds finding 3.

## What looked solid (no manufactured findings here)

- **Gate 1 corpus admission**: `cases.py`'s double-generation byte-compare
  (`_canonical_generator_json`, `sort_keys=True, default=str`), typed
  `CaseExclusion`/`CorpusAdmissionError` (never a silent drop), and
  `build_corpus(strict=True)` failing loudly are all exercised by
  `tests/test_econevals_cases.py`, including a byte-for-byte cross-check of
  the checked-in 28-instance corpus against a fresh build
  (`test_checked_in_corpus_matches_a_fresh_build_byte_for_byte`). Spot-check
  of the 28 on-disk case files confirms unique `case_id`s and 28 distinct
  `content_sha256` digests (no collisions, no dedup failures).
- **Verifier declarations vs. `verifier_taxonomy.md`**: nothing
  judge-dependent is labeled deterministic (there is no `rater_judge`
  anywhere in this family); pricing's tolerance-based numerical optimum is
  explicitly flagged as a documented limitation (spec section 6) rather than
  presented as bit-exact; the gate/objective split is reported as a genuine
  vector (`(ScoreEnvelope, ScoreEnvelope | None)`), never collapsed into one
  scalar; `headroom_capture` is deliberately never computed, matching
  taxonomy section 5.3's warning.
- The `MeasurementLeafSpec.__post_init__` id-matching bug found against the
  literal spec text (`objective_id` vs `estimand_id`) was caught and fixed
  by the authors themselves and documented as a spec-prose slip, not hidden.

