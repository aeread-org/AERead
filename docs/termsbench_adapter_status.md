# termsbench adapter — status

Branch `zeyu/termsbench-adapter`. Last verified 2026-09-02 (milestone 3 of 3).

## What the adapter claims

`termsbench` is a **faithful reimplementation from the paper** of TERMS-Bench's
bilateral alternating-offer price-negotiation environment (arXiv
`2605.13909v2`) — there is no upstream code (the paper's own repository link
is dead), so nothing here is a "port" or a wrapper around someone else's
binary. The environment, the counterpart kernel (Candid/Taciturn/Expressive,
3 of the paper's 6 families), and 4 measurement leaves are all AERead's own
from-scratch code, translating cited equations, run through the real
shared-runner scheduler (`run_episode`/`PluginRegistry`), never a hand-wired
shortcut. See `docs/termsbench_adapter_spec.md` for the full design and
milestone 1's reality-forced-deviation amendment (section 7).

Milestone 3 (this one) adds the piece milestones 1–2 deferred: a scripted
harness that drives complete episodes through the real scheduler with
**sealed evidence**, and an **offline replayer** that reproduces a recorded
episode's state and every declared score with zero random draws and zero
provider calls.

| Leaf | Verifier family | Evaluation class | Declared when |
|---|---|---|---|
| `termsbench_surplus_efficiency` | `comparative` (`head_to_head`) | `deterministic` | Overlap regime only |
| `termsbench_feasible_agreement` | `comparative` (`head_to_head`) | `deterministic` | Overlap regime only |
| `termsbench_no_deal_agreement` | `comparative` (`head_to_head`) | `deterministic` | No-deal regime only |
| `termsbench_protocol_compliance` | `rule_constraint` (`constraint_satisfaction`) | `deterministic` | every episode |

## Evidence

**Sealed evidence per round, not just embedded response data.** Unlike
`tau3_retail` (whose tool calls are sealed through `ToolRuntime`), termsbench
has no tools, so `ScriptedTermsBenchHarness` now accepts an optional
`EvidenceStore` and seals one durable event per logical action —
`termsbench_agent_response` for an agent turn, `termsbench_counterpart_draws`
(the raw random draws `kernel.resolve_counterpart_turn` consumed, plus the
resolved decision) for a counterpart turn — each tagged with its own
`phase_instance_id`/`logical_action_id`. `evidence` is optional and defaults
to `None`, so every pre-existing provider-free unit test that never passed
one is unaffected.

`tests/test_termsbench_harness.py` drives 2 full episodes end to end through
`run_episode`, against real on-disk pilot cases (not hand-built payloads):

- a real **Overlap** case (`termsbench.candid.overlap.1000001`) through 2
  counterpart rounds to `agent_accept`, scoring `SE+ > 0`, `AGR+ = 1`;
- a real **No-deal** case (`termsbench.candid.nodeal.1010011`) through 5
  rounds to `counterpart_walk_away`, scoring `FAGR- = 0` (no false
  agreement).

Both episodes' evidence is sealed and then **independently reopened from
disk** (`EvidenceStore.audit_existing`, a fresh object, not the one that
wrote it) to verify the full hash chain and seal marker, confirm one sealed
event per logical action, and confirm a sealed write after `seal()` is
rejected (`EvidenceSealedError`) — proving the seal is real, not merely
called once and never checked.

**Offline replay reproduces state and score with zero random draws.**
`src/aeread_families/termsbench/replay.py` (the `tau3_retail/replay.py`
pattern, adapted for a stochastic counterpart kernel rather than an upstream
tool bridge): `record_episode` extracts the ordered raw responses from a
completed `EpisodeResult`; `RecordedResponseSource` serves them back through
the real scheduler with no RNG and no model call at all —
`TermsBenchPlugin.step()`'s own draws-recompute-and-verify (already exercised
live, `tests/test_termsbench_environment.py`'s
`test_step_rejects_a_counterpart_response_that_lies_about_its_resolution`) is
the actual replay guarantee; this module is only the outer bookkeeping.

`tests/test_termsbench_replay.py` (11 tests) covers both live episodes above:

- replay from a JSON-round-tripped record reproduces the live run's state
  **byte-identically** (`compare_episode_results(...).matches is True`,
  `canonical_json_bytes` equal) — termsbench state carries no wall-clock or
  message-timestamp field (unlike tau3_retail), so raw and content equality
  genuinely coincide here, not merely "close enough";
- every declared leaf recomputed from the replay matches the original run's
  score (`score_replayed_episode`);
- a tamper test (flipping one recorded `u_accept`) proves the mismatch still
  surfaces as `SchedulerContractError("... replay mismatch ...")` through
  replay, exactly as it does live;
- a cross-check ties the two milestone-3 claims together: the exact draws
  sealed into `EvidenceStore` per round equal the draws `record_episode`/
  replay reconstruct from — proving they are one substrate, not two
  independently-plausible but potentially divergent stories.

**Suite: 806 passed, 31 skipped, 1 xfailed** (full repo, `pytest -q`, no
`AEREAD_TAU2_BRIDGE_PYTHON` provisioned). The skips/xfail belong entirely to
`tau3_retail`'s bridge-gated fidelity tests and one pre-existing xfail;
nothing here skips. Scoped to this family plus the shared-runner smoke test:
**90 passed, 0 failed** (`tests/test_termsbench_*.py` +
`tests/test_shared_runner_smoke.py`); 16 of those are new this milestone
(5 harness, 11 replay).

## Known limits, stated rather than implied

- **Milestone 1's stated limits still apply unchanged**: the Oracle-Cue
  Bayes-optimal DP (App. D–E) is deferred, no `Gap_π`/upper-bound claim;
  `BE_type` is out of scope; only 3 of 6 counterpart families are
  implemented; the urgency-shift regime is deferred; counterpart language is
  a deterministic template, never an LLM. See
  `docs/termsbench_adapter_spec.md` section 6.
- **The harness/replay tests exercise scripted trajectories, not model
  behaviour.** Every episode in `test_termsbench_harness.py` /
  `test_termsbench_replay.py` is a fixed agent script chosen to hit a
  specific termination case deterministically (forced accept/reject/
  walk-away via `counterpart_draws_by_round` overrides on top of real pilot
  case parameters). That proves the scheduler/harness/replay machinery is
  correct; it says nothing about how any agent scores — exactly
  `tau3_adapter_status.md`'s own stated limit for its gold-trajectory parity.
- **Evidence sealing is adapter-owned, not a new kernel primitive.** There is
  no `ToolRuntime`-shaped abstraction for a non-tool family, so this harness
  calls `EvidenceStore.append_event` directly with two family-invented event
  types (`termsbench_agent_response`, `termsbench_counterpart_draws`). These
  do not participate in `EvidenceStore.audit_reconciliation`'s built-in
  `logical_action`/`action_attempt`/`provider_call`/`tool_invocation`
  started/terminal-suffix bookkeeping (no event type here uses those
  prefixes), so reconciliation passes trivially rather than actively
  validating this family's own event pairing. That is acceptable for this
  family's purpose (evidentiary logging of RNG draws, not lifecycle
  tracking), but it means the reconciliation check is not doing family-aware
  work here the way it would for a tool-calling family.
- **Replay's byte-identical claim is proved on 2 scripted episodes, not the
  30-case pilot corpus.** No parity-CLI-style full-corpus sweep exists for
  termsbench (there is no upstream binary to sweep against, unlike
  `tau3_retail`'s 114/114 corpus parity) — replay correctness here is a
  targeted proof on representative Overlap/No-deal trajectories, not an
  exhaustive one.
- **`RecordedResponseSource` exceptions surface wrapped, not bare.** Any
  `ReplayError` it raises mid-episode (exhausted record, phase/seat
  mismatch) is caught and re-raised as `SchedulerContractError` by
  `run_episode` itself (every `response_source` exception is wrapped there,
  an existing, general scheduler behavior also relied on by
  `tau3_retail`'s own tamper test) — only `replay_episode`'s own pre/post
  checks (wrong `case_id`, an unconsumed record tail after a *successful*
  replay) raise a bare `ReplayError`. Documented here so a caller does not
  write a `pytest.raises(ReplayError)` around a mid-episode exhaustion and
  get a confusing failure.

## No kernel/runner defect found

Nothing in this milestone required a kernel/runner change or worked around a
kernel defect. `EvidenceStore.append_event`, `seal()`, `verify_seal()`, and
`audit_existing()` all worked exactly as documented for a non-tool-calling
family's evidence needs.
