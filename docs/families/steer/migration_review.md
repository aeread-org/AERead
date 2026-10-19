# steer migration review

<!-- Provenance: independent review supplied to the migrating agent for the steer FamilyScoringInput migration; reproduced verbatim below. -->
<!-- Disposition (fixed/refuted/escalated), verification, and mutation-test results appended by the migrating agent, 2026-09-05. -->

--- BEGIN REVIEW ---
1. `tests/test_shared_runner_scoring_contract.py:979-987, 1448-1450, 1717-1720, 1750-1757` — STEER is counted as enrolled by the always-on trusted-catalog closure through a static set entry, while its actual protocol test skips whenever the external cache is absent. Scenario: run the suite without the license-constrained STEER cache; `_steer_cache_root()` calls `pytest.skip`, so `_assert_family_scoring_contract` never executes for STEER, yet the catalog closure still passes because `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` contains `("steer", "0.1.0")`. Thus a scorer returning the wrong leaf set could remain trusted with a green suite. This violates the requirement that the trusted family be covered by the protocol test; it is a test-quality/enrollment gap.

FINDINGS: 1
--- END REVIEW ---

## Disposition

### Finding 1 — CONFIRMED, fixed

Verified against the code before acting:

- `tests/test_shared_runner_scoring_contract.py::_steer_cache_root` (line 980, pre-fix
  numbering) calls `pytest.skip(...)` whenever the flattened cache's marker file
  (`<cache_root>/transitivity/cases.jsonl`) is missing.
- `_steer_fixture_pair` (line 1257, pre-fix numbering) is the only caller of
  `_steer_cache_root`, and `test_steer_obeys_the_scoring_contract` (line 1751, pre-fix
  numbering) is the only caller of `_steer_fixture_pair` — so that test skips under the
  same condition, and `_assert_family_scoring_contract` never runs for steer.
- `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS = frozenset({("steer", "0.1.0")})` (line 1448,
  pre-fix numbering) is folded unconditionally into
  `test_every_registered_family_obeys_the_scoring_contract`'s `enrolled_family_versions`
  set (line 1719, pre-fix numbering: `set(fixtures) | _BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`),
  independent of whether `test_steer_obeys_the_scoring_contract` actually ran to
  completion.
- Reproduced directly: with `AEREAD_STEER_DATA_ROOT` pointed at an empty directory and no
  `AEREAD_STEER_FIXTURES_REQUIRED` set,
  `pytest tests/test_shared_runner_scoring_contract.py -k "test_every_registered_family_obeys_the_scoring_contract or test_steer_obeys_the_scoring_contract"`
  reported `test_steer_obeys_the_scoring_contract` as `SKIPPED` while
  `test_every_registered_family_obeys_the_scoring_contract` reported `PASSED`, exit 0 — a
  green run that never exercised steer's returned leaf set, primary, admission set,
  provenance, or determinism. Finding confirmed.

**Relationship to the reference migration's govsim finding of the identical shape**
(`docs/govsim_migration_review.md` finding 1): the project's established fix for this
finding class is an `AEREAD_<FAMILY>_..._REQUIRED`-style entry in root `conftest.py`'s
`_BRIDGE_FAMILIES`, whose `pytest_terminal_summary` hook turns a matching skip into a
failed run (exit status 1) when the variable is set. Unlike govsim, which had no such
entry at all, **steer already has one** — `AEREAD_STEER_FIXTURES_REQUIRED`, with markers
including `"flattened cache not built yet at"` (`conftest.py`'s `_BRIDGE_FAMILIES`,
pre-existing on this branch's base, not added by this migration). So the reference fix
itself (add the missing entry) is a no-op here; it was already done before this review.

That pre-existing mechanism does **not** fully close the gap, though, and this is the
concrete residual verified directly: the hook only reacts to a skip it can see in the
*same pytest session* (matched by scanning `terminalreporter.stats["skipped"]` for a
reason substring produced by *some other test*, namely
`test_steer_obeys_the_scoring_contract`). A narrower invocation that never collects that
test — reproduced with
`pytest tests/test_shared_runner_scoring_contract.py -k test_every_registered_family_obeys_the_scoring_contract`,
cache still missing, `AEREAD_STEER_FIXTURES_REQUIRED=1` set — reported `1 passed`, exit
status **0**. The certifying flag was set, the cache was genuinely missing, and the run
was still fully green with no warning at all, because the one test that would have
produced a matching skip reason was never collected in the first place. The conftest
mechanism alone is therefore an incomplete answer for steer specifically, because steer
(unlike every other bridge-gated family, all of which are honestly listed in
`_NOT_YET_MIGRATED_TRUSTED_KEYS` rather than claiming migration) makes an unconditional,
closure-level claim of being migrated-and-fixture-covered.

**Fix**: added a self-contained check directly inside the closure assertion in
`tests/test_shared_runner_scoring_contract.py`, so `test_every_registered_family_obeys_the_scoring_contract`'s
own pass/fail no longer depends on whether a companion test happened to be selected in
the same invocation:

- `_steer_cache_available() -> bool` — a non-skipping counterpart to `_steer_cache_root`
  (same marker-file check, returns `False` instead of calling `pytest.skip`).
- `_steer_fixtures_required_env() -> bool` — reads `AEREAD_STEER_FIXTURES_REQUIRED` with
  the same truthy values as root `conftest.py`'s own `_truthy`.
- `_assert_steer_bridge_gated_enrollment_is_honest(*, cache_available, fixtures_required)`
  — `pytest.fail`s when the cache is unavailable **and** certification was requested;
  otherwise a no-op, preserving the sanctioned "vacuously green without the bridge"
  behaviour shared by every other bridge-gated family's own tests when nobody has asked
  to certify fidelity.
- Wired into `test_every_registered_family_obeys_the_scoring_contract`, called
  immediately before `_assert_trusted_catalog_is_closed`.

This does not touch `conftest.py` (already correct for steer), does not change
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`'s or `_assert_trusted_catalog_is_closed`'s own
semantics, and does not weaken, loosen, or delete any existing test.

**Deviation from the reference (govsim) fix shape, stated as required**: govsim's fix
added the missing `conftest.py` entry because none existed. Steer's entry already
existed, so that reference action is a no-op here; the residual gap it doesn't close
(narrower invocations that never collect the companion skip) required a different,
smaller fix scoped entirely to `test_shared_runner_scoring_contract.py` instead of
`conftest.py`.

- **Test written first (red)**: `test_steer_bridge_gated_enrollment_is_not_honest_about_required_fixtures`
  and `test_steer_fixtures_required_env_reads_the_documented_truthy_values`, calling
  `_assert_steer_bridge_gated_enrollment_is_honest` / `_steer_fixtures_required_env`,
  which did not exist yet — collection failed with `AttributeError`/`NameError` before the
  helpers were added.
- **Fix applied**: the four additions above (`_steer_cache_available`,
  `_steer_fixtures_required_env`, `_assert_steer_bridge_gated_enrollment_is_honest`, and
  the call site in `test_every_registered_family_obeys_the_scoring_contract`).
- **Test result (green)**: both new tests pass; the full designated re-run (below) is
  175 passed, 0 failed, 0 skipped.
- **Mutation check, end-to-end, reproducing the review's exact scenario before and after**:
  - Before the fix: `AEREAD_STEER_DATA_ROOT` pointed at an empty directory,
    `AEREAD_STEER_FIXTURES_REQUIRED=1` set,
    `pytest tests/test_shared_runner_scoring_contract.py -k test_every_registered_family_obeys_the_scoring_contract`
    → `1 passed`, exit status `0` (the vulnerability, reproduced pre-fix).
  - After the fix: the identical invocation →
    `1 failed` with
    `Failed: AEREAD_STEER_FIXTURES_REQUIRED is set but the flattened STEER cache is unavailable -- ...`
    (the vulnerability is closed).
  - Regression check, same cache-missing setup with `AEREAD_STEER_FIXTURES_REQUIRED`
    unset (the sanctioned, documented without-bridge mode): unchanged before and after —
    `test_every_registered_family_obeys_the_scoring_contract` `PASSED`,
    `test_steer_obeys_the_scoring_contract` `SKIPPED`, exit status `0`.
  - Isolated unit-level mutation check: `test_steer_bridge_gated_enrollment_is_not_honest_about_required_fixtures`
    directly exercises `_assert_steer_bridge_gated_enrollment_is_honest` and asserts it
    raises exactly when `cache_available=False, fixtures_required=True`, and never
    otherwise — proven without touching the real cache path, environment, or
    `TRUSTED_BUILTIN_PLUGIN_KEYS`, mirroring `test_trusted_catalog_closure_rejects_an_unenrolled_key`'s
    own pattern for the analogous R6 mutation check.

## Stated limits

- This closes the gap for any invocation that certifies via
  `AEREAD_STEER_FIXTURES_REQUIRED=1`, including the narrower `-k`-scoped invocation the
  pre-existing `conftest.py` mechanism could not see. It does not, by itself, force any
  particular CI job to set that variable — matching the already-accepted state of the
  identical `conftest.py` mechanism for tau2-bench, econ-evals, auction-arena, AgenticPay,
  Alympics, and EconAgent, none of which has a dedicated fidelity CI job either.
- The fix is specific to steer's own `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` entry. It is
  not a general solution for a future bridge-gated family added the same way; the next
  such family needs its own `_steer_cache_available`-shaped, non-skipping availability
  check and its own honesty assertion, following this shape.
- A genuinely offline invocation still cannot detect a *wrong* scorer without the cache
  present — `_assert_steer_bridge_gated_enrollment_is_honest` only prevents a *silent,
  unqualified* pass when certification was explicitly requested and could not be
  delivered; it does not (and cannot) run `_assert_family_scoring_contract` itself
  without the real, license-constrained cache.

## Post-stacking note, 2026-09-06

After rebasing this branch onto the R9/R10 kernel branch (`zeyu/kernel-r9r10`,
PR #103), the family-local `_assert_family_scoring_contract` named throughout
the sections above was removed in favour of that kernel branch's own,
identically-shaped `_assert_family_obeys_the_scoring_contract`
(`tests/test_shared_runner_scoring_contract.py`); `test_steer_obeys_the_scoring_contract`
now calls the kernel's helper directly. Every reference to
`_assert_family_scoring_contract` above describes the pre-rebase state of the
code and is left as originally written, not restated.
