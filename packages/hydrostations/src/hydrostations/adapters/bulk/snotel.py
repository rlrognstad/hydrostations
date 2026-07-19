"""SNOTEL / SCAN (USDA NRCS AWDB) adapter.

Clean JSON REST (AWDB REST API v1), no auth. Confirmed live: the API has
no true bbox/lat-lon spatial filter -- unrecognized query params (bbox,
lat/lon ranges) are silently ignored and the *entire* multi-network
station list (4,000+ stations) comes back regardless. The only real
server-side filter is `stationTriplets`, a comma-separated
`stationId:stateCode:networkCode` pattern that accepts `*` wildcards --
`*:*:SNTL` (confirmed live: 913 real stations) genuinely filters to the
SNOTEL network server-side. `BulkFileAdapter._filter_by_bbox()` handles
the actual spatial trim client-side, same shape as NRFA.

Two networks under one platform map to two compartments that had zero
sources before this adapter: SNTL (SNOTEL proper) -> SNOW, SCAN (Soil
Climate Analysis Network) -> SM. Each compartment is still its own live
request (`network_code_by_compartment`), not a single fetch-all -- unlike
NRFA, AWDB's own network filter is real and worth using.

`elevation` is in feet (confirmed against known Colorado high-altitude
sites, e.g. ~11,290 ft, not plausible in meters) -- converted to
`elevation_m`. `endDate` uses "2100-01-01" as a sentinel for "still
active" (confirmed on every currently-active station sampled); treated as
no end date rather than a real one.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import parse_timestamp, stations_frame_from_records

_FEET_TO_METERS = 0.3048
_NO_END_DATE_SENTINEL = "2100-01-01"


class SnotelAdapter(BulkFileAdapter):
    protocol = "snotel_awdb"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.snotel
        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments or c not in cfg.network_code_by_compartment:
                continue
            records.extend(self._fetch_compartment(c))
        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _fetch_compartment(self, compartment: str) -> list[dict]:
        cfg = self.entry.snotel
        network = cfg.network_code_by_compartment[compartment]
        response = httpx.get(
            self.entry.endpoint,
            params={"stationTriplets": f"*:*:{network}", "activeOnly": "true"},
            timeout=60.0,
        )
        response.raise_for_status()
        return [self._row_to_record(row, compartment) for row in response.json()]

    def _row_to_record(self, row: dict, compartment: str) -> dict:
        elevation_ft = row.get("elevation")
        end_date = row.get("endDate")
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": row["stationTriplet"],
            "name": row.get("name"),
            "lon": row["longitude"],
            "lat": row["latitude"],
            "compartment": compartment,
            "variables": [],
            "elevation_m": elevation_ft * _FEET_TO_METERS if elevation_ft is not None else None,
            "first_obs": parse_timestamp(row.get("beginDate")),
            "last_obs": (
                None if end_date is None or end_date.startswith(_NO_END_DATE_SENTINEL)
                else parse_timestamp(end_date)
            ),
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }
