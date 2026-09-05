#!/usr/bin/env bash
#
# Provision the interpreter the econevals adapter uses to talk to upstream.
#
# The econevals family's central claim is a generated pilot corpus that is
# byte-reproducible from its (track, difficulty, seed) triple, plus exact
# optimum references computed by delegating to upstream's own solvers
# (gurobipy for procurement, scipy for pricing) rather than reimplementing
# them. Every test that checks either claim needs an interpreter that can
# import the pinned upstream checkout under Python >= 3.12; this project runs
# on 3.11 and deliberately does not carry these dependencies.
#
# Without this interpreter those tests do not fail -- they skip. See
# tools/tau2_bridge/README.md for why a silent skip on a fidelity claim is the
# failure mode this pattern exists to prevent; the same reasoning applies here.
#
# Usage:
#   tools/econevals_bridge/provision.sh [venv-path]
#
# Then export what it prints, or add it to your shell profile.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${1:-/Users/sunzeyu/Documents/econ benchmark/bridges/econevals-venv}"
REQS="${HERE}/requirements.txt"

find_python() {
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "error: no Python >= 3.12 on PATH." >&2
  echo "       Upstream econ-evals declares python_version = 3.12 in its Pipfile." >&2
  echo "       On macOS: brew install python@3.12" >&2
  exit 1
fi

echo "interpreter : ${PYTHON} ($("${PYTHON}" -c 'import platform; print(platform.python_version())'))"
echo "venv        : ${VENV}"

"${PYTHON}" -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --disable-pip-version-check --upgrade pip
"${VENV}/bin/pip" install --quiet --disable-pip-version-check -r "${REQS}"

# Make the pinned upstream checkout importable WITHOUT touching it: no
# `pip install -e`, which drops an .egg-info build artifact into the source
# tree. Upstream is read-only (see docs/econevals_adapter_spec.md); a .pth
# file lives entirely in this venv's own site-packages instead.
# Not derived from $HERE by relative ".." count: this file lives under a git
# worktree (variable depth) as often as under the main checkout, and the
# upstream checkout's location is fixed and given, not guessed.
UPSTREAM_ROOT="${AEREAD_ECONEVALS_UPSTREAM_ROOT:-/Users/sunzeyu/Documents/econ benchmark/upstream-econevals}"
if [ -d "${UPSTREAM_ROOT}/econ_evals" ]; then
  SITE_PACKAGES="$("${VENV}/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
  printf '%s\n' "${UPSTREAM_ROOT}" > "${SITE_PACKAGES}/econevals_upstream.pth"
else
  echo "error: pinned upstream checkout not found at ${UPSTREAM_ROOT}" >&2
  echo "       set AEREAD_ECONEVALS_UPSTREAM_ROOT and re-run" >&2
  exit 1
fi

# Prove the interpreter can actually do its job, rather than reporting
# success because pip exited zero: import each track's generator, and confirm
# gurobipy resolves a tiny model (the free license's smallest possible check).
if "${VENV}/bin/python" >/dev/null 2>&1 <<'PY'
from econ_evals.experiments.procurement.generate_instance import generate_instance
from econ_evals.experiments.procurement.opt_solver import compute_opt
from econ_evals.experiments.scheduling.generate_preferences import generate_preferences
from econ_evals.experiments.pricing.generate_instance import generate_instance as _pricing_gen
from econ_evals.experiments.pricing.pricing_market_logic_multiproduct import get_monopoly_prices
import gurobipy as gp
env = gp.Env(empty=True)
env.setParam("OutputFlag", 0)
env.start()
PY
then
  echo "verified    : all three track generators import; gurobipy resolves an env"
else
  echo "error: the venv was built but cannot import upstream's generators/solvers." >&2
  echo "       Checked upstream root: ${UPSTREAM_ROOT}" >&2
  exit 1
fi

echo
echo "Export this to make the fidelity tests run instead of skip:"
echo
echo "    export AEREAD_ECONEVALS_BRIDGE_PYTHON=${VENV}/bin/python"
echo
