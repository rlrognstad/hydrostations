from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import geopandas as gpd


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


class StationAdapter(ABC):
    """Interface every network adapter must implement."""

    network: str
    license: str
    redistribution_ok: bool
    compartments: tuple[str, ...]

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
