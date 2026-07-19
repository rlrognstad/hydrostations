"""SIEREM (HydroSciences Montpellier) adapter -- not yet implemented.

SIEREM (http://www.hydrosciences.fr/sierem/) is a static data portal, not a
queryable API. Investigation found ~647 real per-basin/per-station-type KML
files with individual station placemarks (id, name, coordinates, country) --
genuinely structured and machine-readable, just not a REST endpoint. No
server-side spatial filtering exists, so this needs a bulk-fetch-then-filter
design (the `bulk_kml` protocol / `BulkFileAdapter` archetype), not a simple
per-query adapter -- see `hydrostations.adapters.bulk`.

Not yet implemented.
"""

from __future__ import annotations

import geopandas as gpd

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.exceptions import AdapterNotImplementedError


class SieremAdapter(SourceAdapter):
    protocol = "bulk_kml"

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
