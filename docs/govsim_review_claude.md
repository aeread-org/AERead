# govsim adapter — independent review (second reviewer, Claude)

Scope: `git diff origin/main...zeyu/govsim-adapter` (33 files, ~6950 lines added),
read against `docs/govsim_adapter_spec.md`, `docs/verifier_taxonomy.md`,
`docs/problem_bound_case_audit.md`. Reviewed read-only; no files under review were
modified.

**Method note (goes beyond static reading):** the claims in
`docs/govsim_adapter_status.md` were independently re-verified, not just trusted.
I provisioned a fresh bridge venv (`tools/govsim_bridge/provision.sh`,
numpy 1.24.4/pandas 2.0.3/omegaconf 2.3.0/pettingzoo 1.24.2, Python 3.11.3 — the
exact versions `pins.json` records) against the real pinned upstream checkout at
`/Users/sunzeyu/Documents/econ benchmark/upstream-govsim` and ran the full family
suite (`test_govsim_cases.py`, `test_govsim_environment.py`,
`test_govsim_measurement.py`, `test_govsim_replay.py`,
`test_shared_runner_smoke.py`):

- Without the bridge: **80 passed, 18 skipped**, every skip reason naming
  `$AEREAD_GOVSIM_BRIDGE_PYTHON` and `tools/govsim_bridge/provision.sh` (no
  generic/silent skip) — matches the status doc exactly.
- With the bridge: **98 passed, 0 failed** in **146.63s** — matches the status
  doc's "98 passed... ~146s" almost exactly. This is real, not fabricated: the
  five QC Gate-2 goldens, both full-episode replays, and the gini parity check
  all genuinely ran against the actual upstream checkout.

This corroborates the adapter's central claims. The findings below are gaps and
risks found on top of that, not a reason to distrust the headline numbers.

## CRITICAL

None found. No unhandled crash, resource leak, silently-corrupted state, or
falsified verifier claim was located.

## WARNING

### W1 — Two of the three wrapped scenarios (`sheep`, `pollution`) have zero live-bridge test coverage; only `fishing` is ever driven for real

- `src/aeread_families/govsim/cases.py:71` declares `SCENARIOS = ("fishing", "sheep", "pollution")` and the committed corpus (`cases/govsim/v1/`) contains 3 files per scenario (9 total, `cases/govsim/v1/corpus_manifest.json`).
- Every QC Gate-2 golden that uses the **real** bridge
  (`tests/test_govsim_measurement.py:382-560`, functions
  `test_golden_successful_*`, `test_golden_valid_but_poor_*`,
  `test_golden_invalid_unauthorized_*`, `test_golden_malformed_operational_*`,
  `test_golden_degenerate_reference_*`) and every real, scheduler-driven episode
  (`tests/test_govsim_replay.py:230-239`'s `live_sustainable`/`live_greedy`
  fixtures, `_run_live` at line 199) hard-codes `"fishing"` — grep for
  `"sheep"`/`"pollution"` across `test_govsim_measurement.py`,
  `test_govsim_replay.py`, `test_govsim_environment.py` returns **zero** hits.
- Failure scenario: a future change to `SheepConcurrentEnv`/`PollutionConcurrentEnv`'s
  own `env.py` (POOL_LOCATION override, a scenario-specific constant, an import
  path typo) — or a change to `_scenario_env_path`/`_SCENARIO_ENV_CLASSES` in
  `cases.py`/`govsim_bridge_driver.py` that only affects those two scenarios —
  could silently break `govsim.sheep.*`/`govsim.pollution.*` (6 of the 9
  committed cases) while the entire test suite stays green, because nothing in
  CI ever executes those code paths through the real upstream checkout.
- I manually smoke-tested this gap directly against the real bridge (both a
  bare harvest round and a full 12-round drive of `sustainable_v1`/`greedy_v1`
  for all three scenarios): `sheep`/`pollution` currently behave identically to
  `fishing` byte-for-byte (`collected_resource` matches exactly across
  scenarios for the same seed/policy), so this is a coverage gap, not a proven
  live defect today — but it is a real regression-protection hole for 2/3 of
  the wrapped scenarios that the "all three scenarios... arithmetic identical"
  claim (spec section 0) currently rests on manual recon plus my own ad hoc
  probe, not on anything in the committed suite.

### W2 — The "invalid-unauthorized" QC Gate-2 golden never drives the real scheduler; "no credit earned" is asserted in a comment but not literally checked

- `tests/test_govsim_measurement.py:455-479`
  (`test_golden_invalid_unauthorized_rejected_before_any_bridge_call_no_credit`)
  and its structural sibling `tests/test_govsim_environment.py:297-313`
  (`test_legal_rejects_a_seat_that_is_not_eligible_for_the_phase`) both call
  `plugin.legal(...)` **directly**, never through
  `aeread.shared_runner.scheduler.run_episode`. By contrast, the "successful"
  and "valid-but-poor" goldens (via `_drive_episode`,
  `test_govsim_measurement.py:113-149`) and the replay suite's two live episodes
  (`test_govsim_replay.py:199-227`) do go through the real phase loop.
- The measurement test's own comment (`test_govsim_measurement.py:477-478`:
  "No protected state changed and no credit earned: legal() never touches the
  bridge at all") asserts more than the test checks: the only assertion made is
  `counting_bridge.call_count == calls_after_reset` (line 479). Nothing asserts
  an `EvidenceStore` event was withheld or that `phase_action_counts` wasn't
  incremented — because the test never invokes the scheduler at all, there is
  nothing to make that assertion against.
- Failure scenario: this is a real, defensible proof that
  `GovsimPlugin.legal()` itself is side-effect-free (confirmed: `legal()`
  ignores its `action` argument entirely — `environment.py:416` `del action` —
  and `eligible_actors()` likewise ignores `state` — `environment.py:346`
  `del state` — so no mutation is architecturally possible regardless of the
  test). But it does **not** exercise what actually happens when the real
  kernel's `run_episode` receives an illegal action for a `reject`-policy phase
  (`scheduler.py:587-590`: it raises `SchedulerContractError`, aborting the
  whole episode) for this family specifically. That behavior is covered
  generically by `tests/test_shared_runner_scheduler.py`, not by a
  govsim-specific end-to-end golden, so a govsim-specific interaction bug in
  this path (e.g., if a future change made `DISCUSS_PHASE`'s `step()` start
  reading the `actions` mapping instead of ignoring it, per
  `environment.py:453-456`) would not be caught by this golden.

## SUGGESTION

### S1 — `family_manifest()`'s `measurement_kind` enum forces a "human_judged" label onto a fully deterministic, non-judge family

- `src/aeread_families/govsim/environment.py:141` declares
  `"measurement_kind": "comparative_or_human_judged"`. This is the only legal
  value close to "comparative" in
  `MeasurementDeclaration.from_dict`'s enum
  (`src/aeread/shared_runner/schemas.py:279-282`:
  `{"property_or_answer", "optimizable_outcome", "comparative_or_human_judged"}`)
  — there is no bare "comparative" bucket, so this is a pre-existing kernel
  schema limitation, not something introduced by this diff, and every one of
  the five leaves in `measurement.py` correctly declares
  `evaluation_class="deterministic"` with no rater/judge fields anywhere
  (confirmed: `docs/govsim_adapter_status.md` explicitly claims "all
  deterministic (no leaf in this family depends on a judge or a model call)",
  and I found no judge/rubric/LLM-call code path in `measurement.py`).
- Failure scenario: a downstream consumer that branches on the family-level
  `measurement_kind` field (rather than reading each leaf's own
  `verifier_family`/`evaluation_class`) to decide whether rater-provenance
  fields (rubric hash, rater identity, replicate count — per
  `docs/verifier_taxonomy.md` section 7) are required would incorrectly expect
  them for this family. Worth a one-line comment at the declaration site (there
  already is one, `environment.py:130-139`, but it doesn't call out the
  enum's imprecision) or a kernel-level enum split, tracked as a follow-up
  rather than blocking this PR.

### S2 — `govsim_survival_months`/`govsim_total_harvest` lack the same byte-for-byte upstream parity check that `govsim_equality_gini` has

- `measurement.py`'s module docstring (`measurement.py:74-83`) argues, by code
  inspection, that `terminal["num_round"]` is "exactly equal to" upstream's
  own `compute_survival_months_stats` rule (`plots.py:14-56`) — but unlike
  `govsim_equality_gini`, which has an actual runtime cross-check against
  upstream's real, unmodified function through the bridge
  (`GovsimBridge.call_upstream_gini`,
  `tests/test_govsim_measurement.py:568-611`'s
  `test_vendored_gini_matches_upstreams_own_gini_through_the_bridge*`), there is
  no equivalent empirical check for `survival_months`/`total_harvest` against
  upstream's own multi-run analysis code.
- This is already honestly disclosed as open follow-up work (spec section 5's
  P1–P3, `docs/govsim_adapter_status.md`'s "Known limits" section: "P1...P2...P3
  ...remain open follow-up work"), so this is not a hidden gap — flagging only
  because a subtle edge case in upstream's real rule (e.g., how a run that
  never collapses, or a tie at exactly the horizon, is handled by the
  paper's actual dataframe-based code) could silently diverge from the
  adapter's own single-episode reimplementation without any test noticing,
  the same class of risk the P4 gini check was specifically built to close for
  `equality_gini`.

## Not defects (checked and cleared)

- **Gate-1 corpus admission:** `case_content_sha256` is genuinely computed via
  the shared kernel resolver (`cases.py:245-253`, re-hashed and asserted stable
  after construction); `build_corpus()` raises on any duplicate `case_id`
  (`cases.py:263-264`); every case id passes `is_exportable_id` (no colon,
  confirmed by `tests/test_govsim_cases.py:102-109`); the importer is
  byte-identical across two independent runs
  (`test_importer_is_byte_identical_across_two_runs`, verified locally); the
  committed on-disk corpus matches a fresh generation
  (`test_committed_corpus_on_disk_matches_a_fresh_generation`, verified
  locally); `world_seed` is fixed (not resampled) per the spec's own disclosed
  9-cell/one-seed scope — no silent resampling anywhere in `cases.py`.
- **Replay honesty:** `replay.py`'s `replay_episode` genuinely re-executes
  through a **second, independent** `GovsimBridge`/plugin instance driven by
  `run_episode` (not a cached/re-read result) — verified both by reading
  `replay.py:204-236` and by the tamper test
  (`test_replay_of_a_tampered_response_diverges_from_the_original_and_is_caught_by_comparison`,
  `test_govsim_replay.py:628-679`), which I re-ran live: mutating one recorded
  `quantity` genuinely produces a different final state that
  `compare_episode_results`/`assert_replay_matches` catches, not a rubber-stamp
  pass.
- **QC Gate-2, "are all five goldens real":** yes. All five
  (`test_golden_successful_*`, `test_golden_valid_but_poor_*`,
  `test_golden_invalid_unauthorized_*`, `test_golden_malformed_operational_*`,
  `test_golden_degenerate_reference_*`, all in `test_govsim_measurement.py`)
  use the actual `GovsimBridge` against the real pinned upstream checkout, not
  a fake — confirmed by re-running them live (see method note above). The
  structural, fake-bridge versions of the same five scenarios in
  `test_govsim_environment.py` are explicitly and correctly labeled
  non-fidelity in that file's own module docstring.
- **Verifier-declaration correctness:** no leaf's `verifier_family`/
  `evaluation_class` claims something judge-dependent as deterministic, or
  something derived as independent upstream confirmation. `govsim_no_collapse`
  and `govsim_threshold_adherence` read upstream's own recorded
  `collapsed_or_horizon`/`wanted_resource`/`sustainability_threshold` values
  verbatim (never recomputing the regeneration formula or collapse test
  independently — confirmed against the real upstream
  `concurrent_env.py:400-448`); the three `comparative`/`baseline_delta` leaves
  keep `primary`, `reference_values["baseline"]`, and the delta as three
  distinct numbers, never blended (`measurement.py:596-710`); no
  `objective_reference` leaf is declared anywhere (per P06), confirmed by
  `test_no_objective_reference_leaf_is_declared_per_p06`.
- Upstream's `log_step_conversation`'s `html_interactions[-2]`/`[-1]` indexing
  (a real upstream quirk for an empty-conversation chat action) is correctly
  worked around by the driver's two-placeholder list
  (`govsim_bridge_driver.py:209-216`) — verified against the real
  `concurrent_env.py:486-521`.
- `self.terminations` is properly initialized per-agent to `False` by
  upstream's own `_init_agent` during `reset()` (not left as an empty dict, as
  I initially suspected while tracing `environment.py`'s
  `all(projection["terminations"].values())` check) — no false-early
  termination risk after the first harvest batch.
