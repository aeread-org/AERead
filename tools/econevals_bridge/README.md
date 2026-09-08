# The upstream econ-evals bridge interpreter

The econevals family's pilot claims two things: the wrapped corpus is
byte-reproducible from its `(track, difficulty, seed)` triple, and its
objective-reference optima are upstream's own solver output (gurobipy for
procurement, scipy for pricing), never a reimplementation on our side.

Both claims need an interpreter that can import the pinned upstream checkout.
Upstream requires Python >= 3.12 and pulls in gurobipy, scipy, pandas,
pydantic, and inflect; this project runs on 3.11 and deliberately does not
carry them.

## Why a fresh subprocess per call, not just a separate interpreter

Recon found that `econ_evals.experiments.procurement.generate_instance`
computes its `budget` field from the **global** `numpy.random` state
(`np.random.uniform(0, 1)`) instead of the `my_random: RandomState` argument
every other draw in the same function uses. Two calls in the same process
with the same seed and a freshly constructed `RandomState(seed)` therefore
produce byte-identical entries, item groups, effectiveness scores, and start
allocation, but a **different budget** whenever any other code in that
process consumed the global RNG first — this is upstream's bug, not ours, and
it is exactly the kind of gap the corpus admission gate exists to catch (see
`docs/econevals_adapter_spec.md` S1).

The bridge driver therefore runs one instance generation (or one scoring
call) per fresh subprocess and pins `np.random.seed(seed)` at the top of that
subprocess, immediately before calling the upstream generator. A fresh
interpreter has no prior global-RNG draws to leak, so this reproduces the
full instance byte-for-byte across repeated invocations — verified for all
three tracks during recon (procurement, scheduling, pricing: N/N seeds
byte-identical across two independent subprocess runs each). Do not call the
upstream generators twice in one long-lived process; the second call is not
guaranteed reproducible.

## Usage

```bash
tools/econevals_bridge/provision.sh   # defaults to the sibling bridges/econevals-venv
export AEREAD_ECONEVALS_BRIDGE_PYTHON=<printed path>
```

The provisioned venv installs: `numpy==2.5.2`, `scipy==1.18.1`,
`pandas==3.0.5`, `pydantic==2.13.5`, `inflect==7.5.0`, `gurobipy==13.0.3`
(see `requirements.txt` for why each is needed), then makes the pinned
upstream checkout importable via a `.pth` file written into the venv's own
site-packages — never `pip install -e` on the checkout itself, which would
drop an `.egg-info` build artifact into the read-only upstream tree.

## On gurobipy licensing

The pip-installed `gurobipy` ships a size-limited free license — no license
file needed, but it silently rejects models past a variable/constraint cap.
Basic-difficulty procurement (3 inputs x 4 alternatives, 12 menu entries)
solves under it (verified during recon: `compute_opt` returned an integer
optimum with no license error). Upstream's own comment in
`run_procurement_batch.py` warns Hard difficulty needs an academic license;
this pilot never runs Medium or Hard procurement for that reason.
