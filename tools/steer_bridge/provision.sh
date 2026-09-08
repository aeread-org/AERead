#!/usr/bin/env bash
#
# Provision the pandas-capable interpreter the steer adapter's Gate-1
# importer uses to unpickle the pinned upstream STEER corpus.
#
# The project's own venv (Python 3.11) deliberately does not carry pandas --
# see docs/steer_adapter_spec.md's Governing facts ("a missing-package gap,
# not a Python-version gap"). Rather than installing pandas into that venv,
# this script builds a small, separate venv that ONLY unpickles the corpus
# and flattens it to plain JSON; nothing downstream of Gate 1 needs pandas.
#
# Without this interpreter the Gate-1 corpus-admission tests do not fail --
# they skip. A silent skip on the tests that carry the schema-drift and
# admission-count regression guards is the failure mode this script exists
# to prevent (see tools/steer_bridge/README.md).
#
# Usage:
#   tools/steer_bridge/provision.sh [venv-path]
#
# Then export what it prints, or add it to your shell profile.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${1:-${HOME}/.cache/aeread/steer-bridge-venv}"
REQS="${HERE}/requirements.txt"

find_python() {
  for candidate in python3.12 python3.13 python3; do
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
if "${VENV}/bin/python" -c 'import pandas; assert pandas.__version__ == "3.0.5"'; then
  echo "verified    : pandas 3.0.5 importable"
else
  echo "error: the venv was built but cannot import the pinned pandas version." >&2
  exit 1
fi

echo
echo "Export this to make the Gate-1 corpus tests run instead of skip:"
echo
echo "    export AEREAD_STEER_BRIDGE_PYTHON=${VENV}/bin/python"
echo
