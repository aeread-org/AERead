This is the triage of docs/govsim_review_codex.md.
Its author could not write files directly, so this triage was saved on its behalf.

## Finding 1: Production scorer is not callable

**Classification:** CONFIRMED

**Location:** `src/aeread_families/govsim/measurement.py:719`; `src/aeread/shared_runner/family_evaluation.py:245`

**Evidence:** `GovsimScorer` defines named methods such as `score_no_collapse()` and `score_all()`, but no `__call__`. The production finalizer executes `plugin.build_scorer(family_case)(recorded_outcome, ...)`, directly calling the returned object. A read-only probe confirmed `callable(build_scorer(...)) == False`. Existing tests bypass this seam by invoking methods directly at `tests/test_govsim_measurement.py:400-405`.

Concrete failure: any completed govsim episode reaches finalization, the runner calls the `GovsimScorer` instance, and Python raises `TypeError: 'GovsimScorer' object is not callable` before recording a score or issuing a receipt.

## Finding 2: Replay reports match without comparing an original

**Classification:** CONFIRMED

**Location:** `src/aeread_families/govsim/replay.py:378-382`; `src/aeread_families/govsim/replay.py:395-408`

**Evidence:** `replay_and_verify()` permits `original=None` and consequently sets `comparison=None`. `ReplayReport.status` returns `"mismatch"` only when a non-`None` comparison exists and fails; every other case returns `"match"`. The docstring calls `None` "not comparable," but the public status contradicts that distinction.

Concrete failure: load a recorded episode offline, call `replay_and_verify()` without the original `EpisodeResult`, and receive `status == "match"` even though no terminal state, outcome, phase hashes, or final state was compared with the original execution.

## Finding 3: All upstream step exceptions become operational failures

**Classification:** CONFIRMED

**Location:** `src/aeread_families/govsim/govsim_bridge_driver.py:247-257`; `src/aeread_families/govsim/govsim_bridge.py:227-236`; `src/aeread_families/govsim/environment.py:478-500`

**Evidence:** The bridge driver catches `Exception` around every upstream `env.step()` and returns a response containing `failed_action_index`. `GovsimBridge.run_actions()` maps every such response to `GovsimActionError`, irrespective of exception type. `GovsimPlugin.step()` then catches every `GovsimActionError` and returns a normal `operational_failure` transition. Nothing restricts this downgrade to the intended malformed-action assertion.

Concrete failure: an adapter incompatibility causes upstream `step()` to raise `KeyError`, `AttributeError`, or another programming error for a valid action. The run terminates as an expected operational failure with an invalid measurement instead of surfacing the implementation defect as an infrastructure failure.

## Finding 4: Recorded source and dependency pins are not enforced

**Classification:** CONFIRMED

**Location:** `cases/govsim/v1/pins.json:2-21`; `src/aeread_families/govsim/cases.py:147-165`; `src/aeread_families/govsim/environment.py:196-206`; `src/aeread_families/govsim/environment.py:256-280`; `src/aeread_families/govsim/environment.py:286-295`

**Evidence:** `pins.json` records source hashes and exact Python, NumPy, pandas, OmegaConf, and PettingZoo versions. Runtime validation checks only the repository/commit values in the case payload and whether the upstream checkout is clean at that commit. It never loads `pins.json`, hashes the named source files, calls `bridge.runtime_info()`, or compares runtime dependencies with the recorded versions. `initial_state()` proceeds directly to `bridge.run_actions()`.

Concrete failure: execute the corpus with NumPy 2.x instead of the recorded 1.24.4, or with altered source bytes that remain in a checkout Git considers clean at the expected commit. The adapter accepts and executes the run while attributing results to dependency/source pins it never verified.

## Finding 5: Replay is self-consistency, not required upstream parity

**Classification:** CONFIRMED

**Location:** `docs/govsim_adapter_spec.md:218-229`; `tests/test_govsim_replay.py:461-487`

**Evidence:** The specification requires `tests/test_govsim_parity.py` with P2 adapter-versus-raw-`ConcurrentEnv` execution and an independently recomputed P3 regeneration/collapse check. That test file does not exist. The replay test produces the original through `GovsimPlugin`, produces the replay through another `GovsimPlugin`, and compares those two adapter executions. It therefore demonstrates deterministic self-consistency, not equivalence to an independent raw-upstream path.

Concrete failure: `GovsimPlugin.step()` consistently translates a kernel harvest into the wrong upstream action order. Both the live and replay executions use that same translation and match byte-for-byte, while the required direct raw-upstream trajectory would differ. The current tests still pass.

## Finding 6: `num_agents` is omitted from case identity

**Classification:** CONFIRMED

**Location:** `src/aeread_families/govsim/cases.py:176-188`; `src/aeread_families/govsim/cases.py:202-215`

**Evidence:** `num_agents` is explicitly configurable and changes seats, environment configuration, action budget, payload, and content hash. Nevertheless, `case_id` contains only scenario, policy short name, and world seed. A read-only probe produced equal case IDs but unequal content hashes for otherwise identical one-agent and five-agent cases.

Concrete failure: generating `fishing/sustainable_v1/seed=0` first with five agents and then with one agent produces two semantically different manifests named `govsim.fishing.sustainable.0`. A case-indexed mapping or output file overwrites or rejects one of them as a duplicate.

## Finding 7: Module-level skip suppresses bridge-independent tests

**Classification:** CONFIRMED

**Location:** `tests/test_govsim_replay.py:74-92`; `tests/test_govsim_replay.py:362-384`

**Evidence:** Import-time `_upstream_root()` calls `pytest.skip(..., allow_module_level=True)` when the upstream marker is absent, before pytest can collect anything in the module. The same module later contains explicitly bridge-independent tests for JSON round-tripping, recorded-response ordering, mismatch reporting, and harness behavior.

Concrete failure: in CI without the upstream checkout, a regression breaks `RecordedEpisode.from_json()` or `RecordedResponseSource` ordering. Instead of running and failing the pure test at lines 367 onward, pytest skips the entire module, hiding the regression.

COUNTS: confirmed=7 refuted=0 kernel=0
