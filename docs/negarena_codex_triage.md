This document is the triage of docs/negarena_review_codex.md.
Its author could not write files directly, so this triage was saved on its behalf.

## Finding 1: Production scorer is not callable

**Classification:** CONFIRMED

**Location:** `src/aeread/shared_runner/family_evaluation.py:245`; `src/aeread_families/negarena/environment.py:460`; `src/aeread_families/negarena/measurement.py:418`; `tests/test_negarena_harness.py:188`

**Evidence:** `finalize_family_execution()` immediately calls the value returned by `plugin.build_scorer(family_case)`. Negarena returns a `NegarenaScorer`, which exposes only `score_seat_outcome()` and `score_agreement_reached()` and defines no `__call__`. A read-only runtime probe confirmed `callable(scorer) == False` and reproduced `TypeError: 'NegarenaScorer' object is not callable`. The family tests bypass this interface by invoking the two custom methods directly.

Concrete failure scenario: any successfully completed negarena `CellExecution` passed to production finalization reaches line 245 and raises `TypeError`, before `score_recorded`, evidence sealing, or receipt creation.

## Finding 2: Replay record is not bound to its execution inputs

**Classification:** CONFIRMED

**Location:** `src/aeread_families/negarena/replay.py:116`; `src/aeread_families/negarena/replay.py:123`; `src/aeread_families/negarena/replay.py:209`; `src/aeread_families/negarena/replay.py:225`

**Evidence:** `RecordedEpisode` serializes exactly two fields: `case_id` and `decisions`. It contains no case hash, cell ID/hash, profile or pairing identity, seeds, implementation references, or upstream pin. `replay_episode()` validates only that `recorded.case_id == case.case_id` before replaying against the caller-supplied cell, case, and plugin. The scheduler validates that the supplied cell and case agree with each other, but it has no recorded original identity against which to compare them.

Concrete failure scenario: record decisions from case version A, then provide a valid case version B with the same `case_id` but changed valuation, upstream pin, seed, or pairing and a newly matching `PlanCell`. Replay accepts the record and produces version-B state and scores without reporting that it is no longer replaying the original execution.

## Finding 3: Family harness seals an incomplete evidence lifecycle

**Classification:** CONFIRMED

**Location:** `src/aeread_families/negarena/harness.py:72`; `src/aeread_families/negarena/harness.py:85`; `tests/test_negarena_harness.py:188`; `tests/test_negarena_harness.py:211`; `tests/test_negarena_harness.py:272`

**Evidence:** `ScriptedNegarenaHarness` appends only `negarena_decision_served` events. It implements none of the scheduler lifecycle callbacks that would record phase boundaries, transitions, terminal state, or outcome. The tests then call the scorer methods directly, with the default empty `evidence_refs`, and seal the existing store. They explicitly assert that the sealed event count equals only the logical-action count.

The shared finalizer would append `score_recorded` before sealing at `src/aeread/shared_runner/family_evaluation.py:249-258`, but these family tests never call it, and Finding 1 currently prevents negarena from reaching it in production.

Concrete failure scenario: an accepted negotiation produces RED/BLUE settlement values, but the resulting family-test seal contains only served responses. An auditor can verify that incomplete log's integrity while having no sealed transition, settlement result, score, or evidence reference proving how the reported values were derived.

## Finding 4: An unperformed comparison is reported as a match

**Classification:** CONFIRMED

**Location:** `src/aeread_families/negarena/replay.py:391`; `src/aeread_families/negarena/replay.py:401`; `src/aeread_families/negarena/replay.py:428`; `tests/test_negarena_harness.py:378`; `tests/test_negarena_harness.py:390`

**Evidence:** When no original result is supplied, `replay_and_verify()` sets `comparison=None`. Nevertheless, `ReplayReport.status` returns `"mismatch"` only for an explicit nonmatching comparison and returns `"match"` for every other state, including `None`. A runtime probe reproduced `ReplayReport(..., comparison=None).status == "match"`. The test explicitly asserts this behavior even though its comment calls the state "not comparable."

Concrete failure scenario: an offline replay has no original result to compare against. No equality check occurs, but downstream code reading only `status` receives `"match"` and may count the episode as replay-verified.

## Finding 5: Provisioning uses the wrong default upstream path

**Classification:** CONFIRMED

**Location:** `tools/negarena_bridge/provision.sh:26`; `tools/negarena_bridge/provision.sh:68`; `tools/negarena_bridge/provision.sh:69`; `tools/negarena_bridge/provision.sh:95`

**Evidence:** From `tools/negarena_bridge`, `../../../..` resolves to `/Users/sunzeyu/Documents/econ benchmark/AERead`, so the default becomes `/Users/sunzeyu/Documents/econ benchmark/AERead/upstream-negarena`. The repository's tests use the actual sibling checkout `/Users/sunzeyu/Documents/econ benchmark/upstream-negarena`. When the incorrect default does not exist, the script prints a note but does not fail; it skips the import probe and continues to print the export instruction. Thus the skip is announced, but it is non-failing rather than a successful verification.

Concrete failure scenario: an operator runs `provision.sh` without setting `AEREAD_NEGARENA_UPSTREAM_ROOT` while the checkout exists at the documented sibling location. The script exits successfully and presents the venv for use even though it never verified that the pinned upstream game classes import.

COUNTS: confirmed=5 refuted=0 kernel=0
