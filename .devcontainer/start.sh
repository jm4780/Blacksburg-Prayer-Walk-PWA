#!/usr/bin/env bash
#
# Starts the app. Runs automatically whenever the Codespace is opened, and can be
# run by hand at any time with:   ./go
#
# Its main job beyond starting the server is making port 8000 *public*. A phone is
# not signed in to the Codespace, so a private port would show it a GitHub login
# page instead of the app — which looks exactly like the app being broken.

set -uo pipefail
cd "$(dirname "$0")/.."

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

if [ -f .codespace-env ]; then
  set -a; . ./.codespace-env; set +a
else
  export BPW_TIER=development
  export BPW_TOKEN_PEPPER="${BPW_TOKEN_PEPPER:-local-development-only}"
fi

if [ ! -f web/dist/index.html ]; then
  warn "The phone app has not been built yet. Running setup first."
  bash .devcontainer/setup.sh || exit 1
fi

# --- staleness checks -------------------------------------------------------
# A Codespace never pulls on its own, and the built phone app is not in git. Both can
# be silently out of date, and a silently out-of-date preview is indistinguishable
# from "the new work didn't happen". Say so, loudly, before serving it.
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
say "Serving branch $BRANCH at commit $(git rev-parse --short=7 HEAD 2>/dev/null || echo unknown)"

if git fetch --quiet origin "$BRANCH" 2>/dev/null; then
  BEHIND=$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)
  if [ "${BEHIND:-0}" -gt 0 ]; then
    warn "This Codespace is $BEHIND commit(s) BEHIND origin/$BRANCH."
    warn "You are about to preview old code. Run  ./update  first."
  fi
fi

# The built bundle is what the phone actually receives. If any source file is newer
# than it, the phone gets the old app no matter how current the checkout is.
if [ -n "$(find web/src web/index.html web/vite.config.ts -newer web/dist/index.html \
           -type f -print -quit 2>/dev/null)" ]; then
  warn "The phone app on disk is older than the source it was built from."
  warn "Rebuilding it now so you are not shown a stale screen."
  ( cd web && npm run build ) || warn "Rebuild failed — serving the previous bundle."
fi

# Make the port reachable from a phone. Best effort: this needs the GitHub CLI and,
# on some organisation accounts, permission to open public ports. If it fails, the
# PORTS tab can do the same thing in two clicks — so say that rather than dying.
if [ -n "${CODESPACE_NAME:-}" ] && command -v gh >/dev/null 2>&1; then
  if gh codespace ports visibility 8000:public -c "$CODESPACE_NAME" >/dev/null 2>&1; then
    say "Port 8000 is public — your phone can reach it."
  else
    warn "Could not set the port to public automatically."
    warn "Open the PORTS tab, right-click port 8000 -> Port Visibility -> Public."
  fi
  echo
  say "Open this on your phone:"
  printf '\n    \033[1;36mhttps://%s-8000.app.github.dev\033[0m\n\n' "$CODESPACE_NAME"
  say "First open it on this computer once, to check it loads."
fi

say "Starting. Press Ctrl+C to stop; run ./go to start it again."
echo
exec python3 -m uvicorn api.app.main:app --host 0.0.0.0 --port 8000
