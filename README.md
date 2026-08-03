# Blacksburg Prayer Walk PWA

A mobile-first Progressive Web App that helps people systematically prayer-walk every
eligible public street and major trail in the Town of Blacksburg, Virginia.

**Core experience:** Open the app. Generate a route. Pray while walking. Confirm the
streets covered. Watch the town gradually fill in.

## Project status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Geographic data audit + technical plan | ✅ Complete |
| 2a | Schema inspection + canonical network build | ✅ Complete |
| 2a.1 | Review, normalize, freeze candidate network | ✅ Complete |
| 2b | Routing prototype | ✅ Complete |
| 2b.1 | Routing corrections + integration readiness | ✅ Complete |
| 3 | Functional PWA integration (vertical slice) | ✅ Complete |
| 4 | Pilot | Ready — **public release blocked on licensing gate G1** |

**Canonical network `v1.2` · `bbg-net-v1.2-e1284e6001ff54f5` · routing engine `2.1.0`**

145.588 required miles (123.807 street · 10.423 trail · 11.359 campus) across 9 valid
routing components, with 11,024 households associated to required coverage.

## Running it

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
python3 -m pytest                                  # 82 backend tests
cd web && npm test                                 # 10 component tests
cd web && node e2e/slice.mjs                       # 41 end-to-end assertions
```

## Layout

```
pipeline/    fetch -> normalize -> split -> classify -> connect -> households -> report
api/routing/ the frozen routing engine (cluster-first -> GRASP -> local search)
api/app/     FastAPI: identity, route generation, walks, reservations, progress, admin
web/         React + TypeScript + Vite PWA, mobile-first
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
- [`docs/13-phase-3-integration.md`](docs/13-phase-3-integration.md) — **current**: network v1.2, the vertical slice, privacy, deployment tiers, pilot readiness.

## Two things to know before deploying

**Licensing.** No Town of Blacksburg dataset publishes any reuse licence. Route and map
geometry is therefore served only to authenticated participants; anonymous callers get
aggregate metrics and a 403 naming the gate. `BPW_PUBLIC_GEOMETRY_ENABLED` overrides
that and should stay false until the question is answered.

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
