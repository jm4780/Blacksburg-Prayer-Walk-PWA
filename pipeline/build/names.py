"""Street and trail name normalization.

Two outputs per feature, per technical plan §2.2:

  display_name     "N Main St"   — what a human reads
  normalized_name  "main st n"   — what groups segments into a named street (§12)

normalized_name puts the directional last so "N Main St" and "Main St N" collapse
together, lowercases, strips punctuation, and maps suffix variants onto one spelling.
"""
import re

# USPS-style suffix normalization. Keys are anything we have seen in either the town's
# Roads TYPE field or the free-text Road field on Paths; values are the canonical form.
SUFFIX = {
    "aly": "aly", "alley": "aly",
    "ave": "ave", "avenue": "ave", "av": "ave",
    "blvd": "blvd", "boulevard": "blvd",
    "cir": "cir", "circle": "cir", "cirs": "cir",
    "ct": "ct", "court": "ct", "cts": "ct",
    "dr": "dr", "drive": "dr", "drs": "dr",
    "ln": "ln", "lane": "ln",
    "mall": "mall",
    "pass": "pass",
    "pl": "pl", "place": "pl",
    "plz": "plz", "plaza": "plz",
    "rd": "rd", "road": "rd", "rds": "rd",
    "rdg": "rdg", "ridge": "rdg",
    "run": "run",
    "sq": "sq", "square": "sq",
    "st": "st", "street": "st", "str": "st",
    "ter": "ter", "terrace": "ter", "terr": "ter",
    "trl": "trl", "trail": "trl",
    "way": "way",
    "xing": "xing", "crossing": "xing",
    "byp": "byp", "bypass": "byp",
    "hwy": "hwy", "highway": "hwy",
    "pkwy": "pkwy", "parkway": "pkwy",
}

DIRECTIONAL = {
    "n": "n", "north": "n",
    "s": "s", "south": "s",
    "e": "e", "east": "e",
    "w": "w", "west": "w",
    "ne": "ne", "northeast": "ne",
    "nw": "nw", "northwest": "nw",
    "se": "se", "southeast": "se",
    "sw": "sw", "southwest": "sw",
}

DISPLAY_SUFFIX = {v: v.title() for v in set(SUFFIX.values())}
DISPLAY_DIR = {v: v.upper() for v in set(DIRECTIONAL.values())}

# Source misspellings and inconsistencies found during the Phase 2a schema inspection.
# Every substitution is logged by the caller; nothing is corrected silently.
NAME_FIXES = {
    "bicenntennial trail": "bicentennial trail",
    "deerfield": "deerfield trail",
    "s main sts": "s main st",
    "smithfield road trail underpass": "smithfield road trail",
    "hethwood trail underpass": "hethwood trail",
}

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def _tokens(raw):
    s = _PUNCT.sub(" ", (raw or "").lower())
    return [t for t in _WS.sub(" ", s).strip().split(" ") if t]


def normalize(raw, fixes_log=None):
    """Return (display_name, normalized_name). Empty input yields (None, None)."""
    toks = _tokens(raw)
    if not toks:
        return None, None

    joined = " ".join(toks)
    if joined in NAME_FIXES:
        fixed = NAME_FIXES[joined]
        if fixes_log is not None:
            fixes_log.append({"field": "name", "from": raw, "to": fixed, "rule": "NAME_FIXES"})
        toks = _tokens(fixed)

    # Pull a leading or trailing directional out of the token stream.
    direction = None
    if len(toks) > 1 and toks[0] in DIRECTIONAL:
        direction = DIRECTIONAL[toks.pop(0)]
    elif len(toks) > 1 and toks[-1] in DIRECTIONAL:
        direction = DIRECTIONAL[toks.pop()]

    # Pull a trailing suffix.
    suffix = None
    if len(toks) > 1 and toks[-1] in SUFFIX:
        suffix = SUFFIX[toks.pop()]

    core = " ".join(toks)
    if not core:  # the whole name was a directional/suffix — keep it literal
        return raw.strip(), joined

    normalized = " ".join(x for x in (core, suffix, direction) if x)

    display_parts = []
    if direction:
        display_parts.append(DISPLAY_DIR[direction])
    display_parts.append(" ".join(w.capitalize() for w in core.split(" ")))
    if suffix:
        display_parts.append(DISPLAY_SUFFIX[suffix])
    return " ".join(display_parts), normalized


def road_name(attrs, fixes_log=None):
    """Assemble a name from the town Roads layer's split name fields."""
    parts = [attrs.get(k) for k in ("PREDIR", "NAME", "TYPE", "SUFFIX")]
    raw = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return normalize(raw, fixes_log)


def address_name(attrs, fixes_log=None):
    """Assemble a street name from the town Address layer's split name fields."""
    parts = [attrs.get(k) for k in
             ("STREET_PRE_DIR", "STREET_NAME", "STREET_TYPE", "STREET_POST_DIR")]
    raw = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return normalize(raw, fixes_log)
