# alympics.wac adapter — second-reviewer adversarial review (Claude)

Scope: full diff vs `origin/main` (23 files, ~6.5k lines: `cases/alympics_wac/base/*`,
`docs/alympics_adapter_spec.md`, `docs/alympics_adapter_status.md`,
`src/aeread_families/alympics_wac/*`, `tests/test_alympics_wac_*.py`), read against
`docs/alympics_adapter_spec.md` and `docs/verifier_taxonomy.md`. Read-only; nothing edited.
Verified: pinned upstream checkout present at commit `caed7c8c3b8f9de9ac8be1ba54407a51087affc5`
(clean, matches the pin); full family suite (89 tests) passes locally; the checked-in
`cases/alympics_wac/base/*.json` are byte-identical to a fresh `cases.py` regeneration
(Gate‑1 "importer run twice" property genuinely holds, not just asserted by a unit test).

## Summary

No hidden logic bugs were found in the settlement/state-machine code itself (traced
`step()` → `_delegate_round()` → upstream's real `run_single_round`/`_check_winner` by
hand against the pinned upstream source, including for an over-balance bid). The
material findings are about **QC Gate‑2 completeness and honesty of the golden claims**,
specifically goldens 3 and 4, which the task asked to scrutinize directly.

CRITICAL: 0 · MAJOR: 2 · MINOR: 3

---

## MAJOR

### M1 — Golden 3 (invalid/unauthorized bid) is never driven end-to-end through `run_episode`/the Mode C phase graph, contrary to spec §5's explicit test plan

`docs/alympics_adapter_spec.md:109` requires: *"e2e. Each of the 5 goldens driven through
the Mode C phase graph with scripted per-instance `LLM.call` replacements (§3); assert
Leaf 1-4 values match the hand-derived/verified expectations in §4 exactly."*

Golden 3's only coverage is:
- `tests/test_alympics_wac_environment.py:312` (`test_delegate_round_flags_an_over_balance_bid_as_illegal_but_still_settles`) — calls `environment._delegate_round()` **directly**, bypassing `observe`/`parse_action`/`legal`/`step` entirely.
- `tests/test_alympics_wac_environment.py:337` (`test_legal_hook_never_rejects_an_over_balance_bid_action`) — calls `plugin.legal()` directly, not via a running episode.
- `tests/test_alympics_wac_measurement.py:333-417` (`_one_round_over_balance_evidence` / `test_golden_3_over_balance_bid_becomes_invalid_measurement_never_a_legal_loss`) — again calls `_delegate_round()` directly and **hand-constructs** the `round_log` dict that is fed to the measurement scorers, rather than obtaining it from a real `step()` call.

By contrast goldens 1, 2 and 5 each have a genuine `run_episode(...)` (or
`ScriptedAlympicsWacHarness` through `run_episode`) driven test
(`test_reference_baseline_runs_full_20_rounds_end_to_end_through_run_episode`,
`test_conservative_focal_seat_ends_with_lower_wealth_than_proportional_rivals`,
`test_zero_supply_degenerate_eliminates_every_seat_identically_at_round_4`, plus the
harness/measurement equivalents).

**Failure scenario:** `environment.py:573-659`'s `step()` is the code that actually
assembles `bids` from `actions`, snapshots `players_before`, and writes the
`round_log` entry (`bid_legal`, `winners`, `players_before/after`) that the measurement
layer consumes. None of that wiring is exercised for an illegal bid. A future edit to
`step()` (e.g. a seat-ordering mismatch between `alive_seats` and `actions`, or an
off-by-one in when `players_before` is snapshotted relative to `_delegate_round`) could
silently break golden 3's real path while every existing test for it (which bypasses
`step()`) keeps passing.

### M2 — Golden 4 (malformed/operational failure) is not merely untested end-to-end, it is structurally unreachable through any real production code path

Traced directly against the pinned upstream source
(`upstream-alympics/src/waterAllocation.py`, `run_single_round`/`_parse_result`): both of
upstream's `LLM.call` sites are unconditionally replaced by the adapter **before**
`run_single_round` is ever invoked —
`environment.py:298-312` rebinds `player.llm.call` for every seat and `wa.llm.call` for
the game's own parser to closures that always return `json.dumps({p.name: p.bidding for
p in survivors})`, i.e. valid, complete JSON by construction. The `KeyError`/`TypeError`
golden‑4 failure modes are reachable **only** via the private `force_malformed` parameter
of `_delegate_round` (`environment.py:236-245`) — and `step()`'s own real call site
(`environment.py:600-608`) never passes `force_malformed`; it is always `None`. This is
even documented candidly in `cases.py:58-62`: *"`malformed_action` is reachable only
through environment.py's internal test-only `force_malformed` hook … never through any
real scripted policy in the 7 grid cells."*

**Failure scenario:** `docs/alympics_adapter_spec.md`'s §4 golden table presents
"Malformed-operational" as a "Verified" real scenario ("raises `KeyError` inside
`run_single_round`") without disclosing, in the spec itself, that this branch can never
actually fire during any live-model or scripted-policy run of this adapter — a QC
auditor who reads only the spec (not `cases.py`'s inline comment) could reasonably
believe golden 4 demonstrates a defect class the adapter can encounter in operation, when
in fact it only proves a defensive `except` clause doesn't crash the process if reached
by hand. This matters specifically for Gate‑2 "are all five goldens real": 3 are real and
e2e, 1 (golden 3) is real but only unit-tested, and 1 (golden 4) is not reachable through
the adapter's real interface at all.

---

## Notes on the review's specific questions

- **Does the invalid-action golden prove no protected state changed?** Partially, and
  only at the unit level. `test_delegate_round_flags_an_over_balance_bid_as_illegal_but_still_settles`
  (`tests/test_alympics_wac_environment.py:312-334`) does prove the load-bearing
  invariant: `outcome.winners == ("eric",)` (alex's 10,000 bid never buys a win) and
  `outcome.players["alex"] == {"balance": 70, "hp": 7, "no_drink": 2}` (an ordinary loss
  penalty, not a special "illegal-but-rewarded" outcome). This is also independently true
  at the source: upstream's real `_check_winner` (`waterAllocation.py`) itself gates
  admission on `player.bidding <= player.balance`, so an over-balance bid cannot win
  regardless of the adapter's own Leaf‑3 bookkeeping. What is **not** proven is that this
  invariant survives the real `step()`/`run_episode` plumbing (see M1) — the golden
  proves the upstream mechanics and the adapter's isolated helper are safe, not that the
  wired-together kernel path preserves the invariant.
- **Verifier-declaration correctness against `docs/verifier_taxonomy.md`:** No
  judge-dependent claim is mislabeled deterministic — this family declares no rater/judge
  leaf at all, and all 4 leaves are legitimately `evaluation_class="deterministic"` given
  a complete scripted trajectory (`measurement.py:41-54`). Leaf 1/2 correctly use
  `verifier_family="comparative"`/`reference_kind="baseline_delta"` with the opponent
  panel folded into `source_sha256` (`measurement.py:153-163`, tested at
  `tests/test_alympics_wac_measurement.py:152-164`) — matches taxonomy §6's "opponent
  population … is part of the estimand." Leaf 4 (`settlement_exactness`) is honestly
  framed as a **shadow recompute of the same code**, not an independent oracle
  (`measurement.py:504-517`); the independent-oracle cross-check is correctly pushed to
  `parity.py` instead, and a mutation test
  (`test_settlement_exactness_detects_a_corrupted_sealed_post_state`,
  `tests/test_alympics_wac_measurement.py:573-606`) proves leaf 4 is not a tautological
  no-op. No derived field is presented as independent confirmation of itself.
- **Replay honesty:** Genuine — `replay.py`'s `replay_episode` reruns the recorded bids
  through the real `AlympicsWacPlugin`/`run_episode` scheduler path (not a log re-read),
  and the module is explicit about the one real limit: replay alone has no independent
  oracle to catch a tampered bid, only `compare_episode_results` against the original run
  does (`replay.py:46-58`, proven by
  `test_replay_detects_a_tampered_bid_only_via_comparison_against_the_original`,
  `tests/test_alympics_wac_replay.py:296-327`). This is a good-faith disclosure, not an
  overclaim.
- **Gate‑1 corpus admission:** Digests are computed by the shared kernel resolver
  (`case_content_sha256`), the supply schedule is generated once from an explicit,
  AERead-owned `numpy.random.RandomState(seed)` (never upstream's own unseeded global
  state) and frozen into the payload, `build_all_cases()` rejects duplicate `case_id`s,
  and the disjoint-seed pairing (`mixed_policies_a` vs `_seed2`) was independently
  verified to actually produce different supply schedules (`[15, 18, 19, …]` vs
  `[18, 19, 13, …]`). No silent resampling: re-running the importer reproduces the
  checked-in JSON byte-for-byte (verified directly in this review, not just asserted by
  `test_importer_is_byte_identical_across_two_runs`).

---

## MINOR / SUGGESTION

### N1 — `cases.py:285` embeds the shared, mutable `PERSONAS` dict by reference into every case payload
`build_case()`'s `data["payload"]["personas"] = PERSONAS` aliases the same module-level
`Mapping[str, Mapping[str, Any]]` object into all 7 generated case dicts rather than a
defensive copy. Currently harmless (nothing mutates a case payload's `personas` key
in place before serialization/consumption — `_plain()` deep-copies on every read), but
it is a fragile pattern: a future code path that mutates `family_case["personas"]` in
place (instead of copying first) would silently corrupt every other case sharing the
same object, including ones already loaded in a long-lived process. No test currently
exercises this risk.

### N2 — No programmatic near-duplicate detection across the 7 grid cells
`build_all_cases()` (`cases.py:319-327`) only rejects an exact duplicate `case_id`; Gate
1's text (quoted in the spec, §1) also calls for rejecting "duplicates/near-duplicates."
Today's 7 cells are manually verified distinct (confirmed in this review), but there is
no automated check that two cells couldn't accidentally share an identical
`(supply_regime, rounds, seed, policy_assignment)` tuple under different names — reliance
is on manual review of a small, hand-authored table only.

### N3 — Spec §3's bid-legality-gate wording is looser than §2's and than the implementation
`docs/alympics_adapter_spec.md:88` says the gate is "checked before `run_single_round` is
invoked for that round, never after." The actual check
(`environment.py:280-296`, inside `_check_winner_wrapper`) runs **during** the call to
`run_single_round` (before the real, delegated `_check_winner` executes), which matches
§2's more precise "adapter checks this before delegating to `_check_winner`"
(`docs/alympics_adapter_spec.md:63`) but not §3's literal wording. Functionally correct
either way (verified by tracing the call order against upstream's own
`run_single_round`), but worth tightening the spec text so §2 and §3 don't read as two
different claims about when the gate runs.

---

## Files read for this review
- `docs/alympics_adapter_spec.md`, `docs/alympics_adapter_status.md`, `docs/verifier_taxonomy.md`
- `src/aeread_families/alympics_wac/{__init__.py,cases.py,environment.py,measurement.py,harness.py,parity.py,replay.py}`
- `tests/test_alympics_wac_{cases,environment,harness,measurement,parity,replay}.py`
- `cases/alympics_wac/base/*.json`
- `upstream-alympics/src/waterAllocation.py` (external pinned checkout, read directly to confirm M2 and the "protected state" question)
