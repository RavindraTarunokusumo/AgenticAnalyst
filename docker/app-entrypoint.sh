#!/bin/sh
set -eu

case "${APP_PROCESS_MODE:-api}" in
  api | scheduler)
    ;;
  *)
    echo "APP_PROCESS_MODE must be api or scheduler" >&2
    exit 64
    ;;
esac

# Task 6 replaces this readiness placeholder with the ASGI process. Task 5
# starts APScheduler only in scheduler mode; no jobs exist in this image.
touch /tmp/analyst-engine-ready
echo "AnalystEngine container started in ${APP_PROCESS_MODE:-api} mode."

trap 'exit 0' INT TERM
while :; do
  sleep 3600 &
  wait $!
done
