#!/usr/bin/env bash
#
# Get the newest version. Type:  ./update
#
# A Codespace clones the repository once, when it is created, and never pulls again.
# Reopening one and pressing start serves whatever was current on the day it was made.
# That is what made a new build look identical to the old one, and it is not something
# a person should have to know.
#
# Pulling alone is not enough either. `web/dist` — the built phone app — is not in git;
# it is produced by a build step that previously ran only at creation time. So a pull
# updates the source while the browser keeps being served last week's bundle.
#
# This script does all of it, in the order that matters, and says what it changed.

set -uo pipefail
cd "$(dirname "$0")/.."

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mxx\033[0m %s\n' "$*"; exit 1; }

BEFORE=$(git rev-parse --short=7 HEAD 2>/dev/null || echo unknown)

say "1/5  Fetching the newest code"

# Setting up a Codespace runs the network build, which rewrites the tracked files under
# pipeline/out/ — a timestamp and some reordering. They then show up as a dozen
# "changes you haven't committed", which looks alarming, is not, and blocks a pull the
# moment the same files move upstream.
#
# They are generated. Throw the local copies away; step 4 regenerates them.
if [ -n "$(git status --porcelain -- pipeline/out 2>/dev/null)" ]; then
  say "     Discarding regenerated build reports under pipeline/out/ (they are outputs,"
  say "     not edits — this is normal and nothing is lost)."
  git checkout -- pipeline/out 2>/dev/null || true
fi

# Anything still dirty is a real edit somebody made, and is not ours to discard.
if [ -n "$(git status --porcelain)" ]; then
  warn "You have local edits to these files:"
  git status --porcelain | sed 's/^/       /'
  warn "They are being kept. If the pull is refused because of them, either commit"
  warn "them on a branch of your own or run:  git stash"
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
git pull --ff-only origin "$BRANCH" || die \
  "Could not fast-forward $BRANCH.

     The usual cause is a commit made here that is not on GitHub, which makes this
     copy and the remote diverge. To throw away local commits and match GitHub
     exactly (you will lose them):

         git fetch origin $BRANCH && git reset --hard origin/$BRANCH

     Run 'git status' first if you want to see what would go."

AFTER=$(git rev-parse --short=7 HEAD)
if [ "$BEFORE" = "$AFTER" ]; then
  say "     Already at $AFTER — no new code."
else
  say "     $BEFORE -> $AFTER"
fi

say "2/5  Installing any new Python packages"
pip install --quiet -r requirements.txt || warn "pip reported a problem; continuing."

say "3/5  Rebuilding the phone app"
# ALWAYS rebuild, even when the commit did not move. The whole point of this script is
# that somebody ran it because the app looked wrong, and "I decided it was unnecessary"
# is the least useful thing it could say.
( cd web && npm ci --no-audit --no-fund && npm run build ) \
  || die "The phone app failed to build. The output above says why."

say "4/5  Rebuilding the street network if the code that builds it changed"
NEED_NETWORK=0
if [ "$BEFORE" != "$AFTER" ] && \
   ! git diff --quiet "$BEFORE" "$AFTER" -- pipeline/ api/routing/network.py 2>/dev/null; then
  NEED_NETWORK=1
fi
# Also rebuild if the network on disk predates neighbourhood names, whatever the
# commits say — that is the state that actually breaks mission titles.
if [ -f pipeline/out/*/segments.geojson ] 2>/dev/null; then :; fi
if ! grep -ql '"neighborhood"' pipeline/out/*/segments.geojson 2>/dev/null; then
  NEED_NETWORK=1
fi
if [ "$NEED_NETWORK" = "1" ]; then
  say "     Rebuilding (this is the slow one, ~2 minutes)"
  python3 -m pipeline.sources.fetch || warn "Could not reach the Town's map servers."
  python3 -m pipeline.build.run || die "The street network build failed."
else
  say "     Unchanged — skipping."
fi

say "5/5  Applying any database changes"
if [ -f .codespace-env ]; then set -a; . ./.codespace-env; set +a; fi
alembic upgrade head || warn "Migrations reported a problem."

say "Updated to $AFTER."
echo
echo "    Now start it:  ./go"
echo
echo "    On your phone, the badge in the bottom-right corner should read $AFTER."
echo "    If it reads something else, tap it and choose"
echo "    'Clear cache and load the newest build'."
echo
