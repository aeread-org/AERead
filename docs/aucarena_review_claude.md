# aucarena adapter — second-reviewer read-only audit (Claude)

Scope: `git diff origin/main...HEAD` on `zeyu/aucarena-adapter`
(commits `9b09d98`..`dea5337`), read against
`docs/aucarena_adapter_spec.md`, `docs/research/verifier_taxonomy.md`, and the pinned
upstream checkout at `/Users/sunzeyu/Documents/econ benchmark/upstream-aucarena`
(confirmed on disk at commit `d0f3bc851eb376d4ea5e69ae5fe52ec5be987bb3`,
matching the pin). Verified: full aucarena suite (100 passed) and full repo
suite (826 passed, 31 skipped, 1 xfailed) both green, matching
`docs/aucarena_adapter_status.md`'s claims exactly, no discrepancy.

Independently re-derived (not just re-read) against upstream source: line
ranges and bodies of `bid_rule` (`bidder_base.py:384-410`), `bid_sanity_check`
(`:623-637`), `win_bid`/`lose_bid`/`set_withdraw` (`:789-809`), `record_bid`/
`check_hammer`/`hammer_fall`/`_num_bids_in_round` (`auctioneer_base.py:63-173`),
and `Item` (`item_base.py:6-32`) all match the vendored transcriptions in
`_vendored_upstream.py` exactly — provenance headers are not fabricated.

## Summary

No critical defects found. The diff is unusually well-guarded: every one of
the five QC Gate-2 goldens is exercised through the real kernel scheduler
(not a hand-wired shortcut), the invalid-action golden explicitly asserts
zero protected-state mutation, replay genuinely re-executes through
`run_episode` (not a re-read of stored final state), and Gate-1 corpus
admission has real digest/dedup/determinism tests. One WARNING-level
verifier-declaration nuance and a few SUGGESTIONs are below.

## WARNING

**1. `aucarena_hammer_rule`'s "independent" recompute is not independent of
`environment.py`'s own legality gate — only of its hammer/tie-break
arithmetic.**
`src/aeread_families/aucarena/measurement.py:483-580` (`score_hammer_rule`),
specifically lines 522-526, builds its `round_bids` input from
`[... for record in phase_instance.actions if record.envelope.valid]`.
`record.envelope.valid` is *computed by* `environment.py`'s own
`legal()`/`parse_action()` (scheduler.py:570: `valid = parsed.ok and
legality is not None and legality.legal`), not a raw fact recorded
independently of the environment's own decision. The module docstring
(measurement.py:27-35) and the leaf's own claim characterize this as
"independently reproduced ... from nothing but the sealed episode
evidence" and "never from environment.py's own live state" — true for the
hammer/tie-break *arithmetic*, but the *set of bids being hammered over* is
inherited from the environment's own accept/reject partition, not
independently re-derived by this leaf.
- Failure scenario: if `environment.py.legal()` ever had a bug that
  incorrectly accepted an illegal bid (`envelope.valid=True` when it should
  be `False`), `aucarena_hammer_rule` alone would silently compute a
  "matching" hammer determination over the bogus bid and report
  `primary=1.0` — it would not, by itself, catch the legality bug. In
  practice this is caught because `aucarena_bid_legality`
  (`measurement.py:384-442`) *does* independently recompute legality from
  each action's frozen pre-round observation and raises
  `AucArenaMeasurementError` on disagreement — but that protection is a
  property of always running both leaves together, not something
  `aucarena_hammer_rule` enforces or documents as a precondition of its own
  independence claim. A future consumer that only asks for the
  `aucarena_hammer_rule` leaf (e.g. a partial-leaf run, or a leaf allowlist)
  would get a leaf whose "independent parity" framing is weaker than
  advertised.
- Suggested fix (not applied, read-only review): either note the
  dependency explicitly in the leaf's `estimand`/docstring ("assumes
  `aucarena_bid_legality` has independently verified the same episode"), or
  have `score_hammer_rule` recompute the accept/reject partition itself
  from `record.parse` + a fresh `bid_sanity_check` call rather than reading
  `record.envelope.valid`.

I verified this is not exercised by the existing mutation test
(`tests/test_aucarena_parity.py:150-171`) — that test mutates
`transition.consequences["winner"]` directly, not the upstream
`envelope.valid` partition, so it does not probe this particular gap.

## SUGGESTIONS

**2. `parse_action`'s `"-1" in response` substring check can misparse a
well-formed negative-looking bid text, inherited from upstream, not new.**
`src/aeread_families/aucarena/environment.py:327-328` mirrors upstream's own
`if '-1' in result:` (`auctioneer_base.py:196`) verbatim, including its
substring (not exact-match) semantics — a raw response like `"$-15"` would
be classified as a withdraw (`bid_price=-1`) rather than parsed as `-15`.
This is a faithful reproduction of an upstream quirk (correctly documented
as such), not a defect introduced by this adapter, and none of the five
goldens' scripted policies ever produce such a string. Flagging only so a
future scripted-policy author knows this edge case exists before writing a
policy that emits a response containing a literal `-1` substring for a
non-withdraw reason.

**3. `docs/aucarena_adapter_spec.md`'s "Governing facts" say
`docs/operations/benchmark_qc.md` does not exist in this repo, but the review task
(and file layout) implies a QC-gate contract exists elsewhere.** This is
called out honestly in the spec itself (§ "Governing facts" and the
ledger note at the bottom, "logged to `ledger_entries/aucarena.md`"), so it
is not a new gap this diff introduces — just noting I could not
cross-check the "QC Gate 1/2" terminology against a canonical
`benchmark_qc.md` definition; the spec's own inference from
`verifier_taxonomy.md` §9 and this task's own five-golden enumeration is
the only available ground truth, and it is applied consistently throughout
the diff.

**4. Golden 4 (`malformed_operational_01`) never asserts `agent.profit` is
untouched, only `agent.budget` and `winner`.** `tests/test_aucarena_
environment.py:254-266` (`test_golden_4_agents_gibberish_is_malformed_
not_illegal`) checks `result.outcome["seats"]["agent"]["budget"] == 3200`
and `result.outcome["items"][0]["winner"] == "field_high"`, but does not
also assert `profit == 0` the way golden 3's equivalent test does
(`test_golden_3_agents_150_bid_is_rejected_by_legal_with_zero_mutation`,
line 244: `assert result.outcome["seats"]["agent"]["profit"] == 0`). Given
`profit` can only change via `win_bid` (only reachable when `winner ==
"agent"`, which is independently disproven by the `winner == "field_high"`
assertion), this is a logical redundancy rather than a real coverage gap —
but for symmetry with golden 3 and to make the "zero mutation" claim
equally explicit for both invalid-action goldens, an
`assert result.outcome["seats"]["agent"]["profit"] == 0` would cost nothing
and close the asymmetry.

## Gate-1 corpus admission (digests, dedup, no silent resampling) — checked, clean

- `src/aeread_families/aucarena/cases.py:194-263` (`build_case`) rejects
  item ids outside the pinned pool, repeated item ids, repeated seat ids,
  and an empty roster before ever computing a digest; `import_all_cases`
  (`:266-278`) raises on a duplicate `case_id`.
- `content_sha256` is computed via the same kernel resolver
  (`case_content_sha256`) every other family uses, verified stable under
  re-hash at build time (`cases.py:260-262`) and independently re-verified
  in `tests/test_aucarena_cases.py:183-192` (`test_case_content_sha256_
  matches_the_kernel_resolver_computation`), including a mutation
  (`budget += 1`) that changes the digest — not a vacuous check.
- `tests/test_aucarena_cases.py:240-256` (`test_importer_is_byte_identical_
  across_two_runs`) and `:272-284` (`test_checked_in_case_files_match_a_
  fresh_import`) both ran clean against the real pinned upstream checkout
  during this review — the checked-in `cases/aucarena/pilot/*.json` files
  are not stale relative to the importer.
- No resampling path exists in this family at all (world_seed is a fixed
  literal per golden in `GOLDENS`, spec-documented as "found by running the
  environment, not derived by hand" for the `agent` budget=3200 constant) —
  there is no retry-on-bad-outcome or seed-search code anywhere in
  `cases.py`/`environment.py`.
- Colon-joined id rejection: `tests/test_aucarena_cases.py:207-232`
  confirms `CaseManifest.from_dict` rejects `"aucarena:pilot:successful_01"`
  via the shared `_ID_RE` grammar (`schemas.py:20`), matching the tau3
  suite's own regression test.

## QC Gate-2: five goldens and the invalid-action "no protected state changed" proof — checked, clean

- All five goldens are driven through the real
  `aeread.shared_runner.scheduler.run_episode` with the shipped
  `ScriptedAucArenaHarness` (no hand-wired shortcut) in
  `tests/test_aucarena_environment.py`, `test_aucarena_measurement.py`,
  `test_aucarena_parity.py`, and `test_aucarena_replay.py`.
- Golden 3 (`invalid_unauthorized_01`,
  `test_golden_3_agents_150_bid_is_rejected_by_legal_with_zero_mutation`,
  environment.py test file lines 229-246) explicitly asserts: parse
  succeeds (`parse.ok is True`), `legality.legal is False`,
  `envelope.valid is False`, **and** `agent.budget == 3200` (unchanged),
  `agent.profit == 0`, `winner == "field_high"`,
  `hammer_price == 1000` — i.e. the item resolves exactly as if `agent`
  had never bid. This is a genuine before/after proof, not an assumption.
- Golden 4 (`malformed_operational_01`) is proven to fail through a
  *distinct* code path from golden 3
  (`test_golden_3_and_4_fail_through_distinct_code_paths`,
  lines 269-277: `parse.ok is True` + `legality.legal is False` for golden 3
  vs. `parse.ok is False` + `legality is None` for golden 4 — `legal()` is
  never reached for the malformed case) and is never folded into the
  legality leaf's failure count (`measurement.py:396-398,
  431-433`: `malformed_action_count` tracked separately from
  `violations`).
- Golden 5's empty comparator population correctly yields
  `status="invalid_measurement"`, `primary=None`,
  `validity.status="invalid"` with a populated `reasons` tuple
  (`measurement.py:601-616`), matching `verifier_taxonomy.md` §9's "must
  not be scored as an economic zero" requirement exactly, and this status
  is proven to survive replay unchanged
  (`test_replay_and_verify_reproduces_the_invalid_measurement_status`).

## Verifier declarations vs. `verifier_taxonomy.md` — checked, clean apart from item 1 above

- No leaf is `judge_dependent`; all four are `evaluation_class="deterministic"`
  (correct: the scripted-rule-bidder scope has no judge and no
  provider/sampling variance to justify `stochastic_estimator`).
- No `objective_reference` leaf is declared, matching the P21 row in both
  `verifier_taxonomy.md` §13 and `problem_bound_case_audit.md:59`
  ("profit and TrueSkill do not solve the auction policy game") —
  confirmed by `test_no_objective_reference_leaf_is_declared`.
- `verifier_family`/`reference_kind` pairings
  (`rule_constraint`/`state_invariant`, `rule_constraint`/
  `constraint_satisfaction`, `rule_constraint`/`temporal_property`,
  `comparative`/`head_to_head`) are all accepted by the shared kernel's own
  `_REFERENCE_KINDS`/`_REFERENCE_SCOPE` tables
  (`src/aeread/shared_runner/measurement.py:27-69`), not a local
  reimplementation — verified directly by
  `test_bid_legality_reference_kind_rejected_by_a_disallowed_scope`, which
  proves the kernel's own gate, not this module's, would reject a bad
  pairing.
- The `aucarena_profit_vs_field` comparator (frozen field seat ids,
  `model_name`, budgets) is pinned into `reference.source_sha256` via
  `_field_roster_sha256` (measurement.py:266-280) — the pairing is part of
  the estimand per taxonomy §6, not an afterthought.

## Replay honesty — checked, clean

`replay_episode` (`src/aeread_families/aucarena/replay.py:190-218`) rebuilds
`initial_state` and drives the *real* scheduler
(`aeread.shared_runner.scheduler.run_episode`) with a
`RecordedResponseSource` feeding back only the raw recorded response text —
this is genuine re-execution through the full phase graph, `parse_action`,
`legal`, and `step`, not a re-read of the original run's stored
`final_state`. Confirmed by:
- `tests/test_aucarena_replay.py:217-251` round-trips the recorded episode
  through actual JSON text (`RecordedEpisode.from_json(recorded.to_json())`)
  before replaying, and replays through a *second*, independently
  constructed `AucArenaPlugin`/`PluginRegistry` instance
  (`_independent_replay_setup`), never the object that produced the
  original run.
- The mutation test
  (`test_tampering_a_mid_trajectory_bid_is_caught_immediately_not_silently_
  replayed`) tampers a real recorded bid value and shows the *real*
  scheduler (not a local diff) raises `SchedulerContractError` before the
  replayed episode can complete — proving replay is not a passive echo.
- `compare_episode_results` is proven non-vacuous both synthetically
  (`test_compare_episode_results_reports_specific_mismatches_not_one_
  boolean`) and against two genuinely different live runs
  (`test_compare_episode_results_would_report_a_genuine_divergence`).

## Other checks performed, no defect found

- Confirmed `pre_state_sha256`/`post_state_sha256` (scheduler.py:718,788,
  852) are computed over the full canonical state, so the "byte-identical
  replay" claim is backed by an actual full-state hash comparison, not a
  partial one.
- Traced the `prev_round_max_bid` vs. `highest_bid` state variables used
  respectively by `environment.py.legal()` and
  `measurement.py.score_bid_legality`'s independent recompute (which reads
  `observation["highest_bid"]`, not a separately-exposed
  `prev_round_max_bid` field) and confirmed by hand-tracing `check_hammer`'s
  branches that the two values are invariant-equal at every point either
  is consulted for legality — this is a real invariant of the state
  machine, not coincidental test-fixture luck, so the two "independent"
  legality computations are genuinely computing the same thing from
  different fields.
- Verified `phase_instance.actions` ordering (scheduler.py:735-772, actors
  processed in `eligible_actors()` order) matches the roster-filtered
  order `environment.py.step()` iterates in, and that both `step()`'s and
  `measurement.py._recompute_round`'s `call_index`-seeded
  `random.Random(...)` tie-break draws are therefore seeded identically —
  the "component parity" claim between the live run and the independent
  recompute is real, not accidental.
- Verified the family imports nothing upstream (`grep` for
  `langchain`/`torch`/`vertexai`/`transformers`/`trueskill` across
  `src/aeread_families/aucarena/` and the test files returns nothing) and
  makes no network calls.
- Ran the full repo suite (`pytest tests/ -q`): 826 passed, 31 skipped,
  1 xfailed — identical to the numbers claimed in
  `docs/aucarena_adapter_status.md`, confirming this diff does not
  silently break or skip anything elsewhere in the repo.
