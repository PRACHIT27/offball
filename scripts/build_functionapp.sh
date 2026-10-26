#!/usr/bin/env bash
# Assemble the normalizer Function App package: function_app.py at the root plus the ingest
# package (without the functionapp folder itself). Output: build/functionapp/
set -euo pipefail
cd "$(dirname "$0")/.."
out=build/functionapp
rm -rf "$out" && mkdir -p "$out"
cp ingest/functionapp/{function_app.py,host.json,requirements.txt} "$out"/
rsync -a --exclude functionapp --exclude __pycache__ ingest "$out"/
echo "built $out"
