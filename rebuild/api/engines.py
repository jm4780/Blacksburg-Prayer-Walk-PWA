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


def _load(module_name: str, attr: str) -> Callable[..., Any]:
    try:
        mod = importlib.import_module(module_name)
        importlib.reload(mod)
    except Exception:
        raise EngineUnavailable(
            module_name,
            f"import failed: {traceback.format_exc(limit=2).strip().splitlines()[-1]}",
        )
    fn = getattr(mod, attr, None)
    if not callable(fn):
        raise EngineUnavailable(module_name, f"no callable {attr}()")
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


def _as_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "_asdict"):
        return dict(obj._asdict())
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    raise EngineUnavailable("engine", f"cannot read result of type {type(obj).__name__}")
