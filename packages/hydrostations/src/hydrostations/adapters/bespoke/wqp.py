"""USGS / EPA Water Quality Portal (waterqualitydata.us) adapter.

The Station search service
(https://www.waterqualitydata.us/data/Station/search) returns a
monitoring-location inventory as CSV -- anonymous, no auth, no API key.
It's a real server-side spatial filter: `bBox=min_lon,min_lat,max_lon,
max_lat` returns only locations inside the box. Confirmed live. This is
the joint USGS/EPA/NWQMC aggregator, distinct from NWIS's own site
service and from EPA's WQX web services.

The whole matching set streams back in one CSV response -- there is no
pagination and (unlike NWIS) no bbox-size limit; a continental bbox
really does return millions of rows in a single ~100 MB response, so
`timeout` is generous and a broad query is genuinely slow. Called with no
bbox, the adapter issues one request per declared coverage box rather
than an unfiltered pull (the service rejects a query carrying no
spatial/attribute filter).

Populates `WQ`, the last compartment in `COMPARTMENTS` that had no
source. Every monitoring-location type (streams, wells, springs, lakes,
atmosphere, treatment facilities, CERCLA sites) is a water-quality site
by definition of the portal, so there's no site-type filter -- one query
per box covers the compartment.

first_obs/last_obs are left null: the Station service carries no
period-of-record (sample dates live in the separate, far larger Result
service, which this library doesn't fetch for any source yet), same as
BoM and WISE. elevation_m is filled from `VerticalMeasure/MeasureValue`
where present (~two-thirds of rows), converting `feet`/`ft` to metres.
Coordinate datum varies per row (NAD83 / WGS84 / NAD27 / unknown) and is
not reprojected -- treated as WGS84 degrees, consistent with this
register's coarse positional handling elsewhere.

WQP re-serves USGS NWIS sites (provider `NWIS`, ids like `USGS-01646500`)
alongside EPA WQX sites; those overlap the `nwis` source's Q/GW records
but are a different compartment (WQ) and a different `source`/`source_id`
shape, and this register does not deduplicate across sources
(`canonical_id` is provisional).

Bespoke (not a generalized protocol adapter): WQP's CSV shape is specific
to this one platform, no second known user.
"""

from __future__ import annotations

import io

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records

_FEET_UNITS = {"feet", "ft"}
_METRE_UNITS = {"m", "meter", "meters", "metre", "metres"}
_FOOT_TO_M = 0.3048


class WqpAdapter(SourceAdapter):
    protocol = "wqp_station"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if compartment is not None and compartment not in self.compartments:
            return stations_frame_from_records([])
        if self._skip_out_of_coverage(bbox):
            return stations_frame_from_records([])

        boxes = [bbox] if bbox is not None else list(self.coverage)
        records: list[dict] = []
        for box in boxes:
            records.extend(self._fetch_box(box))
        return stations_frame_from_records(records)

    def _fetch_box(self, box: BBox) -> list[dict]:
        params = {
            "mimeType": "csv",
            "zip": "no",
            "bBox": f"{box.min_lon},{box.min_lat},{box.max_lon},{box.max_lat}",
        }
        response = httpx.get(self.entry.endpoint, params=params, timeout=300.0)
        response.raise_for_status()
        table = pd.read_csv(io.StringIO(response.text), dtype=str)
        if table.empty:
            return []
        return [self._row_to_record(row) for row in table.to_dict("records")]

    def _row_to_record(self, row: dict) -> dict:
        row = {k: (None if pd.isna(v) else v) for k, v in row.items()}
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": row["MonitoringLocationIdentifier"],
            "name": row.get("MonitoringLocationName"),
            "lon": float(row["LongitudeMeasure"]),
            "lat": float(row["LatitudeMeasure"]),
            "compartment": "WQ",
            "variables": [],
            "elevation_m": _elevation_m(
                row.get("VerticalMeasure/MeasureValue"),
                row.get("VerticalMeasure/MeasureUnitCode"),
            ),
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }


def _elevation_m(value: str | None, unit: str | None) -> float | None:
    """Convert a WQP `VerticalMeasure` value+unit to metres, or None.

    Units seen live: `feet`, `ft`, `m` (and blanks). Anything unrecognized
    is treated as missing rather than assumed."""
    if value is None or unit is None:
        return None
    try:
        magnitude = float(value)
    except (TypeError, ValueError):
        return None
    normalized = str(unit).strip().lower()
    if normalized in _FEET_UNITS:
        return magnitude * _FOOT_TO_M
    if normalized in _METRE_UNITS:
        return magnitude
    return None
