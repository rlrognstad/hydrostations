"""CoCoRaHS (Community Collaborative Rain, Hail & Snow Network) adapter.

Volunteer observer network, US-focused, covering both P and SNOW: the
same daily report form (and so the same station list) carries rainfall,
hail, *and* snowfall/snow-depth observations -- there is no separate
"snow network" of different stations, so both compartments are emitted
from one fetch per state rather than two.

Confirmed live: `api2.cocorahs.org`'s documented Web API requires an API
key ("Authorization has been denied for this request" without one) --
but a separate, genuinely anonymous XML export endpoint
(`data.cocorahs.org/cocorahs/export/exportstations.aspx`) is real and
unauthenticated. It has no bbox filter and no "all states" mode
(`state=a` crashed the server with an OutOfMemoryException) -- only a
real per-state filter, so the full inventory is one request per
jurisdiction (see the register entry's `cocorahs.states` list),
aggregated, then filtered client-side via
`BulkFileAdapter._filter_by_bbox()`, same shape as NRFA/SNOTEL. Each
state is fetched once regardless of how many compartments are
requested -- the per-state fetch is the expensive part (~38s for all
51 jurisdictions), duplicating it per compartment would double that for
no reason since the same response covers both.

Real gotcha, confirmed live: the "currently reporting" status string is
"Reporting", not "Active" -- a naive "Active" filter silently returns
zero stations (Colorado alone: 0 stations with status "Active" vs 1,967
real "Reporting" stations out of 8,969 total, the rest mostly "Closed").

`Elevation` is in feet (same convention confirmed for SNOTEL/SCAN) --
converted to `elevation_m`. No clean period-of-record field exists on
this export (`CreationDate`/`DateTimeStamp` are record-management
timestamps, not observation dates); `first_obs`/`last_obs` are left
null, same as WISE/BoM.
"""

from __future__ import annotations

from xml.etree import ElementTree

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import stations_frame_from_records

_FEET_TO_METERS = 0.3048
_REPORTING_STATUS = "Reporting"


class CocorahsAdapter(BulkFileAdapter):
    protocol = "cocorahs_export"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        compartments = [compartment] if compartment else list(self.compartments)
        compartments = [c for c in compartments if c in self.compartments]
        if not compartments:
            return stations_frame_from_records([])

        records = []
        for state in self.entry.cocorahs.states:
            stations = self._fetch_state_stations(state)
            for station in stations:
                records.extend(self._station_to_record(station, c) for c in compartments)
        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _fetch_state_stations(self, state: str) -> list[ElementTree.Element]:
        response = httpx.get(
            self.entry.endpoint,
            params={"format": "v", "state": state},
            timeout=60.0,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        return [
            station
            for station in root.iter("Station")
            if station.findtext("StationStatus") == _REPORTING_STATUS
        ]

    def _station_to_record(self, station: ElementTree.Element, compartment: str) -> dict:
        raw = {child.tag: child.text for child in station}
        elevation_ft = raw.get("Elevation")
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": raw["StationNumber"],
            "name": raw.get("StationName"),
            "lon": float(raw["Longitude"]),
            "lat": float(raw["Latitude"]),
            "compartment": compartment,
            "variables": [],
            "elevation_m": float(elevation_ft) * _FEET_TO_METERS if elevation_ft else None,
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": raw,
        }
