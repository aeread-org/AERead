#!/usr/bin/env bash
#
# Provision the interpreter the negarena adapter uses to talk to upstream
# NegotiationArena.
#
# Unlike tau3_retail's bridge, the blocker here is not a Python-version floor
# (upstream's pyproject.toml declares no [project] table at all) -- it is
# that importing ANY upstream negarena module, including the "pure"
# game-object arithmetic, transitively imports `openai`+`anthropic`
# (negotiationarena/utils.py imports negotiationarena.agents at module
# scope; see docs/negarena_adapter_spec.md's governing facts). The project's
# own venv must never have those installed, so this script builds a
# dedicated, isolated venv instead.
#
# Without this interpreter the upstream-fidelity tests do not fail -- they
# skip. See tools/tau2_bridge/provision.sh's README for why that is the
# failure mode worth guarding against.
#
# Usage:
#   tools/negarena_bridge/provision.sh [venv-path]
#
# Then export what it prints, or add it to your shell profile.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The sibling upstream checkout (`upstream-negarena`) always lives next to
# the top-level "AERead" directory itself -- not next to whichever checkout
# ${HERE} happens to be inside. A plain, fixed-count `../../../..` from
# `tools/negarena_bridge` cannot express that: it resolves correctly from
# a main checkout (`AERead/tools/negarena_bridge`, two levels below
# "AERead") but lands two levels too high from inside a linked git worktree
# (`AERead/.worktrees/<name>/tools/negarena_bridge`, four levels below), so
# it silently produced `AERead/upstream-negarena` -- a path that does not
# exist -- and the "not found" branch below then skipped verification
# entirely rather than failing (docs/negarena_codex_triage.md Finding 5).
# Walking up by name instead of by a fixed depth resolves correctly from
# either location.
default_upstream_root() {
  local walk="${1}"
  while [ "$(basename "${walk}")" != "AERead" ] && [ "${walk}" != "/" ]; do
    walk="$(dirname "${walk}")"
  done
  if [ "${walk}" = "/" ]; then
    echo "error: could not find an ancestor directory named 'AERead' above ${1}" >&2
    return 1
  fi
  echo "$(dirname "${walk}")/upstream-negarena"
}

# Test-only introspection hook: print the resolved default and exit, without
# creating a venv or touching the network -- lets
# tests/test_negarena_provisioning.py verify the path-resolution logic in
# isolation (never by actually provisioning). Note this always calls
# `default_upstream_root` directly, ignoring any
# `AEREAD_NEGARENA_UPSTREAM_ROOT` override -- it exercises the helper
# function alone, not the real assignment below.
if [ "${1:-}" = "--print-default-upstream-root" ]; then
  default_upstream_root "${HERE}"
  exit 0
fi

# The real provisioning run's own upstream-root resolution, computed once,
# here -- not reimplemented anywhere else in this script. Previously this
# was computed a second time, further down, right before the import check;
# a test suite that only ever drove `--print-default-upstream-root` above
# (which never reaches this assignment) could not tell a regression in *this*
# expression apart from correct behavior, since reverting only this line
# left every existing test green while normal provisioning broke again
# (docs/negarena_codex_triage.md Finding 5; docs/negarena_fix_verification.md
# on the gap in this fix's own regression coverage). Resolving it once, up
# here, and reusing the same variable both for the introspection flag below
# and for the real import-check gate further down closes that gap: any
# revert of this expression now breaks both identically.
if ! UPSTREAM_ROOT="${AEREAD_NEGARENA_UPSTREAM_ROOT:-$(default_upstream_root "${HERE}")}"; then
  exit 1
fi

# Test-only introspection hook: print the value the real provisioning run
# below actually resolves and uses -- honoring an
# `AEREAD_NEGARENA_UPSTREAM_ROOT` override exactly like the real run does,
# unlike `--print-default-upstream-root` above -- and exit before creating a
# venv or touching the network.
if [ "${1:-}" = "--print-resolved-upstream-root" ]; then
  echo "${UPSTREAM_ROOT}"
  exit 0
fi

VENV="${1:-/Users/sunzeyu/Documents/econ benchmark/bridges/negarena-venv}"
REQS="${HERE}/requirements.txt"

find_python() {
  for candidate in python3.12 python3.11 python3.13 python3; do
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

# Installed one line at a time, not as one `pip install -r`: anthropic==0.5.0
# (old-API pin, needed for the legacy HUMAN_PROMPT/AI_PROMPT names claude.py
# imports) declares `anyio<4`, while a modern openai (needed for the
# `from openai import OpenAI` client-class import chatgpt.py actually uses at
# this pin) pulls in `anyio>=4`. Resolving both together in one pip call is
# a hard ResolutionImpossible; installing them as two calls only leaves a
# non-fatal warning, and this bridge never imports anything that exercises
# the conflicting anyio behavior (no network call, no async client use).
while IFS= read -r requirement; do
  case "$requirement" in
    ""|\#*) continue ;;
  esac
  "${VENV}/bin/pip" install --quiet --disable-pip-version-check "${requirement}"
done < "${REQS}"

# Prove the interpreter can actually do the one job it has, rather than
# reporting success because pip exited zero. UPSTREAM_ROOT was already
# resolved above -- the same value --print-resolved-upstream-root reports.
if [ -d "${UPSTREAM_ROOT}/negotiationarena" ]; then
  if "${VENV}/bin/python" - "${UPSTREAM_ROOT}" >/dev/null 2>&1 <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from games.buy_sell_game.game import BuySellGame, BuySellGameDefaultParser
from negotiationarena.game_objects.resource import Resources
from negotiationarena.game_objects.trade import Trade
from negotiationarena.game_objects.valuation import Valuation
from negotiationarena.game_objects.goal import BuyerGoal, SellerGoal, UltimatumGoal
# games/ultimatum/interface.py references a name upstream's own module never
# defines at this pin (see docs/negarena_adapter_spec.md's "Correction" note
# and ledger_entries/negarena.md); negarena_bridge_driver.py carries the same
# alias at runtime, never touching the read-only upstream checkout.
import negotiationarena.agent_message as _agent_message
_agent_message.AgentMessageInterface = _agent_message.AgentMessage
from games.ultimatum.game import MultiTurnUltimatumGame
from games.ultimatum.interface import UltimatumGameDefaultParser
sys.exit(0)
PY
  then
    echo "verified    : upstream buy_sell/ultimatum game classes import cleanly"
  else
    echo "error: the venv was built but cannot import upstream's game classes." >&2
    echo "       Checked upstream root: ${UPSTREAM_ROOT}" >&2
    exit 1
  fi
else
  echo "note        : upstream checkout not found at ${UPSTREAM_ROOT}; skipped the import check"
  echo "              set AEREAD_NEGARENA_UPSTREAM_ROOT and re-run to verify"
fi

echo
echo "Export this to make the fidelity tests run instead of skip:"
echo
echo "    export AEREAD_NEGARENA_BRIDGE_PYTHON=${VENV}/bin/python"
echo
