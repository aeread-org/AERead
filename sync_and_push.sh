#!/bin/sh
# Copy the paper's working draft from output/pdf into this branch, then commit and push it.
# Usage: ./sync_and_push.sh "commit message"   (run after every rebuild of the draft)
set -eu
SRC=/Users/chenyusu/AERead/output/pdf/aeread_working_draft_20261018_v15
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE" || exit 1
[ "$(git branch --show-current)" = "paper/working-draft" ] || { echo "not on paper/working-draft" >&2; exit 1; }
[ -f "$SRC/build.py" ] || { echo "no draft at $SRC" >&2; exit 1; }
# The version printed under the title must go up on every push, so a reader can tell drafts apart.
python3 - "$SRC/source/version.json" <<'PY' || exit 1
import json, subprocess, sys
new = json.load(open(sys.argv[1]))["version"]
try:
    old = json.loads(subprocess.run(["git", "show", "HEAD:source/version.json"], capture_output=True, check=True, text=True).stdout)["version"]
except (subprocess.CalledProcessError, ValueError, KeyError):
    old = None
key = lambda v: tuple(int(x) for x in v.split("."))
if old is not None and key(new) <= key(old):
    sys.exit(f"source/version.json is {new}, not above the last pushed {old}: raise it by one, rebuild, then push")
PY
rsync -a --delete --exclude '.git' --exclude 'sync_and_push.sh' --exclude '.gitignore' --exclude 'BRANCH.md' \
  --exclude '*.zip' --exclude '*.html' --exclude '__pycache__' --exclude '.DS_Store' "$SRC"/ "$HERE"/
git add -A
if git diff --cached --quiet; then echo "nothing changed"; exit 0; fi
git commit -q -m "$1"
git push -q origin paper/working-draft
git log --oneline -1
