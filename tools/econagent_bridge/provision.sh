#!/usr/bin/env bash
#
# Provision the interpreter the econagent adapter uses to talk to upstream.
#
# ai_economist.foundation and simulate.py's complex_actions need numpy/scipy/
# lz4/pyyaml/pandas/seaborn/matplotlib/python-dateutil/fire -- none of which
# may be installed into the project's own venv (see docs/
# econagent_adapter_spec.md's "Governing facts" and milestone-1 corrections).
# This is package isolation, not a Python-version floor: upstream declares no
# minimum, so any Python >= 3.11 works here (unlike tau2's >= 3.12).
#
# Without this interpreter the econagent bridge-gated tests skip rather than
# fail. See AEREAD_ECONAGENT_BRIDGE_REQUIRED for the switch that turns such a
# skip into an error (mirroring AEREAD_TAU2_BRIDGE_REQUIRED; as of this
# writing that enforcement hook only exists for tau2 in the shared root
# conftest.py -- see the econagent ledger).
#
# Usage:
#   tools/econagent_bridge/provision.sh [venv-path]
#
# Then export what it prints, or add it to your shell profile.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${1:-/Users/sunzeyu/Documents/econ benchmark/bridges/econagent-venv}"
REQS="${HERE}/requirements.txt"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "error: no Python >= 3.11 on PATH." >&2
  echo "       On macOS: brew install python@3.12" >&2
  exit 1
fi

echo "interpreter : ${PYTHON} ($("${PYTHON}" -c 'import platform; print(platform.python_version())'))"
echo "venv        : ${VENV}"

"${PYTHON}" -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --disable-pip-version-check --upgrade pip
"${VENV}/bin/pip" install --quiet --disable-pip-version-check -r "${REQS}"

# Prove the interpreter can actually do the one job it has, rather than
# reporting success because pip exited zero: import ai_economist.foundation
# AND reach complex_actions via `from simulate import complex_actions`,
# running with cwd=<upstream_root> the way the real driver always does (see
# milestone-1 corrections 1-2: both simulate.py's top-level config.yaml read
# and one_step_economy.py's data/profiles.json read are cwd-relative).
# Hard-coded rather than derived from ${HERE} by relative ".." hops: this
# script runs from whichever checkout or worktree happens to hold it (their
# nesting depth under "econ benchmark" differs), while upstream-econagent's
# location is fixed and given directly by the adapter's ground rules.
UPSTREAM_ROOT="${AEREAD_ECONAGENT_UPSTREAM_ROOT:-/Users/sunzeyu/Documents/econ benchmark/upstream-econagent}"
if [ -f "${UPSTREAM_ROOT}/config.yaml" ]; then
  if (cd "${UPSTREAM_ROOT}" && "${VENV}/bin/python" - >/dev/null 2>&1 <<'PY'
import sys
sys.path.insert(0, ".")
import ai_economist.foundation as foundation
from simulate import complex_actions
sys.exit(0 if callable(complex_actions) and hasattr(foundation, "make_env_instance") else 1)
PY
  )
  then
    echo "verified    : ai_economist.foundation and simulate.complex_actions both import"
  else
    echo "error: the venv was built but cannot import the pinned upstream checkout." >&2
    echo "       Checked upstream root: ${UPSTREAM_ROOT}" >&2
    exit 1
  fi
else
  echo "note        : upstream checkout not found at ${UPSTREAM_ROOT}; skipped the import check"
  echo "              set AEREAD_ECONAGENT_UPSTREAM_ROOT and re-run to verify"
fi

echo
echo "Export this to make the fidelity tests run instead of skip:"
echo
echo "    export AEREAD_ECONAGENT_BRIDGE_PYTHON=${VENV}/bin/python"
echo
