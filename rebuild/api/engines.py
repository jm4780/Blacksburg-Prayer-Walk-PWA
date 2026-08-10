"""Lazy, forgiving access to the coverage and route engines.

Those two modules are owned by other people and land on their own schedule.
Nothing here imports them at start-up, so the server runs, serves the map, and
commits walks whether or not either engine exists yet. When one is missing the
endpoint that needs it returns 503 with a plain sentence, and every other
endpoint carries on.
"""

from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

REBUILD_DIR = Path(__file__).resolve().parent.parent
if str(REBUILD_DIR) not in sys.path:
    sys.path.insert(0, str(REBUILD_DIR))

# Test hook: point at a directory that contains an `engine/` package to stand in
# for the real one. Unset in normal use.
_alt = os.environ.get("BPW_ENGINE_PATH")
if _alt and _alt not in sys.path:
    sys.path.insert(0, _alt)


class EngineUnavailable(Exception):
    """The engine is not importable, or does not match the contract."""

    def __init__(self, engine: str, detail: str):
        self.engine = engine
        self.detail = detail
        super().__init__(f"{engine}: {detail}")


_loaded: dict[tuple[str, str], Callable[..., Any]] = {}


def _load(module_name: str, attr: str) -> Callable[..., Any]:
    """Import once and keep it.

    A successful load is cached, because these engines hold expensive state
    between calls (the route engine caches the graph it builds from the
    network, which takes about a second). A failed load is not cached, so an
    engine that lands while the server is running is picked up on the next
    request rather than needing a restart.
    """
    key = (module_name, attr)
    hit = _loaded.get(key)
    if hit is not None:
        return hit
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        raise EngineUnavailable(
            module_name,
            f"import failed: {traceback.format_exc(limit=2).strip().splitlines()[-1]}",
        )
    fn = getattr(mod, attr, None)
    if not callable(fn):
        raise EngineUnavailable(module_name, f"no callable {attr}()")
    _loaded[key] = fn
    return fn


def propose(trace: list[dict[str, Any]], network: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fn = _load("engine.coverage", "propose")
    try:
        out = fn(trace, network)
    except TypeError as exc:
        raise EngineUnavailable("engine.coverage", f"signature mismatch: {exc}")
    return [_as_dict(p) for p in out]


def generate(
    start_lonlat: tuple[float, float],
    target_m: float,
    network: list[dict[str, Any]],
    covered: set[int],
    seed: int | None = None,
) -> dict[str, Any]:
    fn = _load("engine.route", "generate")
    try:
        out = fn(start_lonlat, target_m, network, covered, seed=seed)
    except TypeError as exc:
        raise EngineUnavailable("engine.route", f"signature mismatch: {exc}")
    return _as_dict(out)


def to_geojson(geom: Any) -> dict[str, Any] | None:
    """Whatever the engine hands back, the client gets GeoJSON.

    The route engine returns a shapely LineString, which is a perfectly good
    thing for an engine to return and not something the browser can read. Any
    object with __geo_interface__ works, as does plain GeoJSON, as does a bare
    list of coordinates.
    """
    if geom is None:
        return None
    if isinstance(geom, dict):
        return geom
    gi = getattr(geom, "__geo_interface__", None)
    if gi is not None:
        return {
            "type": gi["type"],
            "coordinates": _plain(gi["coordinates"]),
        }
    coords = getattr(geom, "coords", None)
    if coords is not None:
        return {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coords]}
    if isinstance(geom, (list, tuple)):
        return {"type": "LineString", "coordinates": _plain(geom)}
    raise EngineUnavailable("engine.route", f"cannot read geometry of type {type(geom).__name__}")


def _plain(value: Any) -> Any:
    """Tuples and numpy scalars into lists and floats, all the way down."""
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return float(value)


def metres_for_minutes(minutes: float, fallback_pace: float) -> float:
    """Minutes to metres, using the route engine's own pace when it has one.

    The engine plans against a target in metres and judges itself on a +/-15%
    band around it. If the API converted at a different pace than the engine
    plans at, every route would sit at the edge of that band for no reason.
    """
    try:
        fn = _load("engine.route", "meters_for_minutes")
        return float(fn(minutes))
    except Exception:
        return minutes * fallback_pace


def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "_asdict"):
        return dict(obj._asdict())
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    raise EngineUnavailable("engine", f"cannot read result of type {type(obj).__name__}")
