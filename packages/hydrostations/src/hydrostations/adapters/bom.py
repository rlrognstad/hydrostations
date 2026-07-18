"""BoM Water Data Online (Australia) adapter.

BoM Water Data Online runs on a KISTERS WISKI/KiWIS backend
(https://www.bom.gov.au/waterdata/services), which exposes station lists via
a `getStationList` request returning JSON shaped as `[header_row, *rows]`.
Verified live against the real endpoint for both `Q` and `GW`.
"""

from __future__ import annotations

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, StationAdapter
from hydrostations.schema import stations_frame_from_records

_BASE_URL = "https://www.bom.gov.au/waterdata/services"

_PARAMETER_TYPES = {
    "Q": "Water Course Discharge",
    "GW": "Ground Water Level",
}

_LICENSE = "CC BY 4.0 (Bureau of Meteorology, Australia)"

_RETURN_FIELDS = (
    "station_no,station_name,station_latitude,station_longitude,"
    "station_id,object_type,parametertype_name"
)


class BomAdapter(StationAdapter):
    network = "BOM"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("Q", "GW")

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments:
                continue
            records.extend(self._fetch_compartment(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_compartment(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        params = {
            "service": "kisters",
            "type": "queryServices",
            "request": "getStationList",
            "datasource": "0",
            "format": "json",
            "parametertype_name": _PARAMETER_TYPES[compartment],
            "returnfields": _RETURN_FIELDS,
        }
        if bbox is not None:
            params["bbox"] = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"

        response = httpx.get(_BASE_URL, params=params, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
        if not payload or len(payload) < 2:
            return []

        header, *rows = payload
        table = pd.DataFrame(rows, columns=header)

        records = []
        for row in table.itertuples(index=False):
            records.append(
                {
                    "station_id": row.station_no,
                    "name": row.station_name,
                    "lon": float(row.station_longitude),
                    "lat": float(row.station_latitude),
                    "compartment": compartment,
                    "network": self.network,
                    "start_date": None,
                    "end_date": None,
                    "wsi": None,
                    "license": self.license,
                    "redistribution_ok": self.redistribution_ok,
                }
            )
        return records
