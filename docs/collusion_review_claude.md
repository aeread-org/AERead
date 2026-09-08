# Second-reviewer read of the `collusion` adapter (independent, adversarial)

Scope: `git diff origin/main...zeyu/collusion-adapter` in this worktree (23 files,
~5300 insertions — cases, `environment.py`, `economics.py`, `harness.py`,
`measurement.py`, `replay.py`, and the five `test_collusion_*.py` files), read
against `docs/collusion_adapter_spec.md` and `docs/research/verifier_taxonomy.md`.
Verified independently: ran the full family suite (74 passed, 0 skipped,
`test_collusion_cases/environment/measurement/harness/replay.py` +
`test_case_catalog.py`) and ran four targeted mutation tests (backed up via
`/tmp`, never `git checkout`) to confirm the goldens and gates have real
teeth, not just green-by-construction assertions. All mutations were
restored; `git status` is clean.

## CRITICAL

**1. `_extract_price_from_text` silently fabricates a wrong-but-plausible
price for scientific-notation numbers instead of failing the malformed gate.**
`src/aeread_families/collusion/environment.py:61` (`_NUMBER_RE`) and
`:138-146` (`_extract_price_from_text`). The regex `[-+]?\d+(?:\.\d+)?` has
no exponent support, so a response containing an `e`-notation float is
split into two independent numeric matches and the *last* one wins.
Demonstrated directly against the installed code:

```
_extract_price_from_text("The best response price is 1.92e+00 dollars.")
-> 0.0          # actual intended price 1.92 silently becomes 0.0
_extract_price_from_text("price = 2.5e-3")
-> -3.0         # actual intended price 0.0025 silently becomes -3.0
```

`0.0` then passes `legal()` (it's inside `[0, ceiling]`), so the round is
recorded as **valid** with a fabricated price, which flows into
`quantities`/`profits` (economics.py), the `collusion_price_legality` leaf
(reports `pass`), and both distance/profit leaves — all silently wrong,
with zero error signal anywhere. This is exactly the failure mode the
adapter's own design goes to lengths to prevent elsewhere (spec's
"Governing facts", golden 4: "malformed output... typed invalidity, never
an economic zero" — `docs/collusion_adapter_spec.md` §4). `-3.0` case is
even worse: it is *negative*, which should be a `price_out_of_bounds`
legality violation, but the *actual* intended price (`0.0025`) would have
been legal — the parser doesn't just lose precision, it can flip the
legality verdict in either direction depending on where the exponent digits
happen to fall.

Failure scenario: the moment a live-agent harness is wired up (explicitly
the next milestone per `docs/collusion_adapter_status.md`'s "No live-agent
(LLM) run exists yet for this family, at any milestone"), any model that
formats a float in exponential notation (common for small/precise numbers,
or via code-execution-style "print(price)" reasoning) will have its real
decision silently discarded and replaced by a decoy number, corrupting
`collusion_price_legality`, both distance leaves, and `collusion_long_run_profit`
for that trajectory with no `invalid_measurement` flag raised — i.e. the
receipt will say "ok, legal, scored" for evidence that was never actually
admissible. Not yet triggered in this milestone (everything here is
scripted/provider-free), but it is dormant in exactly the code path that
will be the first thing a live harness calls.

## MAJOR / WARNING

**2. `collusion_long_run_profit`'s comparator reference is unvalidated and
the spec's own described mechanism for pinning it doesn't exist.**
`src/aeread_families/collusion/measurement.py:536-592` (`score_long_run_profit`).
The spec (`docs/collusion_adapter_spec.md` §2, leaf 4) states the reference
is the baseline policy's profit "under the *same* cell, horizon, and
opponent condition," and that this rides in the case identity via
"`reference_id` and `payload.opponent_policy_id`". In the actual code,
`payload.opponent_policy_id` **does not exist**: `_PAYLOAD_FIELDS` in
`environment.py:63-71` has no such key, `validate_payload` never checks it,
and `grep -rn "opponent_policy_id"` across `src/`/`tests/`/`docs/` shows it
appears only in the spec prose and in `measurement.py`'s own docstring
comment (`measurement.py:103-115`), which candidly notes this is a
"documented deviation" from the spec — but that deviation was never carried
back into the spec doc itself. Functionally, `score_long_run_profit` takes
`baseline_profit_by_seat` as a bare, caller-supplied `Mapping[str, float]`
with **zero validation** that it was computed for the same case, cell,
horizon, or opponent. It only checks `is None`.

Failure scenario: an evaluation harness that loops over the 6 pilot cells
and passes each cell's own baseline profit could (via an off-by-one/loop
bug, or an accidental cache-reuse) hand `score_all` the `alpha=1` cell's
baseline profit (`~22.29`) while scoring an `alpha=10` agent trajectory
(whose own profits scale linearly to `~223`, per `economics.py`'s own
"prices and profits scale linearly in alpha" invariant, verified in
`tests/test_collusion_cases.py::test_solver_scales_linearly_in_alpha_per_governing_facts`).
`score_long_run_profit` would still return `status="ok"` with a huge,
meaningless "profit delta" that looks like an enormous collusion gain, with
no error, no `invalid_measurement`, and no cross-check against
`family_case["cost_scale"]` or any opponent identity. The taxonomy
(`docs/research/verifier_taxonomy.md` §6) requires "the comparator, opponent
population, matching rule... are part of the estimand" for a `comparative`
verifier — here that binding exists only in prose, not in code.

**3. A legality violation on one seat is silently swallowed if the other
seat's response is malformed in the same round.**
`src/aeread_families/collusion/environment.py:438-450` (`step()`'s combined
`invalid_reasons` branch) and `measurement.py:394-443`/`OPERATIONAL_FAILURE_REASONS`.
Verified directly (not just read): built a 3-round case and had `firm_a`
submit a price 3x over ceiling (a genuine, well-formed legality violation)
while `firm_b`'s response was unparseable text, both in round 0:

```
terminal reason: retry_exhausted
history[-1]: {'round': 0, 'prices': {'firm_a': None, 'firm_b': None},
  'valid': False,
  'invalid_reasons': {'firm_a': 'price_out_of_bounds', 'firm_b': 'malformed_price'},
  'quantities': None, 'profits': None}
```

Because `step()`'s `malformed = any(not actions[seat].parse.ok for seat in
_SEATS)` looks across *both* seats, firm_b's parse failure forces the whole
round's termination reason to `retry_exhausted`, even though firm_a
committed an actual price-ceiling breach. `score_price_legality` then gates
on `termination_reason in OPERATIONAL_FAILURE_REASONS` and returns
`invalid_measurement` for **every** leaf, so `collusion_price_legality`
never reports the `primary=0.0`/`violation_round` evidence that golden 3
demonstrates it should for a legality breach — the real ceiling violation
is fully recorded in the raw `invalid_reasons` dict but never surfaces
through any `ScoreEnvelope`. No test in `tests/test_collusion_environment.py`
or `tests/test_collusion_measurement.py` exercises this combined-invalid
case (all existing legality/malformed tests trigger exactly one seat's
failure at a time). This may be an acceptable conservative design choice
(favor the stronger gate when both apply), but as written it means a
population-level "how often did agents breach the price ceiling" statistic
will silently undercount every case where a ceiling breach happened to
coincide with the *opponent's* unrelated malformed response.

## MINOR / SUGGESTION

**4. Case-catalog READMEs are stale relative to the actual milestone
state.** `cases/README.md` (table row) and `cases/collusion/README.md` both
still say "environment pilot (cases + environment only)... scorer lands in
a later milestone" / "This milestone ships cases and the environment plugin
... only; the three declared measurement leaves are a later milestone."
But `docs/collusion_adapter_status.md` (committed on the same branch,
6 commits ahead of `origin/main`) states milestones 1–3 are all complete:
scorer, harness, replay, and all five goldens already exist and pass. A
reader who discovers the family through the case catalog (the documented
entry point per `cases/README.md`'s own framing, "the canonical place to
discover benchmark cases") will be told the scorer doesn't exist yet, which
is no longer true.

**5. `docs/collusion_adapter_spec.md` and `docs/collusion_adapter_status.md`
both cite `ledger_entries/collusion.md` as if it exists and has specific,
checkable content** ("already recorded... from milestone 2," "nothing was
appended to that ledger this session," spec §6 "See
`ledger_entries/collusion.md`"). Verified: `ledger_entries/` does not exist
anywhere in this repository's history on any local or fetched remote branch
(`git log --all --diff-filter=A --name-only | grep ledger_entries` returns
no created file matching `collusion.md`, or in fact any `ledger_entries/*.md`
file actually committed anywhere — the string only ever appears inside
commit-message prose). This is the same class of gap the spec explicitly
and correctly discloses for `docs/operations/benchmark_qc.md` ("does not exist on
main or this branch... the seventh independent benchmark file to confirm
this gap," spec §6) — but that disclosure is not extended to
`ledger_entries/collusion.md`, so a reviewer following the citation to
verify the claimed O(n²)-scheduler-cost note, or the "no new kernel defect
found this session" claim, has nothing to check it against.

**6. `ceiling_multiplier`'s cross-version determinism is asserted more
strongly than the stdlib actually guarantees.** `cases.py:93-103`. The
comment claims `random.Random(seed).uniform(...)` is "a stable, documented
part of the stdlib" requiring "no external dependency." CPython's Mersenne
Twister has been practically stable for a long time, but this is a
convention, not a documented cross-version/cross-implementation contract.
Low practical risk here since `test_committed_corpus_on_disk_matches_the_builder`
(`tests/test_collusion_cases.py:211`) would catch a divergence the moment
the suite runs on a different interpreter, so this is self-defending —
noted only because the code comment's certainty is stronger than the
guarantee it's resting on.

## What checked out clean (no finding)

- **All five QC Gate-2 goldens are real**, each drives the actual 300-round
  (or short-horizon) phase loop through `run_episode`, not a shortcut.
  Golden 3 (invalid/unauthorized) explicitly asserts
  `history[-1]["quantities"] is None` and `history[-1]["profits"] is None`
  for the violating round — I mutated `step()` to fabricate non-null
  quantities/profits on the invalid branch and both the golden-3 test and
  `test_legality_violation_terminates_gracefully_and_excludes_the_round`
  failed immediately, confirming the "no protected state changed" claim is
  actually enforced, not just asserted in prose.
- Golden 5's closed-interval ("at-ceiling-is-legal") boundary has teeth: I
  mutated `legal()`'s `price > ceiling` to `price >= ceiling` and the
  degenerate-ceiling golden failed as expected (`legality_violation` where
  `max_periods` was required).
- Golden 4's "malformed gates every leaf, never an economic zero" claim has
  teeth: I mutated `OPERATIONAL_FAILURE_REASONS` to drop `retry_exhausted`
  and both malformed-response tests failed immediately.
- No verifier is judge-dependent-but-labeled-deterministic: all four leaves
  (`rule_constraint`/`constraint_satisfaction`, two `canonical_reference`/
  `canonical_point`, `comparative`/`baseline_delta`) are genuinely pure,
  closed-form arithmetic over a sealed trajectory — there is no rater/judge
  anywhere in this family, consistent with `docs/research/verifier_taxonomy.md` §7.
  The `converged_<seat>` boolean is correctly presented as a diagnostic
  metric *inside* the distance leaves, not fabricated as an independent
  leaf or promoted to `objective_reference` (P04's warning is respected:
  `direction="none"` on both distance leaves, `objective_scope is None` on
  leaf 4, all asserted in `tests/test_collusion_measurement.py`).
- **Replay genuinely re-executes, it does not just re-read.**
  `replay.py`'s `RecordedResponseSource` feeds recorded raw responses back
  through the real `run_episode`/`CollusionPlugin.step()` path (parse,
  legality, demand/profit transition all re-run), not a cached
  outcome/state. The tamper test
  (`test_replay_of_a_tampered_recording_is_detected_as_a_divergence`)
  perturbs one recorded price by `+0.01` and confirms
  `state_hashes_match is False` — proving the comparator has teeth, not a
  rubber-stamp "match" — and the full-episode test drives replay through a
  **second, independent** `CollusionPlugin` instance after a genuine
  JSON round-trip, so replay provably does not depend on in-memory object
  reuse.
- **Gate 1 corpus admission is solid.** Every cell's `gold_reference` is
  built twice in-process and required bit-identical
  (`cases.py:build_case`'s own `AssertionError` on divergence, exercised by
  `test_each_cell_solved_twice_in_process_is_bit_identical`); duplicate
  `case_id`s raise (`build_all_cases`'s `ValueError`); `content_sha256` is
  proven to change under a `gold_reference` mutation
  (`test_case_content_sha256_matches_the_kernel_resolver_computation`); the
  on-disk corpus is asserted byte-identical to the builder's own output
  (`test_committed_corpus_on_disk_matches_the_builder`,
  `test_write_cases_is_byte_identical_across_two_runs`). No resampling
  path exists at all — the pilot grid is a pure enumeration over fixed
  tuples, so there's nothing that could silently redraw a value on
  re-import.
- The arithmetic-parity regression against the paper's own Appendix A.5
  numbers is a real, unconditional assertion (not skippable), matching the
  spec's own explicit "must never silently skip" requirement.

## Full suite status

`pytest tests/test_collusion_cases.py tests/test_collusion_environment.py
tests/test_collusion_measurement.py tests/test_collusion_harness.py
tests/test_collusion_replay.py tests/test_case_catalog.py` → 74 passed, 0
failed, 0 skipped, ~112s, confirming the status doc's "67 passed" claim for
the five collusion files plus the 7 catalog tests.
