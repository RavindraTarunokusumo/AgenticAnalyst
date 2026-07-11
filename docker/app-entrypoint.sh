#!/bin/sh
set -eu

MODE="${APP_PROCESS_MODE:-api}"

case "$MODE" in
  api | scheduler)
    ;;
  *)
    echo "APP_PROCESS_MODE must be api or scheduler" >&2
    exit 64
    ;;
esac

touch /tmp/analyst-engine-ready
echo "AnalystEngine starting in ${MODE} mode."

if [ "$MODE" = "api" ]; then
    exec python -m analyst_engine.main
else
    exec python -m analyst_engine.main
fi

