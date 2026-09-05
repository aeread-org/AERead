# Codex adversarial review — econevals adapter

Second-reviewer pass (cross-model, read-only). Recovered from the build run's
transcript: the reviewer's sandbox permitted reads only, so it could not write
this file itself and reported its findings in its returned text instead.

Declared finding count: **0**.

---

The sandbox rejected the sole authorized write, and verification confirms [docs/econevals_review_codex.md](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/econevals/docs/econevals_review_codex.md) was not created. The worktree remains unchanged. Nine prepared findings follow.

## The procurement leaf is not the upstream benchmark score

- **Severity:** critical
- **File:line:** `src/aeread_families/econevals/measurement.py:448-453`, `src/aeread_families/econevals/measurement.py:591-601`, upstream `experiments/procurement/compute_scores.ipynb:121-143`
- **Concrete failure scenario:** Upstream scores maximum feasible utility across all attempts divided by optimum utility. AERead publishes only the last attempt's raw utility. If period 50 is optimal and period 100 has zero utility, upstream reports `1.0`; AERead reports `0.0 workers_supported`.
- **Suggested fix direction:** Publish the upstream-compatible `max(feasible utility) / opt_utility`; retain final native utility only as a separately named metric.

## The pricing leaf discards 49 of the 50 scored rounds

- **Severity:** critical
- **File:line:** `src/aeread_families/econevals/measurement.py:526-530`, `src/aeread_families/econevals/measurement.py:591-601`, `docs/econevals_adapter_spec.md:200-202`, upstream `experiments/pricing/compute_scores.ipynb:177-189`
- **Concrete failure scenario:** Upstream sums realized and monopoly profits over rounds 50–99 and reports their ratio. AERead reports only period 99's raw profit. An agent optimal in rounds 50–98 but earning zero in round 99 scores about `49/50` upstream and zero in AERead.
- **Suggested fix direction:** Score the complete 50-round window and publish the upstream profit ratio.

## Scheduling publishes blocking-pair count instead of the benchmark score

- **Severity:** high
- **File:line:** `src/aeread_families/econevals/measurement.py:477-483`, `cases/econevals/pins.json:35-38`, upstream `experiments/scheduling/compute_scores.ipynb:101-130`
- **Concrete failure scenario:** Upstream reports `1 - final_blocking_pairs / baseline_blocking_pairs`; AERead reports raw blocking pairs and carries no baseline. With baseline 20 and five blocking pairs, upstream reports `0.75`; AERead reports `5`.
- **Suggested fix direction:** Import and pin each seed's upstream baseline and implement the normalized score, explicitly choosing the upstream floored or unfloored variant.

## "Offline replay" requires and executes the live bridge

- **Severity:** high
- **File:line:** `src/aeread_families/econevals/replay.py:212-237`, `src/aeread_families/econevals/environment.py:477-496`, `src/aeread_families/econevals/environment.py:558-561`, `tests/test_econevals_replay.py:245-272`, `docs/econevals_adapter_spec.md:186`
- **Concrete failure scenario:** Replay feeds recorded responses through `run_episode`; `step()` re-executes submissions through the bridge. A machine possessing the sealed record but lacking the bridge environment cannot replay it. The test conceals this by constructing a second live bridge.
- **Suggested fix direction:** Replay sealed invocation results without bridge execution, using a bridge/provider that raises if touched.

## Corpus generation does not enforce the claimed upstream pin

- **Severity:** high
- **File:line:** `src/aeread_families/econevals/cases.py:235-253`, `src/aeread_families/econevals/cases.py:593-603`, `src/aeread_families/econevals/econevals_bridge.py:106-117`, `tools/econevals_bridge/provision.sh:61-68`
- **Concrete failure scenario:** `verify_module_sha256()` exists but `run_import()` never calls it. Provisioning accepts any checkout containing `econ_evals`. A newer checkout can therefore generate cases that are labeled with the old commit and hashes.
- **Suggested fix direction:** Verify the bridge checkout's commit and module hashes before every import/admission run and seal that verified identity with results.

## `write_notes` mutates state while declared read-only

- **Severity:** high
- **File:line:** `src/aeread_families/econevals/environment.py:587-592`, `src/aeread_families/econevals/tools.py:96-104`, `src/aeread_families/econevals/tools.py:170-192`, `tests/test_econevals_tools.py:72-88`
- **Concrete failure scenario:** `write_notes` changes `state["notes"]`, but its read-only binding receives no state reader. Sealed evidence records no before/after mutation even though later `read_notes` behavior changes.
- **Suggested fix direction:** Declare it mutating and record hashes for the notes state.

## Fidelity tests silently skip in CI

- **Severity:** medium
- **File:line:** `tests/test_econevals_cases.py:40-52`, `tests/test_econevals_measurement.py:44-56`, `tests/test_econevals_replay.py:50-62`, `conftest.py:55-63`, `.github/workflows/ci.yml:19-22`
- **Concrete failure scenario:** Bridge-backed tests skip when the macOS-local bridge path is absent. CI neither provisions it nor sets `AEREAD_ECONEVALS_BRIDGE_REQUIRED`, so CI can be green while corpus parity, scoring parity, E2E, and replay checks never execute.
- **Suggested fix direction:** Add a required fidelity job that provisions the pinned bridge, sets the required flag, and permits zero relevant skips.

## The five goldens bypass the environment boundary

- **Severity:** medium
- **File:line:** `tests/test_econevals_measurement.py:11-19`, `tests/test_econevals_measurement.py:142-160`, `tests/test_econevals_measurement.py:171-207`, `tests/test_econevals_measurement.py:219-249`, `tests/test_econevals_measurement.py:279-293`
- **Concrete failure scenario:** Tests hand-build the scorer's internal attempt dictionaries. Golden 1 copies both prices and profits from `gold_optimum`. If `_submit_pricing()` uses the wrong period or corrupts the attempt, these goldens still pass because they never exercise it.
- **Suggested fix direction:** Use independently authored trajectories and expected results, run through tool bindings, scheduler, terminal state, and final scoring.

## Non-finite numeric submissions can become infrastructure crashes

- **Severity:** medium
- **File:line:** `src/aeread_families/econevals/environment.py:687-703`, `src/aeread_families/econevals/environment.py:802-821`, `src/aeread_families/econevals/measurement.py:519-529`
- **Concrete failure scenario:** `{"Product_1": 1e309}` parses to infinity, passes type/key and non-negativity checks, then produces non-finite profit that can fail `MetricValue` construction. Procurement reaches `int(inf)` and raises `OverflowError`.
- **Suggested fix direction:** Reject non-finite values and require non-negative integral procurement quantities without lossy coercion.

Prepared findings: 9. Findings sections written to the requested file: 0.

FINDINGS: 0
