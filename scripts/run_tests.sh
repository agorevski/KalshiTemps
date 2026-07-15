#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

python -m compileall -q src tests
python -m pytest "$@"
