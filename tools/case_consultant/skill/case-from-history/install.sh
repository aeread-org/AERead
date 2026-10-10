#!/bin/sh
# Install the skill for Claude Code and for Codex. Run from anywhere:  sh install.sh
set -e
here=$(cd "$(dirname "$0")" && pwd)
for root in "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" "${CODEX_HOME:-$HOME/.codex}"; do
  [ -d "$root" ] || continue
  dest="$root/skills/case-from-history"
  rm -rf "$dest" && mkdir -p "$dest" && cp -R "$here/SKILL.md" "$here/scripts" "$here/references" "$dest/"
  echo "installed: $dest"
done
