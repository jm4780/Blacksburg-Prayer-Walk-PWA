#!/usr/bin/env bash
# Runs every time the Codespace is opened. Starts the database, then the app.
#
# One process serves everything on port 8000: the app, the map archive and the
# API. A phone has no localhost of ours, so every extra port would be another
# thing to expose and another thing to go wrong.
set -euo pipefail
cd "$(dirname "$0")/../.."

PGVER="$(ls /usr/lib/postgresql | sort -n | tail -1)"
sudo pg_ctlcluster "$PGVER" main start 2>/dev/null || true
until pg_isready -q -h 127.0.0.1; do sleep 1; done

# If the app was never built (a Codespace rebuilt without setup), build it now
# rather than serving a 404 and looking broken.
if [ ! -f rebuild/web/dist/index.html ]; then
  (cd rebuild/web && npm run build)
fi

printf '\n\033[1m==> Prayer Walk is starting on port 8000\033[0m\n'
printf 'Open the PORTS tab, right-click port 8000, Port Visibility > Public,\n'
printf 'then copy the address and open it on your phone.\n\n'

cd rebuild
exec python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000
