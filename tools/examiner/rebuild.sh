#!/usr/bin/env bash
# Rebuild the AERead examiner from an AERead checkout.
#   tools/examiner/rebuild.sh <AERead checkout> [output dir = tools/examiner/build] [run root ...]
# Run roots default to ~/AERead* plus every worktree git registers for them (session worktrees under /private/tmp included). PY=<python> overrides the interpreter
# (default: the checkout's .venv, which has the family packages' dependencies).
set -euo pipefail
WT=$(cd "${1:?usage: rebuild.sh <AERead checkout> [out] [run roots...]}" && pwd)
T=$(cd "$(dirname "$0")" && pwd)
OUT=${2:-$T/build}; mkdir -p "$OUT/data"; OUT=$(cd "$OUT" && pwd)
cp "$T/page/index.html" "$OUT/index.html"   # the page source lives in page/; the build folder is disposable
shift; [ $# -gt 0 ] && shift; ROOTS=("$@")
PY=${PY:-$WT/.venv/bin/python}; [ -x "$PY" ] || PY=$HOME/AERead/.venv/bin/python; [ -x "$PY" ] || PY=python3
echo "[1/7] phase graphs declared by the plugins (static + live)"
PYTHONPATH=$WT/src "$PY" "$T/extract_phase_graphs.py" "$WT" "$T/phase_graphs.json" >/dev/null || echo "  static extraction failed; keeping the previous phase_graphs.json"
PYTHONPATH=$WT/src "$PY" "$T/dynamic_phase_graphs.py" "$WT" "$T/phase_graphs_live.json" >/dev/null || echo "  live extraction failed; keeping the previous phase_graphs_live.json"
# Plugins that exist only on an extra checkout's branch (a new family not yet on the primary's branch) get their
# graphs from that checkout; the primary's own graphs always win.
for X in ${AEREAD_EXAMINER_EXTRA_CHECKOUTS//:/ }; do
  [ -d "$X/src/aeread_families" ] || continue
  XPY=$X/.venv/bin/python; [ -x "$XPY" ] || XPY=$PY
  PYTHONPATH=$X/src "$XPY" "$T/dynamic_phase_graphs.py" "$X" "$OUT/phase_graphs_extra.json" >/dev/null 2>&1 || continue
  python3 - "$T/phase_graphs_live.json" "$OUT/phase_graphs_extra.json" <<'PYEOF'
import json, sys
main, extra = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
added = [k for k, v in extra.items() if v.get("variants") and not (main.get(k) or {}).get("variants")]
for k in added:
    main[k] = extra[k]
json.dump(main, open(sys.argv[1], "w"), indent=1, default=str)
print("  graphs from an extra checkout:", ", ".join(added) or "none new")
PYEOF
done
echo "[2/7] receipt index (sealed attempt dirs on this machine)"
python3 "$T/index_receipts.py" "$T/receipt_index.json" ${ROOTS[@]+"${ROOTS[@]}"}
echo "[3/7] catalog, published grains, run order"
# the lens step restores a bundle's step grain from here when its sealed logs were deleted since the last build
[ -f "$OUT/data/catalog.json" ] && cp "$OUT/data/catalog.json" "$OUT/data/.catalog.previous.json" || true
PYTHONPATH=$WT/src "$PY" "$T/build_general_examiner.py" "$WT" "$OUT" | tail -2
mkdir -p "$OUT/data/lens"
if [ -d "$WT/runs/housing_lemons_refusal_pilot_v1" ]; then
  echo "[4/7] housing lemons narrated lens (run root present)"
  PYTHONPATH=$WT/src "$PY" "$T/build_examiner_data.py" "$WT" "$OUT/data/lens/housing_lemons_refusal_pilot_v1.json" | tail -1 || echo "  lemons exporter failed; the generic lens will be used"
else
  echo "[4/7] housing lemons run root not present; keeping any existing narrated lens, else the generic lens applies"
fi
echo "[5/7] full-detail lenses + trajectories synthesized from sealed logs"
python3 "$T/build_general_lens.py" "$OUT" "$WT" "$T/receipt_index.json" | tail -1
echo "[6/7] quantitative results per bundle (tables, intervals, headline numbers)"
python3 "$T/build_results.py" "$OUT" "$WT"
echo "[6b] case cards: family cards and their checks evaluated per cell"
python3 "$T/build_case_cards.py" "$OUT" "$WT" "$T/receipt_index.json" || echo "  case cards failed; the page shows none"
echo "[6d] model comparisons: every case two or more models played, as cells with their strata"
python3 "$T/build_model_comparisons.py" "$OUT" "$WT" || echo "  model comparisons failed; the page shows none"
# opt-in: the owner has not released the StarCraft prototype to the examiner yet (2026-09-25)
SC=${AEREAD_EXAMINER_STARCRAFT_RUNS:-}
if [ -n "$SC" ] && [ -d "$SC" ]; then
  echo "[6c] StarCraft prototype matches (local runs, not AERead evidence)"
  python3 "$T/build_starcraft.py" "$OUT" "$SC" || echo "  starcraft build failed; the page shows none"
fi
echo "[7/7] checks"
python3 "$T/check_build.py" "$OUT"
echo "done: serve with  cd $OUT && python3 -m http.server 8791 --bind 127.0.0.1"
