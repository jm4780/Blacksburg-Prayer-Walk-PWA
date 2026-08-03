#!/usr/bin/env bash
#
# One-time setup. Runs automatically when a Codespace is created.
#
# Everything here is also what a human would do by hand — nothing is Codespace-only,
# so if this script works, the instructions in docs/15-pilot-deployment.md work too.
#
# Deliberately noisy. This takes several minutes and silence during a long wait is
# indistinguishable from being broken.

set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m!!\033[0m %s\n' "$*"; }

say "1/5  Installing the Python parts (about a minute)"
# Upgrading pip is a nicety, not a requirement, and it fails outright on images
# where pip was installed by the system package manager. Never let it stop setup.
pip install --quiet --upgrade pip 2>/dev/null || true
pip install --quiet -r requirements.txt

say "2/5  Building the phone app"
cd web
npm ci --no-audit --no-fund
npm run build
cd ..

say "3/5  Downloading Blacksburg's map data from the Town's servers"
# Not stored in the repository: it is the Town's data, not ours to redistribute.
# Fetched fresh here, which is also how a real deployment gets it.
if python3 -m pipeline.sources.fetch; then
  say "     Map data downloaded."
else
  warn "Could not reach the Town of Blacksburg's map servers."
  warn "The app will start but cannot generate routes without this."
  warn "Try again later with:  python3 -m pipeline.sources.fetch"
  exit 0
fi

say "4/5  Building the street network (this is the slow one, ~2 minutes)"
python3 -m pipeline.build.run

say "5/5  Setting up the database"
# A secret used to protect sign-in tokens. Generated here and kept out of git.
# Persisted so that restarting does not sign everybody out.
if [ ! -f .codespace-env ]; then
  {
    echo "BPW_TIER=development"
    echo "BPW_TOKEN_PEPPER=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  } > .codespace-env
fi
# shellcheck disable=SC1091
set -a; . ./.codespace-env; set +a
alembic upgrade head

say "Setup finished."
echo
echo "    The app will start on its own. Look for the link in the terminal below,"
echo "    or open the PORTS tab and copy the address next to port 8000."
echo
