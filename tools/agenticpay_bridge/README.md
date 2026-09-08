# The upstream AgenticPay bridge interpreter

The agenticpay.bilateral adapter's central claim is that it drives the real,
pinned upstream negotiation environment (`BaseEnv.reset`/`step`) rather than
reimplementing any of its price/contract extraction, legality checks, or
scoring formulas. Everything downstream inherits its credibility from that
claim, and the tests that check it cannot run in this project's own
interpreter.

## Why a second interpreter

Importing `agenticpay` at all unconditionally imports
`agents.buyer_agent`/`agents.seller_agent`, both of which do `from loguru
import logger` -- a dependency upstream's own `requirements.txt` never
declares and which this project's own venv deliberately does not carry (it is
read-only; nothing is ever installed into it). The two cannot share an
environment, so the adapter delegates to upstream across a subprocess:
`src/aeread_families/agenticpay_bilateral/agenticpay_bridge.py` spawns
`agenticpay_bridge_driver.py` under a separate interpreter that has
`loguru`/`numpy` installed, hands it a fresh construction of the pinned
environment plus an ordered round history, and gets back upstream's own
`step()` result. Upstream's price/contract extraction, legality checks, and
scoring formulas are never reimplemented on this side.

## The failure mode this exists to prevent

Without that interpreter, the upstream-fidelity tests do not fail. They
**skip**. That is the right behavior for someone working on an unrelated part
of the repo, and a trap everywhere else, because a green suite then means
"the fidelity tests did not run", not "the adapter matches upstream" (see
`tools/tau2_bridge/README.md` for the sibling adapter where this was first
discovered the hard way).

Two things guard against a repeat:

- `provision.sh` makes the interpreter one command to obtain, and verifies it
  can import upstream's bilateral environment rather than trusting that
  `pip` exited zero.
- `AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1` turns a bridge-related skip into a
  failed run (see the root `conftest.py`). Set it in CI and in any run meant
  to certify fidelity. It is off by default.

## Usage

```bash
tools/agenticpay_bridge/provision.sh          # defaults to ~/.cache/aeread/agenticpay-bridge-venv
export AEREAD_AGENTICPAY_BRIDGE_PYTHON=<printed path>

# fidelity tests now run instead of skipping
pytest tests/test_agenticpay_bilateral_environment.py

# and in CI, prove they ran
AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1 pytest
```

The adapter also accepts a venv colocated at `<upstream_root>/.venv/bin/python`
without any environment variable; see `discover_bridge_python`.

## On upstream's own stdout noise, and on the stale `info["buyer_utility"]`

Two upstream quirks the bridge driver works around, not fixes:

- `Task1BasicPriceNegotiation._calculate_reward`/`_calculate_seller_reward`/
  `_calculate_buyer_reward` call `print(...)` unconditionally on every
  terminal round. Left alone this corrupts the driver's one-JSON-object-on-
  stdout protocol; the driver redirects upstream's own stdout to a throwaway
  buffer for the duration of every call.
- `info["buyer_utility"]`/`info["seller_utility"]` are built (via
  `_get_info()`) *before* the score-calculation methods that are the only
  place upstream ever populates them run, so they are always `null` in the
  dict `step()` returns -- even on a terminal round with a real,
  non-degenerate contract utility. The driver reads the correct,
  already-computed values off `env.state.metadata` after `step()` returns
  instead, never recalculating `u_b`/`u_s` itself. See
  `agenticpay_bridge_driver.py`'s `_overlay_contract_utilities` docstring for
  the reproduction.
