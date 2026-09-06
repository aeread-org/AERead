# econevals adapter — review disposition

Fix pass against the second-reviewer read in `docs/econevals_review_codex.md`
(recovered from that reviewer's transcript after this disposition was
written, in `c866b50d` on origin/main; it declares 0 findings but carries
nine prepared findings that remain un-dispositioned here) and
`docs/econevals_review_claude.md` (present, 5 findings: 2 CRITICAL, 1 MAJOR,
2 MINOR). Every finding below was independently
re-verified against the code before any fix was made. All 5 are about the
econevals adapter's own code/docs (`src/aeread_families/econevals/`,
`docs/econevals_adapter_spec.md`, `tests/test_econevals_*.py`,
`conftest.py`'s per-family entry), not about the kernel/runner
(`src/aeread/shared_runner/`), so none required a
`ledger_entries/econevals.md` entry — no ledger entry was added.

## CRITICAL

### 1. "Offline replay" silently requires a live upstream bridge subprocess every period — contradicts the spec's own explicit requirement, and the deviation is undocumented

**Disposition: fixed (documentation; behavior was already correct and intentional).**

Verified directly: `replay.py`'s own module docstring, `environment.py`'s
`step()` (whose tool-replay cross-check independently re-derives every
recorded tool result from a live bridge call and hard-fails on any
divergence), and `tests/test_econevals_replay.py::test_replay_raises_when_a_recorded_tool_result_is_tampered_with`
(which only works *because* replay re-derives the tool result from a live
bridge call and compares it to the recorded one) all agree that replay
spawns one bridge subprocess per period. Spec section 5's "Offline replay"
bullet claimed the opposite ("no bridge subprocess spawned... replay reads
sealed evidence only"), borrowing `tau3_retail`'s judge-replay language
verbatim. That analogy does not transfer: `tau3_retail`'s "reads recorded
verdicts, never re-invokes" applies only to its judge-dependent leaf;
econevals has no judge leaf at all — every leaf is deterministic and is
actively, correctly re-verified against the bridge on every replay. This
is exactly the same trade-off `tau3_retail`'s own replay makes for its
tool-body re-execution (also bridge-gated, also not skipped during
replay); the actual behavior is correct and matches established precedent,
it was only the spec's *prose* that overclaimed something never
implemented and never intended.

Fix:
- `docs/econevals_adapter_spec.md` section 5's "Offline replay" bullet
  rewritten to say "zero model calls," not "no bridge subprocess spawned,"
  and to explain why the tau3-judge analogy doesn't apply here.
- Added a milestone-3 build note to section 6 recording this correction
  explicitly, per this adapter's own documentation habit for every other
  known deviation.
- `environment.py`'s stale milestone-2 scope note (which still promised
  "offline replay without a live bridge... lands in a later milestone")
  corrected to match what milestone 3 actually shipped.

Test: `tests/test_econevals_replay.py::test_replay_requires_a_live_bridge_it_is_not_bridge_free`
builds a bridge-free plugin and asserts `replay_episode` raises
`RuntimeError("... requires a provisioned EconevalsBridge")` rather than
silently succeeding — pinning down the corrected claim as an executable
regression, not just prose.

### 2. None of the "five QC Gate-2 goldens" are real episodes — they never touch `parse_action`/`legal`/`step`/`run_episode`, are never sealed, and are never offline-replayed

**Disposition: fixed (partially — see scope note below).**

Verified directly: all five goldens in `tests/test_econevals_measurement.py`
hand-construct an `attempt` dict and feed it straight to
`EconevalsScorer.score_terminal_state`, never calling `parse_action`,
`legal`, `step`, or `run_episode`. Golden 3's *actual* spec'd scenario (the
over-budget allocation), golden 1, golden 2, and golden 5 had zero
environment-level coverage (only golden 3's unknown-offer-id *companion*
and golden 4's malformed-scheduling case were exercised through `step()`,
confirmed by reading `tests/test_econevals_environment.py`). This directly
confirms the reviewer's own question: nothing checked that
`family_case["generated_instance"]` is left untouched by a real
`_submit_procurement` call on golden 3's over-budget scenario.

Fix: added four environment-level companion tests to
`tests/test_econevals_environment.py`, mirroring the existing golden-3-
companion/golden-4 pattern (drive one real period through
`parse_action`/`legal`/`step` via the existing `_run_one_period` helper,
bridge-gated), for goldens 1 (pricing, monopoly prices), 2 (scheduling,
reversed-preference matching), 3 (procurement, the actual over-budget
scenario), and 5 (the hand-authored degenerate procurement instance).
Each new test then calls `plugin.build_scorer(family_case).score_terminal_state(transition.state)`
on the *real* resulting state and asserts the same gate/objective values
the measurement-only goldens assert — so a future `_submit_procurement`
bug that produces a differently-shaped or aliased `attempt` would now be
caught. Goldens 3 and 5 additionally snapshot
`canonical_json_bytes(family_case["generated_instance"])` before and after
`step()` and assert it is unchanged, directly closing the aliasing-bug
scenario the review names.

Scope note (not a refutation, a boundary): this fix adds real
`step()`-level coverage for all five goldens; it does not add
`replay.py`-level coverage sealing and replaying each of the five as its
own recorded episode (spec section 5's literal "replay each of the 5
goldens from its sealed episode record"). `tests/test_econevals_replay.py`
already replays one live pricing episode end-to-end (structurally
identical machinery to what all five would need), so the remaining gap is
five more fixture wire-ups of the same already-proven mechanism, not a new
capability — left for a follow-up pass rather than expanded here, since
the goldens now have real `step()`-level coverage where they previously
had none at all.

## MAJOR

### 3. `conftest.py`'s bridge-required skip detector has an incomplete marker list for econevals

**Disposition: fixed.**

Verified directly: `tests/test_econevals_cases.py`'s
`test_module_sha256_table_matches_the_checkout_on_disk` skipped with reason
`"pinned upstream checkout not found"`, which is not a substring of and
does not contain `conftest.py`'s only econevals marker, `"pinned upstream
econ-evals Python interpreter"` — confirmed by direct string comparison.
`AEREAD_ECONEVALS_BRIDGE_REQUIRED=1` would silently miss this skip.
Also confirmed `UPSTREAM_ROOT` in that same file was a hardcoded absolute
path with no environment-variable override, unlike `tau2`'s
`_upstream_root()` convention — and unlike
`tools/econevals_bridge/provision.sh`, which *already* reads
`$AEREAD_ECONEVALS_UPSTREAM_ROOT` for exactly this purpose (this test file
had simply never been wired to the same variable).

Fix:
- `tests/test_econevals_cases.py`: `UPSTREAM_ROOT` now reads
  `$AEREAD_ECONEVALS_UPSTREAM_ROOT` before falling back to the hardcoded
  default, and the skip reason is now
  `f"pinned upstream econ-evals checkout not found at {UPSTREAM_ROOT}"`.
- `conftest.py`'s `AEREAD_ECONEVALS_BRIDGE_REQUIRED` entry now carries two
  markers (mirroring `tau2`'s two-marker entry): the Python-interpreter
  one and a new `"pinned upstream econ-evals checkout not found"` one.

Test: `tests/test_econevals_cases.py::test_conftest_bridge_gate_marker_covers_this_files_checkout_skip_reason`
imports `conftest`, reads its own `_BRIDGE_FAMILIES` entry for econevals,
and asserts at least one marker is a substring of this file's own
checkout-not-found skip reason (it would have failed against the
pre-fix marker tuple). Manually confirmed end-to-end: with
`AEREAD_ECONEVALS_BRIDGE_REQUIRED=1` and `AEREAD_ECONEVALS_UPSTREAM_ROOT`
pointed at a nonexistent path, the terminal-summary hook now reports
"upstream bridge required" and forces a nonzero exit status for exactly
this skip.

## MINOR

### 4. Golden 1's own test is tautological in isolation

**Disposition: fixed (via finding 2's remediation).**

Verified directly: `tests/test_econevals_measurement.py`'s golden 1 copies
`attempt["profits"]` straight from `gold_optimum["profits_by_period"]`, so
`objective.primary.value == v_star` holds by construction, exactly as the
review states; the test's own docstring already discloses this and defers
real verification to the adjacent parity test. Not re-touched as a
standalone fix (the review itself calls this "not a standalone defect").
Finding 2's new environment-level golden-1 test
(`tests/test_econevals_environment.py::test_golden_1_successful_pricing_through_step_gate_passes_and_objective_matches_the_optimum`)
independently derives `profits` from a live `bridge.pricing_profits` call
made by the real `_submit_pricing` path rather than copying
`gold_optimum`, so the same gate/objective claim is now also backed by a
non-tautological path; the original measurement-only golden is left as
documented, intentionally cheap scaffolding.

### 5. Hardcoded, machine-specific absolute paths with no env-var override

**Disposition: fixed (via finding 3's remediation).**

Verified directly: `econevals_bridge.py`'s `DEFAULT_BRIDGE_VENV` was
already overridable via `$AEREAD_ECONEVALS_BRIDGE_PYTHON` (the review notes
this itself); `tests/test_econevals_cases.py`'s `UPSTREAM_ROOT` was not
overridable at all, which is the same gap finding 3 fixes. No separate
change was needed beyond finding 3's.

## What looked solid (no action taken)

Gate 1 corpus admission and the verifier-declaration/`verifier_taxonomy.md`
compliance findings in the review's closing section were re-read and are
not disputed; no code or doc changes were made on their account.
