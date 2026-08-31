#!/usr/bin/env bash
#
# Provision the interpreter the tau3 retail adapter uses to talk to upstream.
#
# The adapter's central claim is that it reproduces upstream tau2-bench exactly.
# Every test that checks that claim needs an interpreter which can import the
# pinned upstream checkout. The project itself runs on Python 3.11 and upstream
# requires >= 3.12, so the two cannot share one environment; the adapter bridges
# them across a subprocess instead.
#
# Without this interpreter those tests do not fail -- they skip. A silent skip
# on the tests that carry the paper's fidelity claim is the failure mode this
# script exists to prevent. See AEREAD_TAU2_BRIDGE_REQUIRED in the test suite
# for the switch that turns such a skip into an error.
#
# Usage:
#   tools/tau2_bridge/provision.sh [venv-path]
#
# Then export what it prints, or add it to your shell profile.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${1:-${HOME}/.cache/aeread/tau2-bridge-venv}"
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
  echo "       Upstream tau2-bench requires it; the project's own 3.11 cannot import upstream." >&2
  echo "       On macOS: brew install python@3.12" >&2
  exit 1
fi

echo "interpreter : ${PYTHON} ($("${PYTHON}" -c 'import platform; print(platform.python_version())'))"
echo "venv        : ${VENV}"

"${PYTHON}" -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --disable-pip-version-check --upgrade pip
"${VENV}/bin/pip" install --quiet --disable-pip-version-check -r "${REQS}"

# Prove the interpreter can actually do the one job it has, rather than
# reporting success because pip exited zero.
UPSTREAM_ROOT="${AEREAD_TAU2_UPSTREAM_ROOT:-$(cd "${HERE}/../../../.." && pwd)/upstream-tau2}"
if [ -d "${UPSTREAM_ROOT}/src" ]; then
  if "${VENV}/bin/python" - "${UPSTREAM_ROOT}" >/dev/null 2>&1 <<'PY'
import sys
sys.path.insert(0, f"{sys.argv[1]}/src")
from tau2.domains.retail.environment import get_environment
tools = get_environment().get_tools()
sys.exit(0 if len(tools) == 16 else 1)
PY
  then
    echo "verified    : upstream retail environment imports, 16 tools resolved"
  else
    echo "error: the venv was built but cannot import upstream's retail environment." >&2
    echo "       Checked upstream root: ${UPSTREAM_ROOT}" >&2
    exit 1
  fi
else
  echo "note        : upstream checkout not found at ${UPSTREAM_ROOT}; skipped the import check"
  echo "              set AEREAD_TAU2_UPSTREAM_ROOT and re-run to verify"
fi

echo
echo "Export this to make the fidelity tests run instead of skip:"
echo
echo "    export AEREAD_TAU2_BRIDGE_PYTHON=${VENV}/bin/python"
echo
