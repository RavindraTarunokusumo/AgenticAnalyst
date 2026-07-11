#!/bin/sh
set -eu

: "${SEARXNG_SECRET:?SEARXNG_SECRET must be provided through the environment}"

if [ ! -f /etc/searxng/settings.yml ]; then
  umask 077
  python - <<'PY'
import os
from pathlib import Path

source = Path("/bootstrap/settings.yml")
target = Path("/etc/searxng/settings.yml")
target.write_text(
    source.read_text(encoding="utf-8").replace("${SEARXNG_SECRET}", os.environ["SEARXNG_SECRET"]),
    encoding="utf-8",
)
PY
fi

exec /usr/local/searxng/dockerfiles/docker-entrypoint.sh python -m searx.webapp
