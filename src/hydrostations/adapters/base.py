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
