# steer adapter — status

Branch `zeyu/steer-adapter`. Last verified 2026-09-02.

## What the adapter claims

For each of the 8 declared pilot elements of `narunraman/STEER` (pinned at
`d66673c8277b9112fc5e39751524ccda6d852446`, no license), the adapter reproduces
one deterministic multiple-choice answer-key judgment per admitted question,
end to end through the real kernel scheduler: observe the question and every
option (full observability) → submit exactly one `option_id` → score by exact
index equality against the gold answer recovered from upstream's own
`Answers` frame. One measurement leaf per case, identical shape for all 8
elements:

| Leaf | Verifier family | Evaluation class | Declared when |
|---|---|---|---|
| `steer_answer_key` | `canonical_reference` | `deterministic` | always |

There is no second, judge-dependent leaf: STEER's MCQA answer key is a
deterministic equality check end to end, and the pinned commit itself deleted
its own evaluation submodule (`git show d66673c --stat`: "Remove STEER
evaluation submodule") — there is no upstream scorer to delegate to or achieve
parity against, unlike `tau3_retail`.

Milestone 3 (this session) adds:

- **`ScriptedSteerHarness`** (`src/aeread_families/steer/harness.py`) — a
  provider-free response source, driving episodes through the real
  `run_episode` scheduler (not a hand-wired shortcut), that records each
  served decision as a durable `EvidenceStore` event and can be sealed
  (`EvidenceSeal`) at the end of a run.
- **`replay.py`** (`src/aeread_families/steer/replay.py`) — an offline
  replayer: given a recorded, plain-JSON trajectory, re-run it through
  `run_episode` with zero provider calls and reproduce the final state and
  score.
- Two new test modules exercising both: `tests/test_steer_e2e.py` (harness +
  sealed evidence) and `tests/test_steer_replay.py` (offline replay).

## Evidence

**Family test suite: 138 passed, 0 failed** across all 6 `test_steer_*.py`
modules (`test_steer_cases.py` 60, `test_steer_environment.py` 35,
`test_steer_measurement.py` 12, `test_steer_goldens.py` 7,
`test_steer_e2e.py` 12, `test_steer_replay.py` 12), plus **10 passed** in
`tests/test_shared_runner_smoke.py` (the generic R1–R4 kernel smoke path,
untouched by this family) — **148 passed, 0 failed total**, run twice
independently with identical results.

```bash
PYTHONPATH=src python -m pytest \
  tests/test_steer_cases.py tests/test_steer_environment.py \
  tests/test_steer_measurement.py tests/test_steer_goldens.py \
  tests/test_steer_e2e.py tests/test_steer_replay.py \
  tests/test_shared_runner_smoke.py -q
```

**Narrowed claim (finding 5 follow-up, docs/steer_fix_verification.md):**
the run above did not set `AEREAD_STEER_FIXTURES_REQUIRED=1`, so on its own
it cannot prove none of the six `test_steer_*.py` modules silently skipped
for want of the flattened cache -- only that whatever ran, passed. The
opt-in guard that turns such a skip into a failure (root `conftest.py`,
`tools/steer_bridge/README.md`) is itself regression-tested both ways
(`tests/test_steer_fixtures_required.py`), and re-running the command above
with that variable set reports the identical pass count with zero skips
(see `docs/steer_review_disposition.md`'s "Verification follow-up" section
for the exact re-run). What remains explicitly out of scope for this
adapter: the variable is not set by `.github/workflows/ci.yml`'s generic
`test` job, and should not be, without also automatically fetching the
no-license upstream corpus over the network on every push -- a design
choice this family deliberately avoids elsewhere (`steer_bridge_driver.py`'s
`fetch` op is never invoked automatically). Any run meant to certify
fidelity must set `AEREAD_STEER_FIXTURES_REQUIRED=1` itself; nothing in
this repo's CI does that for steer today.

The whole-repo test collection (896 tests across every family) succeeds with
no import errors after these changes; a full-repo execution was not run to
completion tonight because of unrelated CPU contention from concurrent
sibling adapter work on the same machine, not because of anything this
family's tests do — the scoped run above is the one this milestone asks for
and is unaffected by that contention.

**Eight full episodes through the real harness/scheduler path**
(`test_steer_e2e.py`'s parametrized sweep over all 8 declared elements),
each one recording exactly one sealed evidence event and re-verified via
`EvidenceStore.verify_seal()`. Two more harness-driven episodes cover an
illegal (out-of-range `option_id`) and a malformed (free-text) submission,
proving evidence is sealed for a rejected submission too, not just a passing
one.

**Offline replay reproduces state and score byte-identically**, for real,
not just approximately: `test_steer_replay.py` records a live,
harness-driven episode for each of goldens 1–4 (successful,
valid-but-poor, invalid-unauthorized, malformed-operational), round-trips
the record through plain JSON text, replays it with a *second, independent*
`SteerPlugin` instance and zero provider calls, and asserts

```python
canonical_json_bytes(original.final_state) == canonical_json_bytes(replayed.final_state)
```

holds exactly — not just that the two runs' *content* agrees modulo some
known non-determinism. This is stronger than `tau3_retail`'s own replay
guarantee: `Tau3RetailPlugin.step()` re-timestamps every message it appends
through upstream's `ParticipantMessageBase(default_factory=get_now())`, so
tau3.retail's raw state never matches itself bit-for-bit across two runs of
one trajectory (only its *content* does — see
`tau3_retail.replay._strip_message_timestamps`'s docstring). `SteerPlugin`'s
state (`question_text`/`options`/`termination`/`selected_option_id`/
`failure_code`) carries nothing wall-clock-derived, so the raw claim holds
without qualification here.

**Mutation tested.** Two deliberate defects were injected and reverted
(never committed):

1. `StateComparison.matches` hard-coded to always return `True` — caught
   immediately: `test_compare_episode_results_reports_specific_mismatches_not_one_boolean`
   and `test_replay_of_a_tampered_record_diverges_and_is_caught_by_comparison`
   both failed as expected (`assert True is False`), proving those paths have
   real coverage rather than a vacuously-green comparator.
2. `ScriptedSteerHarness.__call__`'s evidence-recording call deleted —
   caught immediately: all 10 tests asserting `seal.event_count == 1` failed
   (`assert 0 == 1`), proving the sealed-evidence claim is actually checked,
   not merely asserted-and-never-exercised.

Both mutations were reverted; the suite returned to 148/148 green
afterward.

**Deterministic across runs.** `test_steer_e2e.py` + `test_steer_replay.py`
were executed twice, independently, both times 24/24 passed with no
differences in behavior.

**Corpus/Gate-1 status is unchanged from milestones 1–2** (not re-verified
tonight beyond re-running its existing test file): 1,595 admitted cases
(200 × 7 elements + `ir_mechanism`'s full 195), 32/32 pinned file hashes
matched against the upstream git-lfs `oid`, schema-drift-safe `Answers`
column probing (`correct` vs `correct_answer`), and the five QC Gate-2
goldens. See `docs/steer_adapter_spec.md` sections 1–4 for the governing
detail and `tests/test_steer_cases.py`/`tests/test_steer_goldens.py` for the
tests.

## Known limits, stated rather than implied

- **A genuinely offline replay (no `original` episode in memory) cannot
  detect that its own record was tampered with.** Unlike
  `tau3_retail.replay` (whose `Tau3RetailPlugin.step()` independently
  re-executes and cross-checks every recorded tool call against the pinned
  upstream bridge, so a tampered tool result raises
  `SchedulerContractError` from inside `replay_episode` itself), Mode A has
  no tool call and no independent upstream computation to re-verify a
  submitted answer against — only the row's own gold answer, which a
  tampered record cannot see either way. `replay_episode` alone will happily
  reproduce a *self-consistent* replay of a tampered record; the only thing
  that catches the tamper is `compare_episode_results` against a genuine
  `original` supplied by the caller (see
  `test_replay_of_a_tampered_record_diverges_and_is_caught_by_comparison`).
  A caller replaying from a written record with no original run in memory —
  the "genuinely offline" case the record format is meant to support — gets
  no independent tamper detection at all.
- **`ScriptedSteerHarness` has no tool loop to drive**, unlike
  `ScriptedTau3RetailHarness`. This is a direct, correct consequence of Mode A
  (spec section 1: "no environment, no tools, no counterpart seat, no phase
  graph"), not a scoped-down placeholder — there is nothing further to add
  here as the corpus/element count grows.
- **Sealed evidence records the submitted answer and observation shape, not
  a provider call.** Because the harness itself is the only thing that ever
  "answers" in these tests (scripted, not a live model), the evidence trail
  documents what was served and submitted, not an independent model-call
  record the way `ToolInvocationRecord` documents tau3.retail's tool calls
  against upstream's own bridge.
- **The e2e sweep uses each element's first admitted row only**, not a
  sample across the full 1,595-case pilot corpus — sufficient to prove the
  harness/scheduler/scorer wiring holds for every declared element, not a
  claim that every admitted case has been individually run through it.
- All limits already stated in `docs/steer_adapter_spec.md` section 6
  (8/48 elements, head-N not stratified, manual branch assignment, no
  `canonical_set` variant for `dsic_mechanism`'s 5 genuinely multi-correct
  questions, no cross-part consistency check, no upstream scoring parity
  claim) are unchanged by this milestone and still apply.

## Open item

`docs/benchmark_qc.md`, referenced by this task's own brief as the source for
"Gates 1–2" conventions, does not exist anywhere in this repo (also logged in
`ledger_entries/steer.md` from an earlier milestone). This adapter's Gate-1/
Gate-2 vocabulary was reconstructed from `docs/steer_adapter_spec.md` itself,
consistent with milestones 1–2, not from that missing canonical source.
