# Licensing Status — Release Blocker Register

**Date:** 2026-08-03
**Status:** 🔴 **BLOCKING PUBLIC RELEASE.** Not blocking technical work.

Technical work continues on every source below. What is blocked is *publishing* — the
public PWA, any public map, any public statistic — because for the layers this project
is built on, **no source grants written reuse rights**.

Rule applied throughout: **no dataset is described as public domain unless the source
explicitly grants that status.** None of the sources below do.

---

## 1. What each source actually says

Transcribed from what the *service* or its catalogue entry returns, not from a
publisher's website. Retrieved 2026-08-03.

| Source | Layers we use | Licence text carried by the data | Our reading |
|---|---|---|---|
| **Town of Blacksburg** (`services1.arcgis.com/rAuQoDGA22NtJdmg`) | Roads, Address, Building, Town Corporate Limits, Paths to the Future, Current Land Use, Town Zoning, Parks, Open Space | **Nothing.** `copyrightText` is the empty string at both service and layer level on every service inspected. No licence field, no terms, no attribution string. | **No grant and no restriction — silence.** Silence is not permission. |
| **Town of Blacksburg** — Brush Mountain Trails | (not used in the network) | `"Poverty Creek Trails Coalition, New River Land Trust, Town of Blacksburg"` | Attribution named; still no reuse grant. |
| **Montgomery County, VA** (`services5.arcgis.com/IZ8QFYP84iubFqmi`) | Parcels Open Data *(not yet retrieved — host blocked)* | Warranty disclaimer only: *"Information shown is for reference purposes only and is not to be construed or used as a legal or official determination of official county, state, and/or federal records. Data is believed to be accurate but is not guaranteed. The Montgomery County Board of Supervisors or Planning & GIS Services are not responsible for any inaccuracies herein contained or for damages or other liabilities due to the accuracy, availability, use or misuse of this information."* Hub `license` field = `custom`. Plus: *"Owner names are excluded for privacy."* | Disclaimer of liability, not a grant of rights. |
| **VGIN** (`vginmaps.vdem.virginia.gov`) | RCL, Address Points, Building Footprints *(not yet retrieved — host blocked)* | Warranty disclaimer only, identical across all three: *"The Virginia Base Data layers are intended for cartographic use and spatial analysis only, and not for use as a legal description. Best efforts were undertaken to ensure the correctness of RCL, Address Points, Parcels, Administrative Boundaries, and Building Footprint data throughout the Commonwealth of Virginia, however, all warranties regarding the accuracy of the map data and any representation or inferences derived there from are hereby expressly disclaimed."* Hub `license` = `custom`. | Disclaimer, not a grant. ⚠️ **"intended for cartographic use and spatial analysis only" is arguably narrower than what we do** — deriving a routable network and publishing statistics may exceed it. |
| **U.S. Census / TIGER** | Housing-unit and household benchmarks | Federal government work | Public domain — the **only** source here that genuinely is. |
| **OpenStreetMap** | Not used | ODbL 1.0 | Explicit licence; deliberately excluded from the canonical network (audit §2.4). |

### Correction to the Phase 1 audit

The audit stated VGIN Address Points were *"public domain as of January 1, 2012 — the
cleanest license in the whole audit."* **That is not supported by anything VGIN
attaches to the dataset.** The claim traces to the address-point standard document,
not to a licence grant on the data. Corrected in `01-data-audit.md` §2.2.

---

## 2. Permissions we need, in the words we need them

One list per provider. Each line is a distinct right; a provider may grant some and
not others, and we need to know which.

### 2.1 Town of Blacksburg — Engineering & GIS *(highest priority)*

We use Roads, Address, Building, Town Corporate Limits, Paths to the Future, Current
Land Use, Town Zoning, Parks, and Open Space. Every one of these is load-bearing.

Permissions requested:

1. **Download and store** — retain periodic snapshots of the listed layers on our
   servers, indefinitely, for reproducible builds.
2. **Transform and combine** — reproject, split at intersections, merge with other
   sources, and derive new geometry (including synthetic connector edges) from them.
3. **Display derived map geometry** — show the derived street and trail network on a
   public map in a web application, at street level, to unauthenticated users.
4. **Produce routes** — compute and display walking routes that trace the derived
   geometry, and hand those routes to members of the public.
5. **Publish aggregate statistics** — publish counts and percentages derived from the
   data (e.g. "62% of Blacksburg streets covered", total street mileage, estimated
   household counts) on a public website.
6. **Retain processed data in the application database** — hold the derived network,
   its identifiers, and household estimates in our production database for the life of
   the project, including after a source layer is updated or withdrawn.
7. **Attribution** — tell us the exact wording and placement you require. We will
   display it whether or not it is required.
8. **Term and revocation** — confirm whether permission is open-ended, and what you
   would want us to do if the town later withdraws it.

Suggested framing for the ask: this is a volunteer project for a local church to
organise neighbourhood prayer walking. It is non-commercial, it drives foot traffic
onto public streets, and it will credit the town.

### 2.2 Montgomery County, VA — GIS Services

Currently a cross-check only; the residential filter now uses the town's own Current
Land Use layer instead. Needed only if we reinstate parcels.

Same rights 1–8 as above, plus:

9. **Confirmation that the published Parcels Open Data extract is intended for public
   reuse** and that the owner-name exclusion is deliberate and permanent.

### 2.3 VGIN / Virginia Department of Emergency Management

Needed if VGIN RCL becomes the source for VT campus streets (see
`07-vt-campus-coverage.md`).

Same rights 1–8, plus the one that matters most here:

10. **Clarification of "intended for cartographic use and spatial analysis only."**
    Does that phrase restrict use, or is it a disclaimer of fitness? Specifically: may
    we derive a routable pedestrian network from RCL, publish it, and generate walking
    routes from it?

### 2.4 Virginia Tech *(if VT GIS becomes a source)*

Same rights 1–8 for any campus street, building, or residence-hall data, plus:

11. **Permission to publish residence-hall capacity figures** in aggregate form as
    part of a household estimate.

---

## 3. Release gate

| Gate | Condition | Current |
|---|---|---|
| **G1** | Written permission from the Town of Blacksburg covering rights 1–6 | ❌ not requested yet |
| **G2** | Attribution wording captured and implemented | ❌ blocked on G1 |
| **G3** | Every source used in a shipped build has a recorded `license_status` that is not `NONE_PUBLISHED` | ❌ all nine town layers are `NONE_PUBLISHED` |
| **G4** | If VGIN data ships: right 10 answered | ⚪ not yet applicable |
| **G5** | If VT data ships: right 11 answered | ⚪ not yet applicable |

**G1 is the whole blocker.** It is an email and a conversation, and it has latency
measured in weeks, so it should be sent before any more engineering happens. Nothing
downstream of it can start earlier.

Until G1 clears, the following are safe and the following are not:

**Safe now** — building the network, running the pipeline, internal review of the map
and reports, prototyping the router, developing the PWA against the data.

**Not safe until G1** — deploying a public URL, showing the map to anyone outside the
project, publishing coverage percentages, distributing route files, or committing
snapshot geometry to a public repository.

> 🔴 **This repository is public.** Checked 2026-08-03 via the GitHub API:
> `jm4780/Blacksburg-Prayer-Walk-PWA` has `"visibility": "public"`.
>
> That makes the redistribution question immediate rather than hypothetical.
> `pipeline/snapshots/` holds verbatim copies of town GIS data (43 MB) and
> `pipeline/out/` holds geometry derived from it (20 MB). Publishing either is exactly
> what G1 has not authorised.
>
> **Action taken:** a `.gitignore` excludes all raw snapshots, all derived geometry
> (`segments.geojson`, `nodes.geojson`, `network-map.html`), and the two files
> containing individual addresses. What is committed is the pipeline code, the snapshot
> **sidecars** (field names, counts, URLs, edit dates — metadata *about* the data), the
> build report, and aggregate review files. Anyone with network access reproduces the
> rest in a few minutes by running the pipeline.
>
> **Separate from licensing: `households.json` and
> `review/unassociated-households.json` contain ~18,000 individual residential street
> addresses.** Those stay out of a public repository regardless of how the licensing
> question is answered. They are derived from published 911 address points, so this is
> not a leak of anything secret — but assembling them into a downloadable list of every
> home in town is a different act from the town publishing a queryable address layer,
> and it is not one this project needs to perform.
>
> **Decision still needed:** make the repository private, or accept working
> permanently under these exclusions. Recommendation: make it private until G1 clears.
> It costs nothing and it removes a whole category of question.

---

## 4. What is recorded in the build

Every segment in `segments.geojson` carries:

```json
"source": {
  "dataset": "roads",
  "source_id": 1234,
  "source_global_id": "…",
  "source_layer_url": "https://services1.arcgis.com/…/FeatureServer/1",
  "source_updated_at": "2026-04-07T12:03:59+00:00",
  "retrieved_at": "2026-08-03T…",
  "license_status": "NONE_PUBLISHED"
}
```

Synthetic connectors carry `"dataset": "DERIVED"` and `"license_status": "DERIVED"`
with a `derived_from` block naming what they were stitched between. Nothing in the
network is untraceable, and nothing claims a licence it does not have.
