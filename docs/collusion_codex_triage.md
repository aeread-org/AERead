This is the triage of docs/collusion_review_codex.md.
Its author (Codex) could not write files directly, so this triage was saved on its behalf.

## Finding 1: Retry exhaustion occurs outside the family hook

**Classification**: KERNEL

**Location**: `src/aeread/shared_runner/scheduler.py:516`; `src/aeread_families/collusion/environment.py:445`; `docs/collusion_adapter_spec.md:279`

**Evidence**: The family environment deliberately treats any parse failure reaching `step()` as already retry-exhausted. Its contract says retries belong upstream in the harness/response source. The shared scheduler, however, calls `response_source(request)` exactly once and immediately parses that single response at line 525; it contains no ten-attempt loop. Thus a first malformed response followed by a potentially valid second response cannot occur through this runner path. The missing retry orchestration belongs to the shared runner/harness layer, not the collusion family.

## Finding 2: Profit baseline uses the wrong opponent condition

**Classification**: CONFIRMED

**Location**: `src/aeread_families/collusion/measurement.py:103`; `src/aeread_families/collusion/measurement.py:577`; `src/aeread_families/collusion/measurement.py:621`; `tests/test_collusion_replay.py:377`

**Evidence**: The family contract requires the baseline policy to run under the same opponent condition, but the named baseline is documented as both firms playing Nash. The scorer subtracts whatever bare `baseline_profit_by_seat` mapping the caller supplies and cannot verify its provenance. The asymmetric replay test supplies `gold["pi_nash"]`, i.e. Nash-vs-Nash profit, even though the tested trajectory uses monopoly play against tit-for-tat. Concrete failure scenario: firm B is evaluated against firm A's persistent monopoly-price policy; B's correct baseline is B playing Nash against that same monopoly-price opponent. If that profit differs from Nash-vs-Nash `pi_nash`, line 621 subtracts the latter and publishes an incorrect delta. Existing tests validate internal score/replay equality, not the required same-opponent counterfactual.

## Finding 3: Unverified offline replay reports `match`

**Classification**: CONFIRMED

**Location**: `src/aeread_families/collusion/replay.py:100`; `src/aeread_families/collusion/replay.py:349`; `src/aeread_families/collusion/replay.py:375`; `tests/test_collusion_replay.py:265`

**Evidence**: `RecordedEpisode` stores only a case ID and decisions—no expected trajectory digest or seal. With `original=None`, `replay_and_verify()` sets `comparison=None`. `ReplayReport.status` returns `"mismatch"` only when a non-null comparison fails; otherwise it returns `"match"`. The cited test explicitly asserts `comparison is None` and `status == "match"`. Concrete failure scenario: edit one stored price, load the recording without the original episode, and replay it. The altered trajectory receives a newly calculated output digest but is never compared with an expected digest, so the report still says `"match"`.

## Finding 4: Replay identity is bound only to case ID

**Classification**: CONFIRMED

**Location**: `src/aeread_families/collusion/replay.py:100`; `src/aeread_families/collusion/replay.py:207`

**Evidence**: The serialized recording contains `case_id` and `decisions` only. `replay_episode()` rejects a recording only when `recorded.case_id != case.case_id`; it checks neither the case content digest nor the run-cell identity. Concrete failure scenario: retain a case ID, change demand parameters, recompute a valid manifest digest, and replay the old decisions using a compatible cell. The case-ID check passes, while the same prices produce different quantities, profits, references, and scores under the changed economics.

## Finding 5: Distance leaves discard per-round gaps

**Classification**: CONFIRMED

**Location**: `docs/collusion_adapter_spec.md:138`; `src/aeread_families/collusion/measurement.py:503`; `src/aeread_families/collusion/measurement.py:524`

**Evidence**: The family specification says the result includes the raw per-round gap. The scorer instead averages absolute gaps over all admitted rounds for each seat, then averages those seat means into the primary value. Its metrics contain only convergence booleans; no per-round gap sequence is retained. Concrete failure scenario: let `d = p_monopoly - p_nash`. A trajectory spending half its rounds at `p_nash` and half at `p_monopoly` receives primary Nash distance `d/2`, exactly like a trajectory priced constantly at their midpoint. The materially different dynamics are indistinguishable in the published primary distance.

## Finding 6: Scientific notation parsing has been corrected

**Classification**: REFUTED

**Location**: `src/aeread_families/collusion/environment.py:67`; `src/aeread_families/collusion/environment.py:145`; `tests/test_collusion_environment.py:313`

**Evidence**: The current numeric regex includes an optional exponent component, `(?:[eE][-+]?\d+)?`. `_extract_price_from_text()` therefore captures `1e0` or `1.92e+00` as one token and converts it with `float()`, producing `1.0` or `1.92`, respectively. The regression test exercises `1.92e+00` and asserts the resulting price is `1.92`. The claimed truncation to the exponent's trailing number no longer occurs.

COUNTS: confirmed=4 refuted=1 kernel=1
