# The upstream EconAgent bridge interpreter

The econagent adapter drives the pinned upstream `complex` (scripted, non-LLM) policy
path directly: `ai_economist.foundation` for the engine, `simulate.complex_actions` for
the scripted per-agent labor/consumption formulas. Neither is reimplemented on the
AERead side.

## Why a second interpreter

`ai_economist.foundation` needs `numpy`/`scipy`/`lz4`. Reaching `complex_actions` also
means importing `simulate.py` itself (`from simulate import complex_actions`), which
executes that module's full body — `matplotlib`/`yaml`/`fire`/`pandas`/`seaborn`/
`python-dateutil` at module scope. None of this may be installed into the project's own
venv (see `docs/econagent_adapter_spec.md`'s "Governing facts" and milestone-1
corrections), so the adapter delegates across a subprocess:
`src/aeread_families/econagent_v1/econagent_bridge.py` spawns
`econagent_bridge_driver.py` under a separate, already-provisioned interpreter.

## Why this bridge is a persistent subprocess, not one-shot-per-call

Unlike the tau3 retail adapter's `tau2_bridge.py` (one fresh subprocess per tool call,
with all state traveling in a plain JSON `db` dict), `complex_actions` needs the *live*
upstream `env` object: mutable per-agent `endogenous` fields it caches across months
(`consumption_fun_idx`/`work_fun_idx`, drawn once via `np.random.choice`), `env.world`
price/interest-rate history, and one shared numpy global RNG stream advancing in a fixed
per-agent order every month. None of that is a clean JSON round-trip target without
either reimplementing upstream's own RNG-driven formula selection (forbidden) or
replaying every prior month from scratch on every call. So the driver is spawned once
per episode, held open over stdin/stdout for `episode_length` months, and closed at the
end — see `docs/econagent_adapter_spec.md`'s milestone-1 correction 3 for the full
reasoning.

## cwd matters

The driver is always spawned with `cwd=<upstream_root>`. Two upstream reads are
cwd-relative and would otherwise fail or silently read the wrong file: `simulate.py`'s
own top-level `with open('config.yaml') as f: ...`, and
`ai_economist/foundation/scenarios/one_step_economy/one_step_economy.py`'s
`set_offer`/`reset_agent_states`, which both do a bare `open('data/profiles.json', 'r')`.
Neither is AERead's own defect — see milestone-1 corrections 1-2 — but the driver must
still run from the right directory for both to resolve to the pinned checkout instead of
whatever happens to be at the caller's own cwd.

## Usage

```bash
tools/econagent_bridge/provision.sh    # defaults to bridges/econagent-venv
export AEREAD_ECONAGENT_BRIDGE_PYTHON=<printed path>
```

The adapter also accepts a venv colocated at `<upstream_root>/.venv/bin/python`, or the
fixed default path `/Users/sunzeyu/Documents/econ benchmark/bridges/econagent-venv/bin/
python` with no environment variable at all; see `discover_bridge_python`.

## No network, no LLM

The driver only imports local, already-checked-out source (`ai_economist.foundation`,
`simulate.complex_actions`) and runs local numpy arithmetic. The `complex` policy path
never imports `openai` — that only happens lazily inside `simulate_utils.get_completion`,
reached only by `gpt_actions`, which this adapter never calls.
