"""SIEREM (HydroSciences Montpellier) adapter -- not yet implemented.

SIEREM (http://www.hydrosciences.fr/sierem/) is a static data portal, not a
queryable API -- data is retrieved via the portal's map/download interface
rather than a REST endpoint.

Before implementing:

- Confirm whether SIEREM exposes any machine-readable bulk export (CSV,
  shapefile) versus requiring interactive portal navigation.
- If only interactive/manual export exists, this adapter may need to work
  from a periodically-refreshed static extract rather than a live fetch,
  which changes its shape relative to the other adapters.
- Confirm the exact wording SIEREM's citation requirement expects in the
  `license` field.
"""

from __future__ import annotations

import geopandas as gpd

from hydrostations.adapters.base import BBox, StationAdapter
from hydrostations.exceptions import AdapterNotImplementedError

_LICENSE = "Open, citation required (SIEREM / HydroSciences Montpellier)"


class SieremAdapter(StationAdapter):
    network = "SIEREM"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("Q", "P")

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        raise AdapterNotImplementedError(
            "SIEREM adapter is not implemented yet: SIEREM is a static "
            "portal with no queryable station-list API. See module "
            "docstring for what's needed before this can be built."
        )
