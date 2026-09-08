# amazonbarg adapter — triage of `docs/amazonbarg_review_codex.md`

Second-reviewer (codex) pass, 10 declared findings. Each finding was independently
re-read against the code (narrow `grep`/`sed -n` reads, no reliance on the reviewer's
line numbers or authority) before classification. Where the finding concerns upstream
behavior, the pinned upstream checkout at
`/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg` (verified at commit
`834ad9066d0627f0332504d5fa6d236706f2402b`, matching `UPSTREAM_COMMIT`) was read
directly. This is triage only — nothing has been fixed yet.

---

## Finding 1 — Runtime upstream pin is not enforced (Critical)

**Classification: CONFIRMED.**

**Read:** `src/aeread_families/amazonbarg/environment.py:151-166`
(`AmazonbargPlugin.validate_payload`) and
`src/aeread_families/amazonbarg/upstream_shim.py:346-406`
(`import_parse_reply`/`import_action_parser`/`import_metrics`).

**Evidence.** `validate_payload` checks `pins.get("upstream_commit") != UPSTREAM_COMMIT`
(environment.py:163) — this compares two *strings*: the commit hash declared inside the
case JSON payload against the hard-coded constant in `cases.py:64`. It never touches the
actual bytes at `upstream_root`. Separately, `AmazonbargPlugin.__init__`
(environment.py:143-146) calls `upstream_shim.import_parse_reply(self.upstream_root)` /
`import_action_parser(self.upstream_root)`, and `measurement.compute_upstream_metrics`
(measurement.py:538) calls `upstream_shim.import_metrics(upstream_root)` on every scoring
call. All three `upstream_shim` functions (`direct_import`/`delegated_import`,
upstream_shim.py:304-343) do nothing but `sys.path.insert` the caller-supplied
`upstream_root` and `import` whatever source files live there — no hash, no `git
rev-parse`, no byte comparison against anything derived from `UPSTREAM_COMMIT`. `git log
-1 --format=%H` inside the upstream checkout was independently confirmed to equal
`UPSTREAM_COMMIT` today, but nothing in this adapter's code path would notice if that
checkout were edited in place.

**Concrete failure scenario:** an operator (or a compromised dependency) edits
`eval.py`'s `Metrics.evaluate` in the on-disk `upstream_root` checkout — e.g. widening
what counts as ZOPA, or forcing `wrongAction = 0` always. `validate_payload` still
passes (the payload's declared `pins.upstream_commit` string is untouched and matches).
`compute_upstream_metrics` imports and executes the edited file with zero detection.
Every published score for that run is silently wrong under the officially claimed pin.

---

## Finding 2 — False ZOPA passes (High)

**Classification: CONFIRMED.**

**Read:** `src/aeread_families/amazonbarg/measurement.py:661-693`
(`score_zopa_membership`) and upstream `eval.py:220-238` (`Metrics.evaluate`, DEAL
branch).

**Evidence.** `score_zopa_membership` reads `lower, upper, deal_price =
float(metrics_output["C"]), float(metrics_output["B"]), float(metrics_output["D"])`
(measurement.py:675-679) and does `in_zopa = lower <= deal_price <= upper`
(measurement.py:680) — i.e. it trusts upstream's delegated `B` (budget) verbatim.
Upstream's own `eval.py:220-233` does **not** always set `self.B = self.budget`
unchanged: `if 0 <= budget - cost < 1: room = 1; budget = cost + 1` (and the mirror
branch for `-1 < budget - cost < 0`) — i.e. whenever the raw bargaining room is under
$1, upstream silently *replaces* the budget with `cost + 1` (or `cost - 1`) before
setting `self.B = budget`. `score_zopa_membership` has no knowledge of this and no
comparison against the *genuine* derived budget already sitting in `family_case`.

**Reproduced on the actual pilot case** `cases/amazonbarg/pilot/amazonbarg.bilateral.home-kitchen_20.json`:
`derived.budget = 47.992000000000004`, `derived.cost = 47.99`
(`budget - cost = 0.002 < 1`). Per upstream's own branch this forces `budget = cost + 1
= 48.99`, so `metrics_output["B"] = 48.99` for any deal on this case — exactly the
reviewer's numbers. A deal at `$48.50` would sit inside `[47.99, 48.99]`
(`in_zopa = True`, primary `1.0`, "pass") even though `48.50` is **above the buyer's
real budget of 47.992** — a false ZOPA pass. No test drives `home-kitchen_20` at all
(`grep -rn "home-kitchen_20" tests/` and `src/` returns nothing besides the review file
itself), and no test in `test_amazonbarg_measurement.py` exercises a
`budget - cost < 1` case, so this is a live, uncaught gap in a leaf whose whole
documented purpose ("AERead's own added check upstream itself never performs") is to
catch exactly this kind of discrepancy.

---

## Finding 3 — Replay never reads sealed evidence (High)

**Classification: CONFIRMED.**

**Read:** `src/aeread_families/amazonbarg/replay.py:137-155` (`record_episode`) and
`tests/test_amazonbarg_replay.py:160-171` (`_run_live`), `:266-275`
(`test_replay_case_mismatch_raises_a_typed_replay_error`).

**Evidence.** `record_episode(result: EpisodeResult)` (replay.py:137) iterates
`result.phase_instances[*].actions[*]` — fields on the **in-memory** `EpisodeResult`
object returned by `run_episode` — and builds a `RecordedEpisode` from that. `grep -n
"EvidenceStore" src/aeread_families/amazonbarg/replay.py` returns nothing: the entire
`replay.py` module never imports, opens, or reads an `EvidenceStore` at all. In
`tests/test_amazonbarg_replay.py`'s `_run_live` helper (lines 160-171), an
`EvidenceStore` (`_evidence(tmp_path, ...)`) is constructed and passed to
`ScriptedAmazonbargHarness`, the episode runs and the store is sealed
(`assert harness.sealed`), but the returned `result` (the in-memory object) — not the
sealed store — is what every caller passes to `record_episode`. This is not a
tests-only shortcut: it is the *only* code path `replay.py` has, so the module's own
`docs/amazonbarg_adapter_spec.md:22` claim ("`replay.py` reproduces a sealed episode's
state and score with zero further model/network calls") is not backed by any read of
the durable, hash-chained evidence — only of the live process's own return value.
Corrupting or deleting the sealed `EvidenceStore` on disk after a test run would not
affect any assertion in `test_amazonbarg_replay.py`, because nothing in that file (or in
`replay.py`) ever reads it back.

---

## Finding 4 — Unverified offline replay reports `match` (High)

**Classification: CONFIRMED.**

**Read:** `src/aeread_families/amazonbarg/replay.py:376-425`
(`ReplayReport.status`/`replay_and_verify`).

**Evidence.**
```python
@property
def status(self) -> str:
    if self.comparison is not None and not self.comparison.matches:
        return "mismatch"
    return "match"
```
(replay.py:388-391). `replay_and_verify`'s own docstring (replay.py:403-410) states
that when `original` is absent ("a genuinely offline replay from a previously-written
record, with no original run in memory") `comparison is None` is "an explicit, typed
'not comparable' rather than a fabricated match" — but the `status` property directly
contradicts that: `comparison is None` falls through to `return "match"`, the identical
string returned when `comparison.matches is True`. No test in
`tests/test_amazonbarg_replay.py` calls `replay_and_verify`/constructs a `ReplayReport`
with `original=None` (`grep -n "original=None" tests/test_amazonbarg_replay.py` — no
hits); the one test that checks `report.status == "match"`
(`test_replay_and_verify_end_to_end_returns_a_matching_report`, line ~498) always
supplies `original=original`. So the exact case the docstring calls out as needing to be
"explicit, typed 'not comparable'" is (a) not what the code does, and (b) not tested.

**Concrete failure scenario:** a `RecordedEpisode` fabricated or altered offline (no
corresponding live `original` in memory) is replayed through `replay_and_verify` with
`original=None`. The replay itself completes (any well-formed, terminating scripted
trajectory does), `comparison` stays `None`, and `report.status == "match"` — a caller
that treats `"match"` as "byte-identical to a genuine prior run" (the meaning it has in
every other codepath) is misled: nothing was actually compared to anything.

---

## Finding 5 — Production execution does not produce or seal scores (High)

**Classification: CONFIRMED, but OUT OF SCOPE for this adapter — appended to the
shared-runner ledger** (`runner_defect_ledger.md`, new entry below).

**Read:** `src/aeread_families/amazonbarg/measurement.py:815-840`
(`AmazonbargScorer` docstring) and `:904-927` (`score_all`), plus (to determine scope)
`src/aeread/shared_runner/family_evaluation.py:210-252` (`finalize_family_execution`)
and `src/aeread/shared_runner/smoke.py:126-127`.

**Evidence.** `AmazonbargScorer`'s own docstring (measurement.py:818-822) states
verbatim: *"the current kernel does not yet invoke `build_scorer` itself... so these are
also exercised directly by tests today"* — mirroring an identical admission in
`Tau3RetailScorer`'s docstring in the sibling `tau3_retail` family. `score_all`
(measurement.py:904-927) does default every leaf's `evidence_refs` to `()` — true as
stated, but moot today because nothing in the real execution path calls `score_all` at
all, on any family: `finalize_family_execution` (`family_evaluation.py:245`) does
`plugin.build_scorer(family_case)(recorded_outcome, evidence_refs=(outcome_event.event_id,))`
— i.e. it expects `build_scorer`'s return value to be directly **callable** and to
return **one** `ScoreEnvelope` (it reads `score.leaf.leaf_id` and `score.status`
singular, and constructs `scores=(score,)`, a one-element tuple). `AmazonbargScorer` (and
`Tau3RetailScorer`) are frozen dataclasses with **no `__call__`** — calling
`plugin.build_scorer(family_case)(...)` for amazonbarg (or tau3_retail) today would raise
`TypeError: 'AmazonbargScorer' object is not callable`. Even the shared kernel's own
reference/smoke plugin doesn't satisfy this contract: `smoke.py:126-127`'s
`build_scorer` returns `lambda outcome: outcome` — calling that with
`evidence_refs=(...)` would raise `TypeError` for an unexpected keyword argument. `grep
-rl "finalize_family_execution" tests/` returns no hits anywhere in this worktree: this
kernel entry point is currently untested against every real family, not just amazonbarg.

**Why out of scope:** the actual gap — a five-leaf-per-case family (amazonbarg,
matching its own documented "never blended into one number" design) has no way to
satisfy a kernel contract (`finalize_family_execution`) that is hard-wired for exactly
one `ScoreEnvelope` per family — is a shared-runner/family-plugin contract question
(same shape as ledger `D-12`'s `build_scorer`/`EpisodeResult` gap), not a bug in
amazonbarg's own measurement.py. amazonbarg correctly implements its own declared
five-leaf model; the mismatch is that the kernel's only currently-wired production
scoring call site assumes single-leaf families. Fixing this inside amazonbarg (e.g.
inventing an arbitrary "primary" leaf and hacking `__call__` onto `AmazonbargScorer`)
would be a unilateral, adapter-local workaround to a cross-family kernel design
question that needs a ruling, exactly the pattern the existing D-12/D-13/D-14 entries
already follow. Appended to `runner_defect_ledger.md` as a new entry (see below);
amazonbarg's own code is unchanged by this triage step.

---

## Finding 6 — Tests silently skip wholesale (Major)

**Classification: CONFIRMED.**

**Read:** `tests/test_amazonbarg_measurement.py:48-63` (`_upstream_root`) and `:161-220`
(pure leaf-declaration tests).

**Evidence.** `_upstream_root()` is called at **module level**
(`UPSTREAM_ROOT = _upstream_root()`, line 63) — not inside a fixture scoped to only the
tests that need it. If the hard-coded fallback path
`/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg` (a personal, absolute,
developer-machine path; overridable only via the `AEREAD_AMAZONBARG_UPSTREAM_ROOT` env
var) has no `data/AmazonHistoryPrice/home-kitchen.json` marker file, the function calls
`pytest.skip(..., allow_module_level=True)` (line 58-60), which skips **every test in
the file**. Lines 161-220 (`test_build_leaves_declares_exactly_five_leaves_every_time`,
`test_deal_authenticity_leaf_is_a_delegated_rule_constraint`,
`test_zopa_membership_leaf_is_a_rule_constraint_distinct_from_authenticity`,
`test_bound_leaves_are_two_separate_objective_reference_leaves`,
`test_bargained_ratio_leaf_is_comparative_with_no_objective_scope`) call only
`m.build_leaves()`/`m.build_*_leaf()` — pure functions of `measurement.py`, touching no
upstream checkout, no `upstream_root` parameter at all — yet they are skipped along
with everything else on a machine/CI runner without that one checkout present. The
identical `allow_module_level=True` pattern is present in all six
`tests/test_amazonbarg_*.py` files (`grep -n "allow_module_level=True"
tests/test_amazonbarg_*.py` — one hit per file), so this is systemic across the whole
family's test suite, not an isolated slip. This exactly matches this triage's flagged
defect shape: a green run's "106/106 passed" or "114/114 passed" headline figure gives
no signal that these numbers depend on one personal absolute path existing on the
machine that ran them — on any other machine the true count would be "0 ran, N
skipped," silently, with no failure.

---

## Finding 7 — "Component parity" compares the implementation with itself (Major)

**Classification: CONFIRMED.**

**Read:** `tests/test_amazonbarg_measurement.py:287-343` (`_score_and_check_parity`).

**Evidence.** `_score_and_check_parity` calls `m.compute_upstream_metrics` twice
(`metrics_output` and `replay_metrics_output`, lines 297-304) on the *identical*
recorded `history`, both delegated to the same pinned upstream `eval.py:Metrics` through
the same shim, and asserts they're equal (line 305) — this proves determinism/no
cross-call caching (test plan P3), nothing more. The subsequent "component parity"
assertions (lines 331-342, e.g. `envelopes["zopa"].metrics["deal_price"].value ==
metrics_output["D"]`) check only that `measurement.py`'s scoring functions read
upstream's own fields **verbatim**, catching wiring slips (wrong dict key, rounding) —
not semantic defects that live *inside* the delegated `eval.py:Metrics` computation
itself, because both "independent" calls run the exact same upstream code on the exact
same input and will agree on whatever that code computes, bug or not. This is
demonstrated directly by finding 2: the room-widening quirk in upstream's own
`eval.py:220-233` reproduces byte-identically in both `metrics_output` and
`replay_metrics_output`, so `_score_and_check_parity`'s assertions all pass on
`home-kitchen_20` even though the resulting ZOPA verdict is substantively wrong. The
five shipped goldens' hand-annotated comments (e.g. `test_golden_1_...`'s
`# 135 in [95.0, 173.44]`, measurement.py-adjacent test file line ~363) show a genuine
manually-checked bracket for wide-room cases, but none of the five goldens has a
narrow (`< $1`) bargaining room, so this manual-oracle spot-check never exercises the
one case class where the delegated "oracle" itself is wrong. The parity check's oracle
*is* the code under test; it cannot and does not detect defects shared between the two
calls to it.

---

## Finding 8 — Sanitization is collision-prone and non-reversible (Major)

**Classification: CONFIRMED.**

**Read:** `src/aeread_families/amazonbarg/cases.py:118-146` (`sanitize`/`desanitize`) and
`tests/test_amazonbarg_cases.py:108-123` (round-trip tests).

**Evidence, reproduced directly** (ran the escaping logic standalone):
```
sanitize("a:b")          == "a_x003a_b"
sanitize("a_x003a_b")    == "a_x003a_b"   # every char already in [a-z0-9_.-]
collision: True
```
`sanitize` (cases.py:122-135) passes any character matching `_SANITIZE_PASSTHROUGH_RE =
[a-z0-9_.\-]` straight through and escapes everything else as `_x{ord:04x}_`; because the
literal characters `_`, `x`, and hex digits are themselves inside the passthrough set, a
codename that already happens to *contain* the literal marker text (e.g.
`"a_x003a_b"`) is left untouched and becomes indistinguishable from the escaped form of
`"a:b"`. `desanitize` (cases.py:137-143) is therefore not a true inverse of `sanitize` in
general: `case_id_for_codename` (cases.py:147-148) could assign the identical
`case_id` to two distinct real codenames if the corpus ever contained both forms. The
docstring on `sanitize` (cases.py:127-132) states this is deliberately defensive code
for "a future non-conforming category name" — that stated intent (produce a *safe,
unique* id) is not met, independent of whether today's fixed, pinned 930-codename
corpus happens to avoid triggering it (verified: it does, per
`test_sanitize_is_the_identity_on_every_one_of_the_930_real_codenames`). The
parametrized counter-example test (`tests/test_amazonbarg_cases.py:108-114`, inputs
`["café_1", "a:b", "ABC_1", "home-kitchen_2", "toys-games_22", "已经_9"]`) never includes
a literal `_xHHHH_`-shaped input, so this collision path is genuinely untested.

---

## Finding 9 — Pilot digest depends on dictionary insertion order (Medium)

**Classification: CONFIRMED.**

**Read:** `src/aeread_families/amazonbarg/cases.py:445-471` (`build_pilot_manifest`,
`_pilot_content_sha256`).

**Evidence, reproduced directly:** built two dicts with the identical 45 keys, one the
reverse insertion order of the other, and called `build_pilot_manifest` on each:
```
same membership, order reversed
digest1: abbfc79acd3c6b8f7682ae5be83fdc53989bd2c0abf2d019df47ceb7f4bc7e8c
digest2: 54c59841e4cd8adf20a99c7a5f1411794e27b6749b88a24d94f0a9e982684094
equal digests: False
same set of case_ids: True
```
`build_pilot_manifest` (cases.py:445-463) does `case_ids = list(cases)` — plain dict
insertion order, with an explicit code comment (cases.py:446-448) rejecting sorting in
favor of relying on the one production caller (`import_pilot_cases`) always building the
dict in the same natural order. That reliance is real (the one shipped caller is
deterministic today) but the digest itself, despite representing "pilot *membership*" (a
set), is actually keyed on an incidental total order — two callers assembling the
identical 45-case set in a different sequence get two different "identities" for what
should be the same content. Nothing in `validate_payload`/environment.py re-derives and
compares this digest against a pin at runtime (only `tests/test_amazonbarg_cases.py`'s
own mutation-sensitivity tests touch it), so the practical blast radius today is limited
to provenance/documentation use of `pilot_manifest.json`, not a runtime-enforced pin —
but the property described is real and reproduced.

---

## Finding 10 — Import shim is unsafe under concurrency (Medium)

**Classification: CONFIRMED.**

**Read:** `src/aeread_families/amazonbarg/upstream_shim.py:225-343`
(`_install_missing_stub_modules`, `_no_network_guard`, `_lenient_openai_construction`,
`direct_import`, `delegated_import`).

**Evidence.** All of `_install_missing_stub_modules` (mutates `sys.modules`, line
227-241), `_no_network_guard` (reassigns the *class* attribute
`socket.socket.connect`, lines 251-263 — process-wide, not per-instance),
`_lenient_openai_construction` (reassigns the module attribute `openai.OpenAI`, lines
269-286), and `_insert_path`/`_remove_path` (mutate `sys.path`, lines 288-297) operate on
genuinely global, process-wide mutable state with **no lock, no synchronization
primitive of any kind** (`grep -n "Lock\|lock" upstream_shim.py` — no hits). `direct_import`
/`delegated_import` (lines 304-343) compose these as nested context managers and, in
their `finally` blocks, unconditionally pop every name in `_UPSTREAM_MODULE_NAMES` from
`sys.modules` and remove the inserted `sys.path` entry. `measurement.compute_upstream_metrics`
calls `upstream_shim.import_metrics(upstream_root)` fresh on **every** scoring call
(measurement.py:538, not cached), so every episode's scoring pass re-enters this
unsynchronized global-mutation window. Two genuinely concurrent scoring calls (e.g. two
episodes scored via `asyncio.gather` or parallel workers) would race: one call's
`finally` could evict `session`/`eval` from `sys.modules` while another call is mid-import
expecting them present, or one call's restore of `socket.socket.connect`/`openai.OpenAI`
could clobber a still-in-flight second call's patched state. Checked whether this is
currently reachable: `grep -rln "asyncio.gather\|ThreadPoolExecutor\|Semaphore" src/aeread/shared_runner/*.py`
returns no hits — the shared kernel does not currently run cells concurrently, so this is
latent rather than actively triggered today. The hazard is nonetheless a real property
of this adapter's own code (not the kernel's), independent of today's serial-only
execution pattern, and nothing in the code or its docstrings asserts or enforces
single-threaded use as a precondition.

---

## Summary

| # | Severity (reviewer) | Disposition |
|---|---|---|
| 1 | Critical | CONFIRMED |
| 2 | High | CONFIRMED |
| 3 | High | CONFIRMED |
| 4 | High | CONFIRMED |
| 5 | High | CONFIRMED, but OUT_OF_SCOPE (shared-runner kernel contract) — appended to `runner_defect_ledger.md` |
| 6 | Major | CONFIRMED |
| 7 | Major | CONFIRMED |
| 8 | Major | CONFIRMED |
| 9 | Medium | CONFIRMED |
| 10 | Medium | CONFIRMED |

**Confirmed (adapter-owned): 9. Out of scope (kernel-owned, ledgered): 1. Refuted: 0.**

Nothing was refuted: every one of the 10 findings reproduced exactly as described once
read against the actual code, several with a live standalone reproduction (findings 2,
8, 9) rather than only a code read. This is a materially different outcome from the
first (claude) review's disposition (`docs/amazonbarg_review_disposition.md`, 3
findings, all fixed) — this second pass surfaced defects the first pass's own added
regression tests do not cover (the false-ZOPA room-widening bug, the replay/evidence
disconnect, the unverified-offline-replay status collapse, the sanitize collision, and
the order-dependent pilot digest all sit outside what W1/W2/M1's fixes touched).

No fixes were made in this step (triage only, per instructions). Finding 5 has been
appended to `/Users/sunzeyu/Documents/econ benchmark/runner_defect_ledger.md` as a new
entry; the remaining 9 confirmed findings are left for the next (fix) pass.
