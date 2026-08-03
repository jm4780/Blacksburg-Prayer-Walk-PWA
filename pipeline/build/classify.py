"""The eligibility pass: segment_type, access_type, and project role.

Rules first, human review after. Every automatic decision records why it was made,
and anything the rules cannot settle is emitted with role_status=NEEDS_REVIEW rather
than guessed at.

Ownership policy (per instruction): RD_MAINT is the primary Town-road ownership
field. Where ROAD_CLASS disagrees, RD_MAINT wins and the conflict is reported.
"""
from . import curation
from .names import normalize

# Path Type values that ride on the roadway and are absorbed as street attributes
# rather than modelled as separate walkable edges.
ONSTREET_PATH_TYPES = {"Bike Lane", "Sharrow", "Share the Road", "Contra Flow Lane"}
# Path Type values that form the trail network.
TRAIL_PATH_TYPES = {"Trail", "Trail Tunnel", "Bridge", "Stairs"}
SIDEWALK_PATH_TYPES = {"Sidewalk"}
# Alleys appear in both Roads (TYPE=ALY) and Paths; the Paths copies are held for review.
OTHER_PATH_TYPES = {"Alley"}


def walk_stress(speed, road_class):
    """1 (calm) .. 5 (hostile). Feeds the walk-quality score, never eligibility."""
    if speed is None:
        base = 2
    elif speed <= 20:
        base = 1
    elif speed <= 25:
        base = 2
    elif speed <= 35:
        base = 3
    elif speed <= 45:
        base = 4
    else:
        base = 5
    if road_class in ("Arterial", "Primary"):
        base = min(5, base + 1)
    elif road_class == "Collector":
        base = min(5, base + 1) if base < 3 else base
    return base


def classify_road(attrs, conflicts, log):
    """Classify one road segment. Returns a dict of classification fields."""
    maint = (attrs.get("RD_MAINT") or "").strip() or None
    rclass = (attrs.get("ROAD_CLASS") or "").strip() or None
    speed = attrs.get("SpeedLimit")
    reasons = []

    # --- ownership: RD_MAINT is authoritative -------------------------------
    if maint == "Private":
        access = "PRIVATE"
    elif maint in ("Blacksburg", "State"):
        access = "PUBLIC"
    else:
        access = "UNKNOWN"
        reasons.append(f"RD_MAINT missing or unrecognised ({maint!r})")

    # ROAD_CLASS carries its own private flag. Record every disagreement.
    class_says_private = rclass == "Private"
    maint_says_private = maint == "Private"
    if class_says_private != maint_says_private:
        conflicts.append({
            "source_id": attrs.get("OBJECTID"),
            "label": attrs.get("LABEL"),
            "RD_MAINT": maint,
            "ROAD_CLASS": rclass,
            "resolved_to": access,
            "rule": "RD_MAINT is primary (instruction); ROAD_CLASS recorded only",
        })
        reasons.append(f"RD_MAINT={maint} conflicts with ROAD_CLASS={rclass}")

    # --- role ---------------------------------------------------------------
    if rclass in curation.EXCLUDE_ROAD_CLASS:
        role, status = "EXCLUDED", "AUTOMATIC"
        reasons.append(curation.EXCLUDE_ROAD_CLASS[rclass])
    elif access == "PRIVATE":
        role, status = "EXCLUDED", "AUTOMATIC"
        reasons.append("RD_MAINT=Private")
    elif access == "PUBLIC":
        role, status = "REQUIRED", "AUTOMATIC"
    else:
        role, status = "OPTIONAL_CONNECTOR", "NEEDS_REVIEW"

    # A conflict never rides through as a settled automatic decision.
    if class_says_private != maint_says_private and status == "AUTOMATIC":
        status = "NEEDS_REVIEW"

    if rclass and rclass not in {
        "Local", "Private", "Secondary", "Collector", "Arterial", "Ramp",
        "Primary", "Service Drive",
    }:
        log.append({"kind": "unexpected_road_class", "value": rclass,
                    "source_id": attrs.get("OBJECTID")})
        reasons.append(f"unexpected ROAD_CLASS {rclass!r}")

    return dict(
        segment_type="STREET",
        access_type=access,
        ownership=maint,
        road_class=rclass,
        speed_limit=speed,
        walk_stress=walk_stress(speed, rclass),
        walkable=role != "EXCLUDED",
        role=role,
        role_status=status,
        review_reasons=reasons,
        one_way=(attrs.get("ONE_WAY") or "").strip() or None,
    )


def trail_role(normalized_name):
    """Look up a trail's curated role, honouring spur inheritance."""
    if not normalized_name:
        return None
    entry = curation.TRAIL_ROLES.get(normalized_name)
    if entry:
        return entry
    if curation.TRAIL_SPUR_INHERITS:
        for parent, cfg in curation.TRAIL_ROLES.items():
            base = parent.rsplit(" ", 1)[0]  # "huckleberry trl" -> "huckleberry"
            if normalized_name.startswith(base + " ") or normalized_name.startswith(parent):
                return dict(cfg, note=cfg["note"] + " (inherited by spur/related feature)")
    return None


def classify_path(attrs, normalized_name, in_campus, fixes_log):
    """Classify one Paths-to-the-Future feature that survived sidewalk absorption."""
    ptype = (attrs.get("Type") or "").strip()
    owner = (attrs.get("Owner") or "").strip() or None
    material = normalize_material(attrs.get("Material"), attrs.get("OBJECTID"), fixes_log)
    reasons = []

    if ptype in TRAIL_PATH_TYPES:
        segment_type = "TRAIL"
        entry = trail_role(normalized_name)
        if entry:
            role, status = entry["role"], entry["status"]
            reasons.append(entry["note"])
        elif in_campus:
            role = curation.CAMPUS_PATH_DEFAULT_ROLE
            status = curation.CAMPUS_PATH_DEFAULT_STATUS
            reasons.append("Campus path: D1b requires a curated selection, not blanket "
                           "inclusion. Held for review.")
        else:
            role = curation.TRAIL_DEFAULT_ROLE
            status = curation.TRAIL_DEFAULT_STATUS
            reasons.append("Trail not on the D2 curated list; connector until reviewed.")
    elif ptype in SIDEWALK_PATH_TYPES:
        segment_type = "PEDESTRIAN_CONNECTOR"
        if in_campus:
            role = curation.CAMPUS_PATH_DEFAULT_ROLE
            status = curation.CAMPUS_PATH_DEFAULT_STATUS
            reasons.append("Campus walkway, unmatched to any street. D1b candidate; "
                           "held for review.")
        else:
            role, status = "OPTIONAL_CONNECTOR", "NEEDS_REVIEW"
            reasons.append("Sidewalk with no matching street segment — may be a genuine "
                           "connector or a name mismatch. Held for review.")
    else:
        segment_type = "PEDESTRIAN_CONNECTOR"
        role, status = "OPTIONAL_CONNECTOR", "NEEDS_REVIEW"
        reasons.append(f"Path Type={ptype!r} not covered by an automatic rule.")

    if owner == "PRIV":
        role, status = "EXCLUDED", "NEEDS_REVIEW"
        reasons.append("Paths Owner=PRIV — privately owned path.")

    access = {"VT": "PUBLIC", "TOB": "PUBLIC", "PRIV": "PRIVATE"}.get(owner, "UNKNOWN")
    if access == "UNKNOWN":
        reasons.append("Paths Owner blank on 83% of the layer; ownership unknown.")

    return dict(
        segment_type=segment_type,
        access_type=access,
        ownership=owner,
        road_class=None,
        speed_limit=None,
        # Paths carry no traffic; stress is low but not zero (crossings, shared use).
        walk_stress=1,
        walkable=role != "EXCLUDED",
        role=role,
        role_status=status,
        review_reasons=reasons,
        surface=material,
        path_type=ptype,
        # NOTE: the source Slope field is populated on 1,026 of 1,069 features and every
        # value is 0. It is deliberately not read — see docs/04-schema-inspection.md Q4.
        grade_pct=None,
        grade_source="UNAVAILABLE",
        one_way=None,
    )


MATERIAL_FIXES = {"aspahlt": "Asphalt"}
MATERIAL_CANON = {
    "concrete": "Concrete", "asphalt": "Asphalt", "brick": "Brick",
    "concrete/asphalt": "Concrete/Asphalt", "mix": "Mixed", "gravel": "Gravel",
    "dirt": "Dirt", "wood": "Wood", "green lane": "Green Lane",
}
PAVED = {"Concrete", "Asphalt", "Brick", "Concrete/Asphalt", "Green Lane"}


def normalize_material(raw, source_id, fixes_log):
    v = (raw or "").strip()
    if not v or v.lower() == "review":
        return None
    low = v.lower()
    if low in MATERIAL_FIXES:
        fixed = MATERIAL_FIXES[low]
        fixes_log.append({"field": "Material", "from": v, "to": fixed,
                          "source_id": source_id, "rule": "MATERIAL_FIXES"})
        return fixed
    return MATERIAL_CANON.get(low, v)


def sidewalk_key(attrs, fixes_log):
    """Normalized street name a sidewalk claims to parallel."""
    _, norm = normalize(attrs.get("Road"), fixes_log)
    return norm
