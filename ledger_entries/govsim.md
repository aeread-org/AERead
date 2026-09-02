# govsim adapter -- ledger of defects/limitations found in OUR runner/kernel/environment

Format: severity | where | what | evidence | suggested fix. Entries here never fix the
kernel itself (per the govsim build's ground rules) -- they record what was found so
someone owning that code can act on it.

## 1. low | process | Milestone 1's own commit message claimed this file, but it was never
committed

**What:** the milestone-1 commit (`feat(govsim): add case corpus and kernel environment
adapter`) says in its own message: "`ledger_entries/govsim.md`: three new entries
(benchmark_qc.md location, a scheduler.py phase-budget documentation gap, and a
forward-looking plugin-teardown-hook design note)." `docs/govsim_adapter_spec.md` itself
cites this file by name in three places (the "governing facts" list, section 7's
phase-budget note, and section 7's "docs/benchmark_qc.md" note) as if it already existed.

**Evidence:** `git ls-tree -r 45573c3 --name-only | grep -i ledger` returns nothing; `git
show --stat 45573c3` lists 26 changed files, none under `ledger_entries/`. The directory did
not exist on this branch until this milestone created it.

**Suggested fix:** none needed on our side going forward -- this entry backfills the three
entries the commit message described (below), reconstructed from direct verification against
the current repository state rather than from the commit message's prose alone. If this
recurs, a pre-commit check that a commit message referencing `ledger_entries/<family>.md`
actually touches that path would catch it mechanically.

## 2. low | docs/benchmark_qc.md | `docs/govsim_adapter_spec.md` cites QC Gate 1/2 terminology
from a doc that does not exist on this branch or on `main`

**What:** the spec's section 1/4 headings ("QC Gate 1", "QC Gate 2") are described as
referencing `docs/benchmark_qc.md`, but that file is not present in this checkout. The spec
itself self-defines the two gate terms inline (section 1 and section 4) rather than depending
on the missing file's contents, so nothing in this milestone's work is blocked by the gap --
but a future reader following the citation will hit a dead reference.

**Evidence:** `ls docs/benchmark_qc.md` -> "No such file or directory" (verified directly, not
merely asserted); `git log --all --oneline -- docs/benchmark_qc.md` (not checked further here,
per the milestone-1 commit message this exists only on an unmerged sibling branch/commit).

**Suggested fix:** either land `docs/benchmark_qc.md` on `main` (if the sibling branch that
has it is still live) or drop the citation from `docs/govsim_adapter_spec.md` in favor of the
already-inline gate definitions, so the doc is self-contained.

## 3. medium | src/aeread/shared_runner/scheduler.py | `phase_action_counts` accumulates
per-phase across the WHOLE episode, never resets per round/instance -- underdocumented,
easy to size wrong

**What:** `run_episode`'s `phase_action_counts: dict[str, int] = {}` (scheduler.py, function
scope) is keyed by `phase.phase_id` alone and incremented every time that phase runs again
across the episode (govsim's `harvest`/`discuss`/`reflect` phases each recur once per round,
for up to `max_num_rounds` rounds) -- never reset when a phase is re-entered. A
`PhaseSpec.max_logical_actions` therefore must be sized as the phase's total budget over the
WHOLE episode (e.g. govsim's `harvest`/`reflect`: `num_agents * max_num_rounds`; `discuss`:
`1 * max_num_rounds`), not a per-round or per-episode-shared value the way a single-visit
phase (e.g. `tau3_retail`'s two phases, which each run at most once) can get away with. There
is no docstring on `PhaseSpec.max_logical_actions` or `run_episode` calling this out; a family
author whose phases recur (any round/turn-based topology, not just govsim) can plausibly size
this as "N per round" and have the scheduler silently reject a legitimate late-episode action
as over-budget.

**Evidence:** `grep -n "phase_action_counts" src/aeread/shared_runner/scheduler.py` shows the
dict declared once per `run_episode` call (line ~703) and incremented via
`phase_action_counts[phase.phase_id] = phase_action_counts.get(phase.phase_id, 0) + 1` in two
call sites (~746, ~802), both checked against `phase.max_logical_actions` with no reset
anywhere in between. Confirmed directly against this checkout's `scheduler.py`, not merely
carried over from the milestone-1 commit message.

**Suggested fix:** add a one-line note on `PhaseSpec.max_logical_actions` (and/or
`run_episode`'s own docstring) stating explicitly that the budget is a whole-episode total per
phase id, not per visit/round -- this is exactly the distinction
`docs/govsim_adapter_spec.md` section 7 had to work out empirically and record itself.

## 4. low | src/aeread/shared_runner/registry.py, scheduler.py | no plugin-level teardown/close
hook exists for a family plugin

**What:** `REQUIRED_FAMILY_PLUGIN_HOOKS` (registry.py) lists 13 hooks
(`validate_payload` ... `generator`) and none of them is a teardown/close/dispose call; a
plugin instance is expected to live for the registry's lifetime with no lifecycle end event.
The one close-style hook that does exist in this package (`EvidenceStore`/whatever
`execution.py:314`'s `close`/`__exit__`/`__del__` belongs to) is a different, tool-runtime-level
construct, not something a family plugin itself can hook into.

**Why it matters here:** `govsim_bridge.py`'s current design is a per-call, no-daemon
subprocess (mirroring `tau2_bridge.py`) specifically because there is no way for a family
plugin to be notified "this episode/run is over, release your resources" -- a daemon-shaped
alternative (one long-lived bridge subprocess reused across calls, avoiding the O(n)
action-replay cost documented in `docs/govsim_adapter_spec.md` section 7) would need exactly
such a hook to know when to terminate the subprocess. This is a forward-looking note, not a
blocker for this milestone: the per-call design works and was verified end-to-end (spec
section 7).

**Evidence:** `grep -n "teardown\|cleanup\|def close\|dispose\|__exit__\|atexit"
src/aeread/shared_runner/scheduler.py src/aeread/shared_runner/registry.py
src/aeread/shared_runner/execution.py` matches only `execution.py`'s `close`/`__exit__`/
`__del__` (not on the family-plugin hook boundary at all); `REQUIRED_FAMILY_PLUGIN_HOOKS`
(registry.py) confirmed to list no such hook.

**Suggested fix:** if/when a daemon-shaped bridge becomes worth the added complexity (e.g. the
replay/parity milestone's wall-clock cost becomes a bottleneck, per spec section 7), the
kernel would need either an optional `teardown(self) -> None` family-plugin hook invoked once
per run, or an out-of-band registration (e.g. `atexit`) left entirely to the plugin's own
constructor -- worth a short design note before anyone builds it, not before.

## 5. informational | src/aeread_families/govsim | measurement.py (Milestone 2) needed a
new bridge op (`call_upstream_gini`) to source-extract one upstream function without
importing its module

**What:** not a kernel defect, but worth recording as precedent: `equality_gini`'s parity
test (spec section 5's P4) needed to call upstream's real, unmodified `gini()`
(`simulation/analysis/plots.py`) to cross-check the verbatim-vendored copy in
`measurement.py`. That module's own top-level imports (`plotly`, `dash`,
`dash_mantine_components`, `statsmodels`) are not installed in `bridges/govsim-venv` and were
deliberately never added there (see `tools/govsim_bridge/requirements.txt`'s own rationale).
`govsim_bridge_driver.py`'s new `_op_call_upstream_gini`/`_load_upstream_gini` therefore parse
the pinned file with `ast`, extract just the `gini` function's source segment, and `exec` it in
a namespace with only `numpy` -- the same style of "controlled avoidance of an unrelated
sibling module's import graph" as the existing `simulation.persona` package-stub workaround
(spec section 3.2), just via source extraction rather than a package-`__init__` stub, since
`plots.py` is the module itself, not a package with an `__init__.py` to route around.

**Evidence:** verified directly: `bridges/govsim-venv/bin/python -c "import plotly"` /
`import statsmodels` / `import dash` all raise `ModuleNotFoundError` in this checkout's
provisioned bridge venv; `GovsimBridge.call_upstream_gini` / vendored `_vendored_gini` agree
byte-for-byte on five sample arrays plus the negative-shift and NaN-removal branches
(`tests/test_govsim_measurement.py`'s parity section).

**Suggested fix:** none -- this is a working pattern, recorded here only so a future adapter
facing the same "need one pure function from an otherwise-heavy upstream module" problem does
not have to rediscover it.

## 6. low | src/aeread/shared_runner/schemas.py | `MeasurementDeclaration.measurement_kind`'s
enum has no bare "comparative" value, forcing a fully-deterministic, non-judged family to
declare `"comparative_or_human_judged"`

**What:** `MeasurementDeclaration.from_dict`'s `measurement_kind` enum is exactly
`{"property_or_answer", "optimizable_outcome", "comparative_or_human_judged"}` -- there is no
value for "comparative, but never human/judge-scored". `govsim`'s family manifest
(`src/aeread_families/govsim/environment.py`'s `family_manifest()`) is comparative-only (three
of its five leaves are `verifier_family="comparative"`/`reference_kind="baseline_delta"`) and
fully deterministic (every leaf in `measurement.py` declares
`evaluation_class="deterministic"`, none references a rater/judge/rubric), yet must pick the
"...or_human_judged" bucket anyway because it is the only legal value close to "comparative".
This was flagged during independent review (`docs/govsim_review_claude.md`'s S1) as a
pre-existing kernel schema limitation, not something introduced by that adapter's diff.

**Evidence:** `src/aeread/shared_runner/schemas.py:279-282`'s `_enum(data["measurement_kind"],
..., {"property_or_answer", "optimizable_outcome", "comparative_or_human_judged"})`; every leaf
returned by `src/aeread_families/govsim/measurement.py::build_leaves()` declares
`evaluation_class="deterministic"` (confirmed by
`tests/test_govsim_measurement.py::test_build_leaves_returns_exactly_five_leaves_matching_the_spec_table`),
and no leaf's `verifier_family`/fields reference a judge, rater, or rubric anywhere in that
module.

**Suggested fix:** split the enum into a bare `"comparative"` value distinct from
`"human_judged"` (or add a separate boolean/field such as `requires_rater_provenance`), so a
downstream consumer branching on family-level `measurement_kind` to decide whether
rater-provenance fields (rubric hash, rater identity, replicate count -- per
`docs/verifier_taxonomy.md` section 7) are required does not have to also read every leaf's own
`evaluation_class` to avoid a false positive for deterministic-only families like this one.
