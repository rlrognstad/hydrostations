"""HidroWeb (ANA, Brazil) adapter -- not yet implemented.

ANA's current Hidroweb service (hidrowebservice) requires an OAuth-style
token obtained via an authenticated endpoint before station queries can be
made -- it isn't an open, unauthenticated REST API the way NWIS is.

Before implementing:

- Confirm the current auth flow (ANA has revised the Hidroweb API more than
  once; the older SOAP service and the newer REST service have different
  credential requirements).
- Decide how a user supplies their own ANA credentials -- this package
  shouldn't ship or proxy a shared account.
- Confirm field names for station metadata and period-of-record once auth
  is sorted out.
"""

from __future__ import annotations

import geopandas as gpd

from hydrostations.adapters.base import BBox, StationAdapter
from hydrostations.exceptions import AdapterNotImplementedError

_LICENSE = "ANA open data (Brazilian government open data)"

# Coarse declared coverage: Brazil, not a verified service area -- for
# hydrostations.coverage's static lookup only.
_COVERAGE_BBOXES = (BBox(min_lon=-74.0, min_lat=-34.0, max_lon=-34.0, max_lat=5.5),)


class HidroWebAdapter(StationAdapter):
    network = "HIDROWEB"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("Q", "P")
    coverage = _COVERAGE_BBOXES

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        raise AdapterNotImplementedError(
            "HidroWeb adapter is not implemented yet: ANA's current service "
            "requires per-user authentication that this package doesn't yet "
            "have a design for. See module docstring for what's needed "
            "before this can be built."
        )
