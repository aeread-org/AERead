# The upstream govsim bridge interpreter

The govsim adapter claims one thing above all else: **it reproduces upstream
govsim's common-pool-resource arithmetic exactly** -- the regeneration
formula, the collapse test, and `_assign_stochastic`/`_assign_proportional`
are upstream's, never reimplemented on this side (see
`docs/govsim_adapter_spec.md` section 3, "adapter boundary").

## Why a second interpreter

`ConcurrentEnv`/`env.py` import `numpy`, `pandas`, `omegaconf`, and
`pettingzoo.utils.agent_selector`. The project's own venv deliberately does
not carry any of these -- they exist only to run one pinned upstream
checkout, never to serve the rest of the codebase. Unlike tau2-bench, govsim
does not need a different Python *version* (it runs fine under the
project's own 3.11); only different site-packages. The adapter still
delegates across a subprocess for the same isolation reason `tau2_bridge.py`
does: a stray `numpy`/`pandas` import order should never let the bridge
venv's copy shadow the project's own already-imported copy in the same
interpreter.

`src/aeread_families/govsim/govsim_bridge.py` spawns
`govsim_bridge_driver.py` under a separate interpreter, hands it a scenario,
an env config, a seed, and the full ordered action history for the episode,
and gets back a plain-JSON projection of upstream's own resulting state.
Upstream's `ConcurrentEnv.step()`/`reset()` are never reimplemented, only
called.

## Why the bridge replays the whole action history every call

Unlike tau2-bench's `RetailDB` (a plain dict that fully describes state
between calls), upstream's `ConcurrentEnv` holds state that is not
JSON-safe: `datetime` values in `internal_global_state["next_time"]` and
`PersonaAction` instances in `internal_global_state["action"]`. There is no
dict this bridge can serialize once and pass back and forth the way
`tau2_bridge.py` passes `db`. Every call instead reconstructs the episode
from scratch (`reset(seed=...)`, then replays every recorded action in
order) inside one subprocess. Upstream's own `np.random.RandomState` is
seeded once by `reset` and consumes draws in the exact same call sequence on
every replay, so this is deterministic, not merely "usually the same" (see
`govsim_bridge_driver.py`'s module docstring, verified during recon). This
keeps the same per-call, no-daemon subprocess discipline as `tau2_bridge.py`
at the cost of O(n) upstream `step()` calls replayed per bridge call instead
of O(1); those calls are pure arithmetic and episodes are short (at most
`(2*num_agents+1) * max_num_rounds` actions), so the added CPU cost is
noticeable (see the spec's implementation notes) but not disqualifying for
this milestone. An O(1) state-serialization design (round-tripping
`np.random.RandomState.get_state()`/`set_state()` plus hand-serialized
`datetime`/`PersonaAction` fields) is a documented follow-up if replay cost
becomes a bottleneck for the replay/parity milestone.

## The failure mode this exists to prevent

Without that interpreter, upstream-fidelity tests should skip, never fail
silently as passing. This adapter's own milestone-1 test suite
(`tests/test_govsim_cases.py`, `tests/test_govsim_environment.py`) is
deliberately bridge-independent (see their module docstrings) so this does
not apply yet; it will once the replay/parity suite lands.

## Usage

```bash
tools/govsim_bridge/provision.sh                  # defaults to bridges/govsim-venv
export AEREAD_GOVSIM_BRIDGE_PYTHON=<printed path>
```

The adapter also accepts a venv colocated at `<upstream_root>/.venv/bin/python`
without any environment variable; see `discover_bridge_python`.

## On pinning

`requirements.txt` freezes exact versions, not the open ranges upstream's own
`requirements.txt` implies for its full persona_v3/wandb stack (which this
adapter never installs or imports): "the adapter reproduces upstream's
arithmetic exactly" is a claim about a specific interpreter. `numpy` and
`pettingzoo` match upstream's own pins; `pandas` and `omegaconf` are not
pinned upstream at all (they are transitive there, via `dash`/`hydra-core`)
and are pinned here to versions verified compatible with `numpy==1.24.4`
under Python 3.11.
