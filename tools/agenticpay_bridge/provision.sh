#!/usr/bin/env bash
#
# Provision the interpreter the agenticpay.bilateral adapter uses to talk to
# upstream AgenticPay.
#
# The adapter's central claim is that it drives the real, pinned upstream
# negotiation environment -- never a reimplementation of its price/contract
# extraction, legality checks, or scoring formulas. Every test that checks
# that claim needs an interpreter that can import the pinned upstream
# checkout, and this project's own interpreter deliberately does not carry
# its runtime dependencies (loguru, numpy).
#
# Without that interpreter those tests do not fail -- they skip. A silent
# skip on the tests that carry the adapter's fidelity claim is the failure
# mode this script exists to prevent (mirrors tools/tau2_bridge/provision.sh
# exactly; see AEREAD_AGENTICPAY_BRIDGE_REQUIRED in the root conftest.py for
# the switch that turns such a skip into an error).
#
# Usage:
#   tools/agenticpay_bridge/provision.sh [venv-path]
#
# Then export what it prints, or add it to your shell profile.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${1:-${HOME}/.cache/aeread/agenticpay-bridge-venv}"
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
  echo "error: no python3 found on PATH." >&2
  exit 1
fi

echo "interpreter : ${PYTHON} ($("${PYTHON}" -c 'import platform; print(platform.python_version())'))"
echo "venv        : ${VENV}"

"${PYTHON}" -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --disable-pip-version-check --upgrade pip
"${VENV}/bin/pip" install --quiet --disable-pip-version-check -r "${REQS}"

# Prove the interpreter can actually do the one job it has, rather than
# reporting success because pip exited zero.
UPSTREAM_ROOT="${AEREAD_AGENTICPAY_UPSTREAM_ROOT:-$(cd "${HERE}/../../../.." && pwd)/upstream-agenticpay}"
if [ -d "${UPSTREAM_ROOT}/agenticpay" ]; then
  if "${VENV}/bin/python" - "${UPSTREAM_ROOT}" >/dev/null 2>&1 <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from agenticpay.envs.single_buyer_product_seller.Task1_basic_price_negotiation import (
    Task1BasicPriceNegotiation,
)
sys.exit(0 if Task1BasicPriceNegotiation is not None else 1)
PY
  then
    echo "verified    : upstream Task1BasicPriceNegotiation imports"
  else
    echo "error: the venv was built but cannot import upstream's bilateral environment." >&2
    echo "       Checked upstream root: ${UPSTREAM_ROOT}" >&2
    exit 1
  fi
else
  echo "note        : upstream checkout not found at ${UPSTREAM_ROOT}; skipped the import check"
  echo "              set AEREAD_AGENTICPAY_UPSTREAM_ROOT and re-run to verify"
fi

echo
echo "Export this to make the fidelity tests run instead of skip:"
echo
echo "    export AEREAD_AGENTICPAY_BRIDGE_PYTHON=${VENV}/bin/python"
echo
