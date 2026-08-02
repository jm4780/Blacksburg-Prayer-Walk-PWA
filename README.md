# Blacksburg Prayer Walk PWA

A mobile-first Progressive Web App that helps people systematically prayer-walk every
eligible public street and major trail in the Town of Blacksburg, Virginia.

**Core experience:** Open the app. Generate a route. Pray while walking. Confirm the
streets covered. Watch the town gradually fill in.

## Project status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Geographic data audit + technical plan | ✅ Complete — see docs below |
| 2 | Canonical network preparation | Not started |
| 3 | Routing prototype | Not started |
| 4 | Minimal backend | Not started |
| 5 | PWA interface | Not started |
| 6 | Pilot | Not started |

## Documents

- [`docs/01-data-audit.md`](docs/01-data-audit.md) — Phase 1 geographic data audit:
  sources, licensing, known gaps, and manual-cleanup needs for every dataset the
  project requires.
- [`docs/02-technical-plan.md`](docs/02-technical-plan.md) — the written technical
  plan: architecture, stack, data pipeline, network model, routing approach, and
  build sequence.
- [`docs/00-product-spec.md`](docs/00-product-spec.md) — the V1 product and routing
  specification this project implements.
- [`docs/03-decisions.md`](docs/03-decisions.md) — decision log. Notably **D1: the
  Virginia Tech campus is included**, with dorms counted as rooms.

## Guiding principle

> Does this make it easier for someone to prayer-walk another street today?

If not, it goes in the future-feature backlog.
