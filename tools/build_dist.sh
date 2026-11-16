#!/usr/bin/env bash
# Build both upload archives from the shared toolkit. Run from the repo root.
set -eu
tools/sync_codex.sh
rm -rf dist build && mkdir -p dist build/plugin/skills
# 1) standalone skill ZIP (ChatGPT: Skills → Create → Upload)
(cd codex && zip -qr ../dist/floorplan-to-3d-skill.zip floorplan-to-3d -x '*/__pycache__/*')
# 2) plugin ZIP (ChatGPT / Codex plugin upload): manifest + skills/ at the archive root
cp -r plugin-src/.codex-plugin build/plugin/
cp -r codex/floorplan-to-3d build/plugin/skills/
(cd build/plugin && zip -qr ../../dist/floorplan-to-3d-plugin.zip .codex-plugin skills -x '*/__pycache__/*')
rm -rf build
echo "built dist/floorplan-to-3d-skill.zip and dist/floorplan-to-3d-plugin.zip"
