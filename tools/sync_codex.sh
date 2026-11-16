#!/usr/bin/env bash
# Assemble the self-contained Codex skill folder from the shared toolkit.
# Run from the repo root before committing; never edit codex/floorplan-to-3d/ by hand.
set -eu
OUT=codex/floorplan-to-3d
rm -rf "$OUT"; mkdir -p "$OUT"
cp codex-src/SKILL.md "$OUT/"
cp -r codex-src/agents scripts assets references "$OUT/"
find "$OUT" -name __pycache__ -prune -exec rm -rf {} +
echo "synced $OUT"
