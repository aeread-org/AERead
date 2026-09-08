#!/usr/bin/env bash
#
# Provision the interpreter the govsim adapter uses to talk to upstream.
#
# Unlike tau3_retail's bridge, the blocker here is not a Python-version floor
# -- govsim runs fine under the project's own Python 3.11 (see
# docs/govsim_adapter_spec.md's governing facts; upstream's ROCm Dockerfile
# targets py3.10 and no .python-version pins anything higher). The blocker is
# that ConcurrentEnv/env.py import numpy, pandas, omegaconf, and
# pettingzoo.utils.agent_selector, none of which the project venv carries (and
# should not: they exist only to run one pinned upstream checkout).
#
# Without this interpreter the upstream-fidelity tests do not fail -- they
# skip. See tools/tau2_bridge/provision.sh's README for why that is the
# failure mode worth guarding against.
#
# Usage:
#   tools/govsim_bridge/provision.sh [venv-path]
#
# Then export what it prints, or add it to your shell profile.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${1:-/Users/sunzeyu/Documents/econ benchmark/bridges/govsim-venv}"
REQS="${HERE}/requirements.txt"

find_python() {
  for candidate in python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "error: no python3 on PATH." >&2
  exit 1
fi

echo "interpreter : ${PYTHON} ($("${PYTHON}" -c 'import platform; print(platform.python_version())'))"
echo "venv        : ${VENV}"

"${PYTHON}" -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --disable-pip-version-check --upgrade pip
"${VENV}/bin/pip" install --quiet --disable-pip-version-check -r "${REQS}"

# Prove the interpreter can actually do the one job it has, rather than
# reporting success because pip exited zero.
UPSTREAM_ROOT="${AEREAD_GOVSIM_UPSTREAM_ROOT:-$(cd "${HERE}/../../../.." && pwd)/upstream-govsim}"
if [ -d "${UPSTREAM_ROOT}/simulation" ]; then
  if "${VENV}/bin/python" "${HERE}/../../src/aeread_families/govsim/govsim_bridge_driver.py" \
      --upstream-root "${UPSTREAM_ROOT}" <<<'{"op": "runtime_info"}' >/dev/null 2>&1
  then
    echo "verified    : bridge driver imports numpy/pandas/omegaconf/pettingzoo"
  else
    echo "error: the venv was built but the bridge driver could not run." >&2
    echo "       Checked upstream root: ${UPSTREAM_ROOT}" >&2
    exit 1
  fi
else
  echo "note        : upstream checkout not found at ${UPSTREAM_ROOT}; skipped the driver check"
  echo "              set AEREAD_GOVSIM_UPSTREAM_ROOT and re-run to verify"
fi

echo
echo "Export this to make the fidelity tests run instead of skip:"
echo
echo "    export AEREAD_GOVSIM_BRIDGE_PYTHON=${VENV}/bin/python"
echo
