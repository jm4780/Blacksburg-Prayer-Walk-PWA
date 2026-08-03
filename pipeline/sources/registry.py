"""Registry of every source layer the network build consumes.

One entry per layer. `url` is the ArcGIS FeatureServer layer endpoint; everything
else is metadata that ends up in the snapshot sidecar so a build months from now can
say exactly where each feature came from and under what terms.

`license_text` is transcribed verbatim from what the *service* returns, not from the
publisher's website. Where a service returns nothing — which is the case for every
Town of Blacksburg layer — that is recorded as the empty string and
`license_status` is NONE_PUBLISHED. See docs/05-licensing-status.md.
"""

TOB = "https://services1.arcgis.com/rAuQoDGA22NtJdmg/arcgis/rest/services"

# license_status values:
#   NONE_PUBLISHED  service returns no copyrightText and no licence terms
#   DISCLAIMER_ONLY publisher attaches a warranty disclaimer, no grant of rights
#   ATTRIBUTION     publisher names required attribution
LAYERS = {
    "roads": dict(
        url=f"{TOB}/Address_Road_Building/FeatureServer/1",
        title="Town of Blacksburg — Roads",
        publisher="Town of Blacksburg",
        role="Primary street network",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "address": dict(
        url=f"{TOB}/Address_Road_Building/FeatureServer/0",
        title="Town of Blacksburg — Address",
        publisher="Town of Blacksburg",
        role="Household base layer (unit-level)",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "building": dict(
        url=f"{TOB}/Address_Road_Building/FeatureServer/2",
        title="Town of Blacksburg — Building",
        publisher="Town of Blacksburg",
        role="Household sanity check; complex footprints",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "boundary": dict(
        url=f"{TOB}/Administrative_Reference_Boundaries/FeatureServer/4",
        title="Town of Blacksburg — Town Corporate Limits",
        publisher="Town of Blacksburg",
        role="Coverage area boundary",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "paths": dict(
        url=f"{TOB}/Paths_to_the_Future/FeatureServer/0",
        title="Town of Blacksburg — Paths to the Future (Existing)",
        publisher="Town of Blacksburg",
        role="Trails, sidewalks, bike infrastructure",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "landuse": dict(
        url=f"{TOB}/Comprehensive_Plan/FeatureServer/8",
        title="Town of Blacksburg — Current Land Use",
        publisher="Town of Blacksburg",
        role="Residential filter (replaces county parcels)",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "zoning": dict(
        url=f"{TOB}/Zoning_and_Landuse/FeatureServer/9",
        title="Town of Blacksburg — Town Zoning",
        publisher="Town of Blacksburg",
        role="UNIV polygon = campus core draft; district context",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "openspace": dict(
        url=f"{TOB}/Parks_and_Open_Space/FeatureServer/1",
        title="Town of Blacksburg — Open Space",
        publisher="Town of Blacksburg",
        role="HOA / privately-owned polygons: private-drive corroboration",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
    "parks": dict(
        url=f"{TOB}/Parks_and_Open_Space/FeatureServer/0",
        title="Town of Blacksburg — Parks",
        publisher="Town of Blacksburg",
        role="Named park context for trail curation",
        license_text="",
        license_status="NONE_PUBLISHED",
        source_id_field="OBJECTID",
        stable_id_field="GlobalID",
    ),
}

# Sources we need but cannot reach from this environment. Kept in the registry so the
# build report can state the gap rather than quietly omitting it.
BLOCKED = {
    "mont_parcels": dict(
        url="https://services5.arcgis.com/IZ8QFYP84iubFqmi/arcgis/rest/services/Parcels_Open_Data/FeatureServer/0",
        title="Montgomery County — Parcels Open Data",
        publisher="Montgomery County, VA",
        role="Residential cross-check; EX_CLASSD property class",
        blocked_host="services5.arcgis.com",
        license_status="DISCLAIMER_ONLY",
    ),
    "vgin_rcl": dict(
        url="https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/VBMP_RCL/FeatureServer",
        title="VGIN — Virginia Road Centerlines (RCL)",
        publisher="Virginia Geographic Information Network",
        role="VT campus street candidate source; statewide cross-check",
        blocked_host="vginmaps.vdem.virginia.gov",
        license_status="DISCLAIMER_ONLY",
    ),
    "vgin_addr": dict(
        url="https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/VA_Address_Points/FeatureServer",
        title="VGIN — Virginia Address Points",
        publisher="Virginia Geographic Information Network",
        role="Address cross-check; campus address candidate source",
        blocked_host="vginmaps.vdem.virginia.gov",
        license_status="DISCLAIMER_ONLY",
    ),
}
