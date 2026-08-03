# Pilot deployment runbook

Everything needed to stand up, verify, back up and roll back the pilot.
**No secret appears in this file or anywhere in version control.**

Target: canonical network `v1.2` / `bbg-net-v1.2-e1284e6001ff54f5`, engine `2.1.1`.

---

## 1. Environment variables

Set these on the host — a systemd unit's `EnvironmentFile`, a container secret, or
your platform's secret store. Never a committed `.env`.

| Variable | Pilot value | Notes |
|---|---|---|
| `BPW_TIER` | `pilot` | Development / pilot / public. Controls startup warnings. |
| `BPW_ACCESS_MODE` | `authenticated` or `invite` | **The G1 control.** Who may see route and map geometry. |
| `BPW_INVITE_CODE` | *(a phrase)* | Required only when `BPW_ACCESS_MODE=invite`. |
| `BPW_TOKEN_PEPPER` | *(48-byte secret)* | **Required.** Mixed into every participant token hash. |
| `BPW_DATABASE_URL` | `postgresql+psycopg://…` | SQLite works but is not recommended beyond one host. |
| `BPW_SNAPSHOT_DATE` | `2026-08-03` | Which canonical network build to serve. |
| `BPW_CORS_ORIGINS` | your web origin | Comma-separated. |
| `BPW_PUBLIC_GEOMETRY_ENABLED` | *(unset)* | Legacy escape hatch; prefer `BPW_ACCESS_MODE`. |

Generate the pepper:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Rotating `BPW_TOKEN_PEPPER` invalidates every remembered device.** Participants are
not locked out — they sign in again with the same email and land on the same record —
but it is a visible event, so rotate deliberately rather than casually.

### Changing the access mode later

G1 is deployment configuration, not architecture. `api/app/deps.may_see_geometry` is
the only place the mode is read, so moving to lightweight public participant access is:

```bash
BPW_ACCESS_MODE=public        # restart
```

No route handler, schema, client build or database change. The identity model is
identical in all three modes — name, email, remembered device, no password. Startup
prints a warning naming G1 whenever geometry is public, so the state is never silent.

---

## 2. Database

```bash
createdb blacksburg_prayer_walk          # or your provider's equivalent
export BPW_DATABASE_URL="postgresql+psycopg://USER:PASS@HOST/blacksburg_prayer_walk"
alembic upgrade head
```

`alembic upgrade head` is the only supported way to create or migrate the schema.
`init_db()` exists for local convenience; it cannot migrate an existing database.

Verify:

```bash
alembic current          # should print the head revision
alembic check            # "No new upgrade operations detected."
```

## 3. Geographic pipeline

The GIS data is an internal application dependency and is **not** in the repository.
Run this on the host, or run it elsewhere and copy `pipeline/out/<date>/` across.

```bash
python3 -m pipeline.sources.fetch          # ~1 min, needs outbound HTTPS to the town's ArcGIS
python3 -m pipeline.build.run              # ~2 min
python3 -m pipeline.build.crc_review
python3 -m pipeline.build.connector_candidates
python3 -m api.routing.freeze              # prints the network id and the gates
```

The freeze step must print `bbg-net-v1.2-e1284e6001ff54f5`. **A different id means a
different network** — the source data changed underneath you. Do not deploy without
looking at what moved.

## 4. Application

```bash
pip install fastapi 'uvicorn[standard]' sqlalchemy pydantic pydantic-settings alembic psycopg
cd web && npm ci && npm run build && cd ..
uvicorn api.app.main:app --host 127.0.0.1 --port 8000 --workers 2
```

Put TLS in front of it. The PWA requires HTTPS for geolocation and service-worker
registration — over plain HTTP the location request silently fails and the app cannot
be installed.

The built frontend at `web/dist` is served by the API process, so there is one thing
to run. For a CDN, serve `web/dist` statically and point it at the API origin.

## 5. First administrator

There is deliberately **no API** for granting administrator rights: an application that
can promote itself over HTTP is one request away from anyone else doing so. Sign up
through the app, then:

```sql
UPDATE participants SET is_admin = true WHERE email_normalized = 'you@example.com';
```

## 6. Health checks

```bash
curl -s https://HOST/api/health | python3 -m json.tool
```

Green looks like:

| Field | Expected |
|---|---|
| `status` | `ok` |
| `network_version` | `v1.2` |
| `network_id` | `bbg-net-v1.2-e1284e6001ff54f5` |
| `engine_version` | `2.1.1` |
| `warnings` | `[]` |
| `public_geometry_enabled` | `false` |

Any entry in `warnings` is a real misconfiguration — an unset pepper, an invite mode
with no code, geometry gone public. Do not start a pilot with a non-empty `warnings`.

Then, end to end:

```bash
curl -s https://HOST/api/progress/metrics | python3 -m json.tool   # 200, aggregate only
curl -s -o /dev/null -w '%{http_code}\n' https://HOST/api/progress/map   # expect 403
```

A `200` on that last line while `BPW_ACCESS_MODE=authenticated` means the gate is not
working. Stop and investigate before inviting anyone.

## 7. Backups

Two things need backing up, and only one of them is precious.

| What | Why | How |
|---|---|---|
| **The database** | Participants, walks, completions, feedback. Irreplaceable. | `pg_dump` nightly, keep 30 days, off-host. |
| `pipeline/out/<date>/` | The canonical network. Reproducible, but a rebuild may not be byte-identical if the town has edited its data. | Copy once at deploy; treat as an immutable artifact. |

```bash
pg_dump --format=custom "$BPW_DATABASE_URL" > bpw-$(date +%F).dump
```

Restore:

```bash
pg_restore --clean --if-exists --dbname "$BPW_DATABASE_URL" bpw-2026-08-03.dump
```

Nothing else is stateful. No uploads, no session store, no cache.

**Test the restore before the pilot starts**, into a scratch database. A backup nobody
has restored is a hope.

## 8. Rollback

Ordered by blast radius, smallest first.

**Bad frontend build** — the API is unaffected.
```bash
git checkout <previous-tag> -- web/ && cd web && npm ci && npm run build
```

**Bad application code, schema unchanged** — deploy the previous commit and restart.

**Bad migration.** Every migration has a `downgrade()`:
```bash
alembic downgrade -1
```
Then deploy the matching application version. Verify with `alembic current`.

**Bad canonical network.** The network is not in the database; it is the files under
`pipeline/out/<date>/`. Roll back by pointing at the previous build:
```bash
BPW_SNAPSHOT_DATE=<previous-date>    # restart
```
Stored walks record the `network_id` they were computed under, so completions taken
against the newer network remain interpretable — they are not silently reattributed.
Segment ids are stable across rebuilds of the same source data, so completions carry
over; if the town's source data has changed materially, check
`review/corrections.json` before assuming that.

**Data loss.** Restore the newest dump, then replay nothing — there is no event log to
replay, and walks recorded after the dump are lost. That is the honest cost of a
nightly cadence and is acceptable at pilot scale; raise the frequency before wider use.

**Full stop.** Set `BPW_ACCESS_MODE=invite` with a code nobody has. Existing
participants keep their walks; nobody new can join. This is the safest pause — it
leaves data intact and needs no deploy.

---

## 9. Pre-flight checklist

- [ ] `alembic current` matches the deployed code
- [ ] `alembic check` reports no pending changes
- [ ] `/api/health` returns `warnings: []`
- [ ] `/api/health` reports `bbg-net-v1.2-e1284e6001ff54f5` and engine `2.1.1`
- [ ] `/api/progress/map` returns **403** unauthenticated
- [ ] `/api/progress/metrics` returns **200** and contains no coordinates
- [ ] `BPW_TOKEN_PEPPER` set and not the development value
- [ ] TLS terminating in front; the site loads over HTTPS
- [ ] The PWA installs on a real phone (Add to Home Screen)
- [ ] One administrator promoted, and the Pilot tab loads
- [ ] A backup has been taken **and restored** into a scratch database
- [ ] `python3 -m pytest` green on the deployed commit
