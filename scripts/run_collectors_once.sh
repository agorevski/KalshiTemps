#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

args=()
if [[ -n "${KALSHI_TEMPS_DB:-}" ]]; then
  args+=(--db "$KALSHI_TEMPS_DB")
fi

args+=(run-scheduled-collectors)
args+=(--collectors "${KALSHI_TEMPS_COLLECTORS:-all}")
args+=(--lockfile "${KALSHI_TEMPS_SCHEDULER_LOCKFILE:-data/scheduler/collectors.lock}")
args+=(--lock-stale-seconds "${KALSHI_TEMPS_LOCK_STALE_SECONDS:-3600}")
args+=(--timeout "${KALSHI_TEMPS_COLLECTOR_TIMEOUT:-10}")
args+=(--max-attempts "${KALSHI_TEMPS_COLLECTOR_MAX_ATTEMPTS:-1}")
args+=(--metar-station "${KALSHI_TEMPS_METAR_STATION:-KSEA}")

if [[ -n "${KALSHI_TEMPS_NWS_URL:-}" ]]; then
  args+=(--nws-url "$KALSHI_TEMPS_NWS_URL")
fi
if [[ -n "${KALSHI_TEMPS_METAR_URL:-}" ]]; then
  args+=(--metar-url "$KALSHI_TEMPS_METAR_URL")
fi
if [[ "${KALSHI_TEMPS_DRY_RUN:-}" == "1" || "${KALSHI_TEMPS_DRY_RUN:-}" == "true" ]]; then
  args+=(--dry-run)
fi
if [[ -n "${KALSHI_TEMPS_COLLECTOR_TIMEOUTS:-}" ]]; then
  IFS=',' read -r -a timeout_overrides <<< "$KALSHI_TEMPS_COLLECTOR_TIMEOUTS"
  for override in "${timeout_overrides[@]}"; do
    [[ -n "$override" ]] && args+=(--collector-timeout "$override")
  done
fi

python -m kalshi_temps "${args[@]}"
