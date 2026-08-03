"""The frozen network and routing engine, loaded once, plus completion state from the DB.

The routing package is treated as a read-only dependency here. Nothing in `api/app`
modifies the network, the weights or the engine — Phase 3 §2 requires the engine to
stay the integration baseline, and the only way to keep that promise is to never reach
into it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...routing import components as comp_mod
from ...routing import network as net_mod
from ...routing.engine import VARIANTS, Engine, EngineConfig
from ...routing.state import CompletionState
from ..config import settings
from ..models import Completion, Reservation

M_PER_MILE = 1609.344

# How hard a live reservation damps another walker's prize on the same segment.
# Not zero: §12 says reservations are penalties, not locks, so a segment someone else
# is walking stays reachable if it is the only sensible thing nearby.
RESERVED_MULTIPLIER = 0.15


class NetworkService:
    """Holds the loaded network, the engine, and the id<->index maps."""

    def __init__(self, date: str):
        self.net = net_mod.load(date, quiet=True)
        self.engine = Engine(self.net)
        self.idx_of_id = {s.id: s.idx for s in self.net.segments}
        self.id_of_idx = {s.idx: s.id for s in self.net.segments}
        self.components = self.engine.component_info
        self.component_summary = comp_mod.summary(self.components)
        self.manifest = net_mod.freeze_manifest(self.net)

        # Denominator for "% of Blacksburg prayed for". Uses the component
        # classification, so mileage nobody may lawfully walk is out and mileage we
        # simply cannot route to on its own is still in — see components.py.
        self.required_denominator_miles = self.component_summary[
            "required_miles_in_denominator"]
        self.total_households_on_required = self.net.stats["households_on_required"]

    # ------------------------------------------------------------- conversions
    def indices(self, segment_ids) -> set[int]:
        return {self.idx_of_id[s] for s in segment_ids if s in self.idx_of_id}

    def ids(self, indices) -> list[str]:
        return [self.id_of_idx[i] for i in indices if i in self.id_of_idx]

    def required_ids(self, indices) -> list[str]:
        return [self.id_of_idx[i] for i in indices
                if i in self.id_of_idx and self.net.segments[i].required]

    # ----------------------------------------------------------------- state
    def completed_indices(self, db: Session) -> set[int]:
        rows = db.execute(select(Completion.segment_id).distinct()).scalars().all()
        return self.indices(rows)

    def active_reservations(self, db: Session, exclude_participant: str | None = None
                            ) -> dict[int, str]:
        """segment index -> participant id holding a live reservation."""
        now = datetime.now(timezone.utc)
        q = select(Reservation.segment_id, Reservation.participant_id).where(
            Reservation.released_at.is_(None), Reservation.expires_at > now)
        out = {}
        for seg_id, pid in db.execute(q).all():
            if exclude_participant is not None and pid == exclude_participant:
                continue
            i = self.idx_of_id.get(seg_id)
            if i is not None:
                out[i] = pid
        return out

    def completion_state(self, db: Session, participant_id: str | None = None
                         ) -> CompletionState:
        """Current state of the town, as the router should see it for this participant.

        A participant's own reservations are not damped — re-generating your own route
        should not make your own held segments look worthless.
        """
        reserved = {i: RESERVED_MULTIPLIER for i in
                    self.active_reservations(db, exclude_participant=participant_id)}
        return CompletionState(self.net, self.completed_indices(db), reserved)

    def engine_with_seed(self, seed: int) -> Engine:
        """A per-request engine. §11: route diversity comes from a request-specific
        seed, so two people standing on the same corner get different walks.

        Weights are NOT a parameter here — they are the frozen defaults. Diversity is
        allowed to change which good route you get, never what counts as good.
        """
        cfg = EngineConfig(random_seed=seed)
        eng = Engine(self.net, config=cfg)
        # Component classification and the CSR graph are expensive and seed-independent.
        eng.g = self.engine.g
        eng.component_info = self.engine.component_info
        eng.components = self.engine.components
        eng.snappable = self.engine.snappable
        eng.component_of_node = self.engine.component_of_node
        eng.main_component = self.engine.main_component
        return eng


@lru_cache
def network_service() -> NetworkService:
    return NetworkService(settings().snapshot_date)


BANDS = VARIANTS
