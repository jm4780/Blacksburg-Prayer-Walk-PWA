# Blacksburg Prayer Walk PWA

A mobile-first Progressive Web App that helps people systematically prayer-walk every
eligible public street and major trail in the Town of Blacksburg, Virginia.

**Core experience:** Open the app and see how far the town has come, on the town's own
map. Say how much time you have. Get a specific walk, with directions to where it
starts. Pray while walking. Confirm the streets covered. Watch the town fill in.

## Project status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Geographic data audit + technical plan | ✅ Complete |
| 2a | Schema inspection + canonical network build | ✅ Complete |
| 2a.1 | Review, normalize, freeze candidate network | ✅ Complete |
| 2b | Routing prototype | ✅ Complete |
| 2b.1 | Routing corrections + integration readiness | ✅ Complete |
| 3 | Functional PWA integration (vertical slice) | ✅ Complete |
| 3.1 | Pilot deployment + campus validation | ✅ Complete |
| 3.5 | Product realignment: real map, time slider, mission recommendations | ✅ Complete |
| 3.6 | Dashboard rebuilt from the approved visual direction ("Mission control") | ✅ Complete |
| 4 | Pilot (3–5 people) | **GO** — **public release still blocked on licensing gate G1** |

**Canonical network `v1.3` · `bbg-net-v1.3-e1284e6001ff54f5` · routing engine `2.1.1`**

v1.3 adds Town neighbourhood names to required segments. The content checksum is
unchanged from v1.2 because neighbourhood is presentation only — no geometry, no
obligation and no denominator moved, and v1.2 routes still replay.

145.588 required miles (123.807 street · 10.423 trail · 11.359 campus) across 9 valid
routing components, with 11,024 households associated to required coverage.

## Trying it on a phone

No setup, nothing to install: **[docs/16-try-it-on-your-phone.md](docs/16-try-it-on-your-phone.md)**.
Click a button on GitHub, wait five minutes, open the link on your phone.

## Running it locally

```bash
cp .env.example .env          # fill in BPW_TOKEN_PEPPER
pip install fastapi 'uvicorn[standard]' sqlalchemy pydantic pydantic-settings alembic
cd web && npm install && npm run build && cd ..
alembic upgrade head
uvicorn api.app.main:app --reload          # http://127.0.0.1:8000
```

The canonical network is rebuilt from source snapshots — neither is committed, see
`.gitignore`:

```bash
python3 -m pipeline.sources.fetch
python3 -m pipeline.build.run
python3 -m pipeline.build.crc_review
python3 -m api.routing.freeze
```

Tests:

```bash
python3 -m pytest                                  # 132 backend tests
cd web && npm test                                 # 16 component tests
cd web && node e2e/slice.mjs                       # 95 end-to-end assertions
cd web && node e2e/verify-build.mjs                # 13 build-identity checks
cd web && node e2e/admin.mjs <admin-token>         # 12 admin-interface checks

# The admin token cannot be granted over HTTP by design. Mint one before starting
# the server, against the same database it will use:
python3 web/e2e/seed_admin.py
```

## Layout

```
pipeline/    fetch -> normalize -> split -> classify -> connect -> households -> report
api/routing/ the routing engine (cluster-first -> GRASP -> local search) and
             mission discovery, both domain-neutral — no prayer concepts below here
api/app/     FastAPI: identity, missions, route generation, walks, reservations,
             progress, admin. Every prayer-specific word in the product lives here.
web/         React + TypeScript + Vite PWA, mobile-first, MapLibre GL
docs/        every decision, with the evidence for it
```

## Documents

- [`docs/00-product-spec.md`](docs/00-product-spec.md) — the V1 product and routing spec.
- [`docs/01-data-audit.md`](docs/01-data-audit.md) — Phase 1 data audit, corrected against live GIS.
- [`docs/02-technical-plan.md`](docs/02-technical-plan.md) — architecture and build sequence.
- [`docs/03-decisions.md`](docs/03-decisions.md) — decision log. **D1**: the Virginia Tech campus is included. **D1b/D2** settled at Phase 3.
- [`docs/04-schema-inspection.md`](docs/04-schema-inspection.md) — field-level inspection of every source layer.
- [`docs/05-licensing-status.md`](docs/05-licensing-status.md) — **release gate G1, unresolved.**
- [`docs/06-household-methodology.md`](docs/06-household-methodology.md) — how households are counted.
- [`docs/07-vt-campus-coverage.md`](docs/07-vt-campus-coverage.md) — the campus data gap.
- [`docs/09-phase-2a1-freeze.md`](docs/09-phase-2a1-freeze.md) — connector classification and campus normalization.
- [`docs/10-routing-approach-evaluation.md`](docs/10-routing-approach-evaluation.md) — ten algorithms scored before any was built.
- [`docs/12-phase-2b1-corrections.md`](docs/12-phase-2b1-corrections.md) — repeat penalty, multi-component routing.
- [`docs/13-phase-3-integration.md`](docs/13-phase-3-integration.md) — network v1.2, the vertical slice, privacy, deployment tiers.
- [`docs/14-phase-3-1-pilot.md`](docs/14-phase-3-1-pilot.md) — campus validation, connector review, pilot plan, go/no-go.
- [`docs/15-pilot-deployment.md`](docs/15-pilot-deployment.md) — the deployment runbook: environment, migrations, health checks, backup, rollback.
- [`docs/16-try-it-on-your-phone.md`](docs/16-try-it-on-your-phone.md) — no-experience-needed guide to trying it on a phone via GitHub Codespaces.
- [`docs/17-mission-planning-review.md`](docs/17-mission-planning-review.md) — engineering review of the mission-planning realignment.
- [`docs/18-phase-3-5-mission-build.md`](docs/18-phase-3-5-mission-build.md) — the real map, the time slider, mission recommendations, before/after screenshots, known limitations.
- [`docs/19-dashboard-mission-control.md`](docs/19-dashboard-mission-control.md) — **current**: the Dashboard rebuilt from the approved design, the town map absorbed into it, and the follow-ups it created.

## Two things to know before deploying

**Licensing.** No Town of Blacksburg dataset publishes any reuse licence, so route and
map geometry is served only to authenticated participants. This is *deployment
configuration*, not architecture: `BPW_ACCESS_MODE` takes `open_read` (default since
Phase 3.5), `authenticated`, `invite`, or `public`, and `api/app/deps.may_see_geometry`
is the only place it is read. Changing modes is one environment variable and a restart
— no API, schema or client change.

The Phase 3.5 default serves the progress map to anonymous readers so the dashboard
works before anybody signs up. **That is publication under G1.** For a public launch
before G1 is resolved, set `BPW_ACCESS_MODE=authenticated`. The server logs a warning
at startup whenever geometry is anonymously readable.

**GIS data is an internal dependency, not a redistributable asset.** Source snapshots,
derived geometry and address data are fetched and built by the pipeline and are never
committed. Run the pipeline on the deployment host.

**Privacy.** No residential address, household coordinate or participant location is
stored anywhere in this application. The browser holds an opaque token; the server
holds its hash. `tests/test_privacy.py` proves real Blacksburg addresses appear in no
API response.

## Guiding principle

> Does this make it easier for someone to prayer-walk another street today?

If not, it goes in the future-feature backlog.
