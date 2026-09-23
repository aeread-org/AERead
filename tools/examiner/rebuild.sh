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
echo "[2/7] receipt index (sealed attempt dirs on this machine)"
python3 "$T/index_receipts.py" "$T/receipt_index.json" ${ROOTS[@]+"${ROOTS[@]}"}
echo "[3/7] catalog, published grains, run order"
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
echo "[7/7] checks"
python3 "$T/check_build.py" "$OUT"
echo "done: serve with  cd $OUT && python3 -m http.server 8791 --bind 127.0.0.1"
