# amazonbarg adapter — second-reviewer read (Claude), 2026-09-02

Scope: `git diff origin/main..HEAD` in this worktree (62 files, ~9.5k lines: cases/environment/
measurement/harness/replay/upstream_shim + tests + docs + 45 pilot case JSON files). Read
`docs/amazonbarg_adapter_spec.md` and `docs/research/verifier_taxonomy.md` first, then every source file
in the diff, then every test file. Actually **executed** the suite against the real pinned
upstream checkout at `/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg` (present and
correct commit-era files) rather than trusting the status doc's claim: `106/106 passed, 0
skipped` for the full amazonbarg family test-file set, confirmed independently. Also hand-traced
`eval.py`/`session.py`/`utils/Action.py` in the pinned checkout to verify claims made about
upstream's own behavior (parseReply's empty-action-text path, ActionParser's regex/exception
shape, Metrics.evaluate's authenticity/ZOPA/ratio arithmetic) rather than taking the adapter's
docstrings at face value.

## Overall verdict

No critical defects. The five QC Gate-2 goldens are real (they exercise the actual pinned
upstream checkout through the real `run_episode`/`AmazonbargPlugin`/`PluginRegistry` path, never
a stub or a hand-derived number), Gate-1 corpus admission is solid (digests match a direct
re-read, dedup guard is real and exercised, no random/resampling anywhere, a checked-in-vs-fresh-
import byte-identity test exists and passes), verifier declarations are checked against the real
`aeread.shared_runner.measurement` contract classes (not just the taxonomy doc's stale prose —
the adapter's own docstrings/ledger entries correctly identify three places where
`docs/research/verifier_taxonomy.md` §5.1 drifted from the real `_REFERENCE_KINDS`/`ObjectiveScopeSpec`/
`ScoreEnvelope.status` schema, and route around them instead of silently mislabeling), and replay
is genuine re-execution (a second, independently-constructed `AmazonbargPlugin` instance is
driven through `run_episode` with a `RecordedResponseSource` that re-serves the recorded raw text
through the real `parse_action`/`legal`/`step` hooks, and the score is recomputed from the
*replayed* history via a fresh delegated `eval.py:Metrics` call — never read back from a stored
number). Two WARNING-level gaps and one MINOR labeling risk below are worth the author's
attention before this is called done.

---

## WARNING

### W1 — The invalid/malformed-action golden (golden 4) never gets the adapter's own strongest evidentiary treatment (sealed evidence + replay), only a plain `run_episode` call

- `src/aeread_families/amazonbarg/harness.py`, `tests/test_amazonbarg_harness.py:117-209`,
  `tests/test_amazonbarg_replay.py:127-137`
- The task asks specifically whether "the invalid-action golden actually proves no protected
  state changed." At the environment level it does: `tests/test_amazonbarg_environment.py:326-339`
  (golden 4, missing `Action:` line) asserts `terminal["reason"] == "action_error"`,
  `turns_completed == 0`, `len(history) == 1`, `len(history[0]) == 1` — i.e. the malformed buyer
  turn halts the episode immediately, no seller phase ever runs, `turn_index` never advances, and
  no phantom deal gets recorded. I additionally hand-verified against the pinned
  `utils/Action.py`/`session.py` that an empty `action_text` really does raise
  `RuntimeError("ActionParser: No action in text")`, caught by `_classify_action`, so this isn't
  an assumed code path.
- But that proof is only ever run through the plain, in-memory `run_episode` call in
  `test_amazonbarg_environment.py`/`test_amazonbarg_measurement.py` — never through
  `ScriptedAmazonbargHarness` (hash-chained `EvidenceStore`, `verify_chain()`/`verify_seal()`) nor
  through `replay.py`'s `replay_and_verify` (independent second plugin instance, byte-identical
  final-state-hash reproduction). `GOLDEN_1_SCRIPT`/`GOLDEN_5_SCRIPT` are the only two scripts
  wired into `test_amazonbarg_harness.py` and `test_amazonbarg_replay.py`
  (`tests/test_amazonbarg_harness.py:117-127`, `tests/test_amazonbarg_replay.py:127-137`) —
  goldens 2, 3, and 4 (including the one golden whose whole point is "no protected state changed
  on an invalid action") never go through the sealed/replayed path at all.
- `docs/amazonbarg_adapter_status.md:112-125` discloses this honestly at the aggregate level
  ("Milestone 3 itself only drives 2 of the 45 pilot sessions (goldens 1 and 5) through the
  harness/replay path") but does not call out that the *specific* golden most relevant to a
  "no silent state mutation on invalid input" claim is one of the three left out. A reviewer
  skimming only the "Evidence" section of the status doc could reasonably believe the strongest
  proof mechanism had touched the invalid-action case; it has not.
- Failure scenario this leaves open: if a future change to `AmazonbargPlugin.step()`'s
  `BUYER_PHASE` branch accidentally started appending a `_pending_buyer_record` (or otherwise
  left seller-phase-reachable state behind) on an `action_error` termination, the existing
  environment-level assertions would probably still catch it — but there would be no
  hash-chained evidence record and no byte-identical-replay proof to catch a *scheduler-level*
  regression (e.g., `invalid_action_policy` interacting oddly with a terminal transition) the way
  goldens 1/5 are proven to catch it today.
- Suggested fix: add golden 4 (and ideally 2, 3) to `GOLDEN_*_SCRIPT` in both
  `test_amazonbarg_harness.py` and `test_amazonbarg_replay.py`, or at minimum state explicitly in
  `docs/amazonbarg_adapter_status.md` that the malformed-action golden's "no protected state
  changed" claim is currently proven only at the plain-`run_episode` level, not at the
  sealed-evidence/replay level.

### W2 — Latent `AttributeError` in the golden test helper for any future conflicting-interest-but-deal-closes case

- `tests/test_amazonbarg_measurement.py:320-329` (`_score_and_check_parity`)
- The component-parity block guards the `zopa` leaf correctly
  (`if envelopes["zopa"].status == "ok": assert envelopes["zopa"].metrics["deal_price"].value == ...`)
  but the very next two lines assert `envelopes["lower"].primary.value == metrics_output["D"]` and
  `envelopes["upper"].primary.value == metrics_output["D"]` unconditionally whenever `"D" in
  metrics_output`, and the block below does the same for
  `envelopes["ratio_buyer"/"ratio_seller"].primary.value` whenever `"buyer_bargained_ratio" in
  metrics_output`. `measurement.py`'s own `_measurement_gate` seals these leaves
  `invalid_measurement` (`primary=None`) whenever the case's `derived.interest == "conflicting"`
  — independently of whether `D`/`buyer_bargained_ratio` are present in `metrics_output`. Upstream
  itself (verified directly in `eval.py:Metrics.evaluate`) sets `D`/`buyer_bargained_ratio`
  whenever a `DEAL` closes, with **no check against `cost`/`budget` at all** — i.e. a
  conflicting-interest session whose scripted trajectory nonetheless closes a deal is a real,
  reachable state in this benchmark, not a hypothetical.
- I reproduced this live: scripting `toys-games_22` (the pilot's one CI session, `cost=$959.00 >
  budget=$864.93`) through `BUY $900 -> DEAL $900` instead of the shipped `BUY $850 -> REJECT ->
  QUIT` script produces `metrics_output` with `D=900.0`/`buyer_bargained_ratio=-0.373` present,
  while `scorer.score_deal_lower_bound(...)` correctly returns `status="invalid_measurement"`,
  `primary=None` (production code is correct). Calling `.primary.value` on that envelope — exactly
  what `_score_and_check_parity` does unconditionally — raises
  `AttributeError: 'NoneType' object has no attribute 'value'`.
- This is currently masked only because none of the 5 shipped goldens combine "conflicting
  interest" with "deal closes" (the one CI golden, 5, quits). It is not hit by the 106/106 green
  run today, but it is a real crash mode waiting for the next contributor who extends this test
  file's helper to the full 45-session pilot (`docs/amazonbarg_adapter_spec.md` P3/P4 explicitly
  name that as pilot-scope future work) or adds a 6th golden — they would get a confusing
  `AttributeError` instead of a clear assertion failure, defeating the parity check's own stated
  purpose for exactly the case it should be most careful about (an economically invalid deal that
  still produced upstream metrics fields).
- Suggested fix: guard the `lower`/`upper`/`ratio_*` parity assertions the same way `zopa` already
  is (`if envelopes["lower"].status == "ok": ...`), or check `derived["interest"] != "conflicting"
  and metrics_output.get("wrongAction") == 0 and metrics_output.get("closeADeal") == 1` before any
  of the four `.primary.value` accesses.

---

## MINOR

### M1 — Golden 3's category label ("invalid-unauthorized") reads as if the illegal deal were blocked; it is deliberately not

- `docs/amazonbarg_adapter_spec.md:248-252` (golden 3), `ledger_entries/amazonbarg.md:19-20`
  (five-golden taxonomy naming)
- Golden 3 (Breville, `home-kitchen_5`) is the case where a `DEAL $480` closes **below cost**
  (`$480 < cost=$524.97`) and upstream's own authenticity check (`wrongAction`) still calls it
  legitimate (it matches a genuine prior offer). This is by design — the adapter's own "Governing
  facts" section states plainly "no economic legality live: a DEAL below cost or above budget is
  not blocked at generation time" — and I confirmed this directly against the pinned
  `session.Agent2AgentSession.agents_talk_with_action` (there is no cost/budget check anywhere in
  the live loop; only `eval.py:Metrics` checks it, ex post). The terminal state genuinely changes
  (`termination_reason="deal"`, a real deal price is recorded) — nothing is "protected" from this
  mutation at the state layer, only caught afterward by the added `amazonbarg_zopa_membership`
  leaf.
- The prose is internally consistent and this is correctly implemented and tested — this is not a
  functional bug. But the golden-category label "invalid-unauthorized" (shared verbatim across
  this adapter, `aucarena`, and `negarena` per the ledger's cross-adapter taxonomy note) invites
  exactly the opposite reading from what actually happens here: a reviewer skimming only the
  five-golden category names (as the task brief that generated this review round evidently did,
  given it asks "does the invalid-action golden prove no protected state changed") could
  reasonably expect golden 3 to be the one proving a block, when the adapter's own actual
  "nothing mutates on bad input" proof lives entirely in golden 4, and golden 3's whole point is
  the opposite — that the environment *does* let an economically-invalid deal through, and only
  scoring catches it.
- Suggested fix: a one-line addition to `docs/amazonbarg_adapter_spec.md` §4's golden 3 entry
  (and ideally the shared `docs/operations/benchmark_qc.md` the ledger already recommends authoring) stating
  explicitly "this golden proves scoring-layer detection of an environment-permitted illegal
  deal, not state-layer prevention — see golden 4 for the latter," so the five-golden taxonomy's
  two different flavors of "invalid" are not conflated by a future reader.

---

## What I checked and found clean (no write-up needed beyond this line)

- **Gate 1 (corpus admission).** `pins.json`'s 18 file-level SHA-256 digests match a direct
  re-read of the pinned checkout (`test_build_pins_file_hashes_match_a_direct_read`, re-verified
  independently); the 930-session declared enumeration vs. the 45-session materialized pilot are
  correctly kept as separate claims (spec §1/§1.2); the importer is byte-identical across two
  runs and the checked-in `cases/amazonbarg/pilot/*.json` matches a fresh import byte-for-byte
  (`test_checked_in_case_directory_matches_a_fresh_import`); duplicate `case_id`s raise
  (`cases.py:434-436`); `PILOT_CATEGORY_FILES` is a hardcoded tuple, no randomness/resampling
  anywhere in the selection path.
- **Verifier declarations vs. `docs/research/verifier_taxonomy.md`.** All five leaves are
  `evaluation_class="deterministic"` and genuinely are (scripted trajectories, no sampling,
  nothing judge-dependent anywhere in this adapter). No derived quantity is sealed as if it were
  independent confirmation: the two bound leaves' `primary` is openly the same realized deal price
  read from the same delegated `D` field (by design, per spec §2), and the "component parity"
  tests are explicitly scoped as a determinism check (two fresh delegated calls on identical
  input), never advertised as an independent-oracle correctness check. The adapter correctly uses
  the real `_REFERENCE_KINDS`/`ObjectiveScopeSpec.direction`/`ScoreEnvelope.status` constraints
  from `src/aeread/shared_runner/measurement.py` rather than the taxonomy doc's stale prose names
  (`outcome_support_normalized` etc.), and the three resulting doc/code drifts are already filed
  in `ledger_entries/amazonbarg.md`.
- **Replay honesty.** `replay.py` re-executes: `replay_episode` drives the real `run_episode`
  with a second, independently constructed `AmazonbargPlugin`/registry and a
  `RecordedResponseSource` that only replays the recorded *raw text*, forcing `parse_action`/
  `legal`/`step` to run again; `score_replayed_episode` recomputes the score via a fresh delegated
  `eval.py:Metrics` call over the *replayed* history, never reading back a stored score. The one
  tamper test (`test_replay_of_a_tampered_response_diverges_rather_than_raising`) honestly proves
  and documents that a tampered reply diverges silently rather than raising (no tool calls exist
  here to cross-check against, unlike `tau3_retail`) — correctly disclosed as an external, not
  internal, guarantee in both the module docstring and the status doc.
- **Independent execution, not just reading the status doc's claims.** Ran
  `test_amazonbarg_{cases,environment,harness,measurement,replay,shim}.py` against the real
  pinned upstream checkout: 106/106 passed, 0 skipped, matching the status doc exactly. Hand-
  traced `parseReply`/`ActionParser`/`Metrics.evaluate` in the pinned upstream source to confirm
  the adapter's claims about upstream's own behavior (empty-action parse failure, authenticity/
  fake-deal detection order, ZOPA/ratio arithmetic) rather than trusting the docstrings.

