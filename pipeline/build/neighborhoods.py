"""Neighbourhood names, from the Town's own road data.

The Roads layer carries `NbrhdCom_L` / `NbrhdCom_R` on 1,528 of 1,547 records. These
are the names residents actually use — Hethwood, Tom's Creek, Miller Southside — and
they are the vocabulary a mission description needs. Nothing else in the project has
ever read them.

They are NOT a routing concept. The router keeps working on segments, clusters and
completion state; a neighbourhood is a label carried alongside, for the application
layer to build a sentence from. See docs/17 §7.

The raw values need the same light cleaning the street names got in Phase 2a: case
duplicates, a slash inconsistency, and one typo.
"""

# Raw value -> canonical. Only entries that actually need fixing; anything not listed
# passes through unchanged, so a new neighbourhood appearing in a future snapshot shows
# up as itself rather than being silently dropped.
CANONICAL = {
    "TOMS CREEK": "Tom's Creek",
    "NORTHSIDE PARK": "Northside Park",
    "UNIVERSITY": "University",
    "MAIN/PATRICK HENRY": "Main/Patrick Henry",
    "MOUNTAIN VIEW": "Mountain View",
    "ALLEGHANY": "Alleghany",
    "MCBYDE": "McBryde",          # typo in the source
    "MCBRYDE": "McBryde",
    "Kabrich/crescent": "Kabrich Crescent",
    "Kabrich/Crescent": "Kabrich Crescent",
    "HETHWOOD/PRICES FORK": "Hethwood/Prices Fork",
    "GRISSOM/HIGHLAND": "Grissom/Highland",
    "ELLETT/JENNELLE": "Ellett/Jennelle",
    "DOWNTOWN": "Downtown",
}

# Campus pedestrian ways carry no neighbourhood in the Roads layer, because the Roads
# layer contains no campus streets at all. Naming them explicitly is better than
# leaving a large, recognisable part of town unlabelled.
CAMPUS_NEIGHBORHOOD = "Virginia Tech"

# How a neighbourhood name reads inside a sentence. Most are plain, a few want an
# article. Kept here rather than in the application so the data and its grammar travel
# together; the application still owns the sentence itself.
ARTICLE = {
    "Drillfield": "the ",
}


def normalize(raw: str | None) -> str | None:
    """Canonical neighbourhood name, or None."""
    if not raw:
        return None
    v = " ".join(str(raw).split()).strip()
    if not v:
        return None
    if v in CANONICAL:
        return CANONICAL[v]
    # Fall back to a case-insensitive match against known canonical forms, so a future
    # snapshot shouting a name we already know does not create a duplicate.
    upper = v.upper()
    for canon in set(CANONICAL.values()):
        if canon.upper() == upper:
            return canon
    return v


def for_road(attrs: dict) -> str | None:
    """A road's neighbourhood.

    Left and right sides usually agree. When they differ the road *is* the boundary
    between two neighbourhoods; the left value is taken and the disagreement is not
    treated as an error, because both answers are correct.
    """
    left = normalize(attrs.get("NbrhdCom_L"))
    right = normalize(attrs.get("NbrhdCom_R"))
    return left or right


def is_boundary(attrs: dict) -> bool:
    left = normalize(attrs.get("NbrhdCom_L"))
    right = normalize(attrs.get("NbrhdCom_R"))
    return bool(left and right and left != right)


def phrase(name: str | None) -> str:
    """The name as it appears mid-sentence: 'through Hethwood', 'through the
    Drillfield'."""
    if not name:
        return "this area"
    return f"{ARTICLE.get(name, '')}{name}"
