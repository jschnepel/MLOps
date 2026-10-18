#!/usr/bin/env bash
set -euo pipefail
python -m compileall -q src integrations scripts
python -m pytest -q
PYTHONPATH=src python -m operations_copilot.cli
node --check src/operations_copilot/web/app.js
