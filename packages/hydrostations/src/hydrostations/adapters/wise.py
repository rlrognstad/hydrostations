"""WISE (Water Information System for Europe, EEA) adapter -- not yet implemented.

WISE-SoE / Waterbase data isn't exposed as a simple per-network "list
stations" REST endpoint the way NWIS is. Access today is bulk CSV/GeoPackage
downloads from the EEA data catalogue (e.g. the Waterbase - Water Quantity
and Waterbase - Water Quality datasets), which need to be fetched, cached,
and re-parsed rather than queried live station-by-station.

Before implementing:

- Identify the current EEA data catalogue dataset IDs / download URLs for
  the water-quantity (streamflow, groundwater) and water-quality datasets.
- Decide whether this adapter fetches-through per query (slow, always
  current) or caches a periodic local extract (fast, needs a refresh job).
- Confirm the EEA reuse/redistribution terms for the specific datasets used.
"""

from __future__ import annotations

import geopandas as gpd

from hydrostations.adapters.base import BBox, StationAdapter
from hydrostations.exceptions import AdapterNotImplementedError

_LICENSE = "EEA open data (reuse per EEA data policy)"

# Coarse declared coverage: Europe (WISE-SoE's WFD reporting scope), not a
# verified service area -- for hydrostations.coverage's static lookup only.
_COVERAGE_BBOXES = (BBox(min_lon=-25.0, min_lat=34.0, max_lon=45.0, max_lat=71.0),)


class WiseAdapter(StationAdapter):
    network = "WISE"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("Q", "GW", "other")
    coverage = _COVERAGE_BBOXES

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        raise AdapterNotImplementedError(
            "WISE adapter is not implemented yet: WISE-SoE data is "
            "distributed as bulk EEA data-catalogue downloads, not a "
            "queryable station-list API. See module docstring for what's "
            "needed before this can be built."
        )
