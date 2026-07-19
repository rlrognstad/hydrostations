from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import geopandas as gpd

if TYPE_CHECKING:
    # Type-only: register.models imports BBox from this module, so importing
    # SourceEntry back here for real would be circular. `from __future__
    # import annotations` already makes the SourceEntry hint lazy, but the
    # explicit TYPE_CHECKING guard keeps that clear rather than relying on
    # it implicitly.
    from hydrostations.register.models import SourceEntry


@dataclass(frozen=True)
class BBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


def bboxes_intersect(a: BBox, b: BBox) -> bool:
    return not (
        a.max_lon < b.min_lon
        or a.min_lon > b.max_lon
        or a.max_lat < b.min_lat
        or a.min_lat > b.max_lat
    )


class SourceAdapter(ABC):
    """Interface every source (agency/network) adapter must implement.

    Constructed from a validated register entry -- see
    `hydrostations.register`. Every current adapter (protocol and bespoke
    alike) uses this base `__init__` unchanged; protocol-specific config
    lives on `entry.kiwis`/`entry.wfs`/`entry.arcgis`/etc., read directly
    by the adapter rather than copied into separate instance attributes.
    """

    protocol: str

    def __init__(self, entry: SourceEntry) -> None:
        self.entry = entry
        self.source = entry.source_id
        self.license = entry.license
        self.redistribution_ok = entry.redistribution_ok
        self.compartments = tuple(entry.compartments)
        self.coverage = entry.coverage_bboxes()
        self.live = entry.live

    @abstractmethod
    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        """Return stations matching the given filters as a normalized GeoDataFrame.

        `compartment`, when given, is always one of this adapter's own
        `compartments` -- the caller (`hydrostations.core`) filters out
        unsupported compartments before calling in.
        """
        raise NotImplementedError

    def _skip_out_of_coverage(self, bbox: BBox | None) -> bool:
        """Whether to skip fetching entirely because `bbox` can't intersect
        this source's declared coverage.

        Opt-in via the register entry's `skip_out_of_coverage` flag (only
        NWIS sets it true, to avoid its own bbox-size API limit) --
        deliberately NOT applied to every source by default. Coverage
        bboxes are coarse, hand-declared approximations; skipping on them
        could suppress genuinely valid results near a coverage-bbox edge
        for a source that doesn't need the guard.
        """
        if not self.entry.skip_out_of_coverage or bbox is None:
            return False
        return not any(bboxes_intersect(bbox, c) for c in self.coverage)
