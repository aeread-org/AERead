# The upstream tau2-bench bridge interpreter

The tau3 retail adapter claims one thing above all else: **it reproduces upstream
tau2-bench exactly.** Everything downstream — the canonical-reference verifier
family, the deterministic DB-equality leaf, the paper's primary number for this
case family — inherits its credibility from that claim.

The claim is only worth what the tests that check it are worth, and those tests
cannot run in this project's own interpreter.

## Why a second interpreter

Upstream requires Python >= 3.12 and pulls in nineteen runtime dependencies.
This project runs on 3.11 and deliberately does not carry them. The two cannot
share an environment, so the adapter delegates to upstream across a subprocess:
`src/aeread_families/tau3_retail/tau2_bridge.py` spawns
`tau2_bridge_driver.py` under a separate interpreter, hands it a database and a
tool call, and gets back upstream's own answer. Upstream tool bodies, scoring
rules, and database mutations are never reimplemented on this side.

## The failure mode this exists to prevent

Without that interpreter, the upstream-fidelity tests do not fail. They **skip**.

That is the right behavior for someone working on an unrelated part of the repo,
and it is a trap everywhere else, because a green suite then means "the fidelity
tests did not run", not "the adapter matches upstream". This was not
hypothetical: the adapter's first full run reported `544 passed, 29 skipped` and
26 of those skips were precisely the tests for tools, environment, measurement,
replay, and parity — the entire fidelity surface, never once executed.

Two things guard against a repeat:

- `provision.sh` makes the interpreter one command to obtain, and verifies it
  can import upstream's retail environment rather than trusting that `pip`
  exited zero.
- `AEREAD_TAU2_BRIDGE_REQUIRED=1` turns a bridge-related skip into a failed
  run (see the root `conftest.py`). Set it in CI and in any run meant to
  certify fidelity. It is off by default.

## Usage

```bash
tools/tau2_bridge/provision.sh                  # defaults to ~/.cache/aeread/tau2-bridge-venv
export AEREAD_TAU2_BRIDGE_PYTHON=<printed path>

# fidelity tests now run instead of skipping
pytest tests/test_tau3_retail_parity.py

# and in CI, prove they ran
AEREAD_TAU2_BRIDGE_REQUIRED=1 pytest
```

The adapter also accepts a venv colocated at `<upstream_root>/.venv/bin/python`
without any environment variable; see `discover_bridge_python`.

## On pinning, and on litellm

`requirements.txt` freezes exact versions. Upstream declares open ranges, but
"reproduces upstream exactly" is a statement about a specific interpreter, not
about a range — an upstream dependency that changes a float repr or a dict
ordering would move our canonical hashes without any change on our side.

`litellm` appears in that list because upstream's package import graph reaches
it: `tau2/__init__.py` imports `tau2.runner`, which reaches the model layer.
Installing it does not make the adapter call a provider. No scoring path invokes
a judge; the single live-model call on the NL-assertions judge path is
monkeypatched to capture-and-return so that parity can compare *the prompt
upstream would send*, never a verdict. The bridge takes no API key and makes no
network request.
