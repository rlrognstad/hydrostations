"""Permanent Service for Mean Sea Level (PSMSL) tide-gauge catalogue adapter.

PSMSL is the global data bank for long-term sea-level change, operated by
the National Oceanography Centre (UK) -- a research compilation of records
supplied by national authorities and research groups, not itself an
operational network (hence `source_class: research`, same category as
GGMN/ISMN).

Each PSMSL dataset directory publishes a `filelist.txt` for programmatic
use -- semicolon-separated, one line per station:
`id; latitude; longitude; name; coastline code; station code; QC flag`.
Confirmed live, anonymous, no auth. The Metric list
(`met.monthly.data/filelist.txt`, ~2,490 stations) is PSMSL's full
holdings; the RLR list (`rlr.monthly.data/filelist.txt`, ~1,620) is the
datum-continuous, quality-controlled subset recommended for trend
analysis -- which one is read is `psmsl.filelist_path` in the register
entry.

Coastal tide gauges -> `SW` (the schema's "surface water: lakes,
reservoirs, coastal"). No server-side spatial filter (one static file),
so the whole list is fetched and filtered client-side via
`BulkFileAdapter._filter_by_bbox()`, same shape as GHCN-Daily/GRDC/ISMN.

The filelist carries no period-of-record dates (the HTML station table at
psmsl.org/data/obtaining/ has a "Date" column, but that's a
data-currency/last-updated date, not a record start/end) -- first_obs/
last_obs are left null, as for BoM/WISE/WQP. The per-station QC flag
(`Y` = flagged for attention, `N` = ok) is kept in `raw`.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import stations_frame_from_records


class PsmslAdapter(BulkFileAdapter):
    protocol = "psmsl_filelist"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if compartment is not None and compartment not in self.compartments:
            return stations_frame_from_records([])

        records = [self._line_to_record(line) for line in self._fetch_filelist()]
        frame = stations_frame_from_records([r for r in records if r is not None])
        return self._filter_by_bbox(frame, bbox)

    def _fetch_filelist(self) -> list[str]:
        url = f"{self.entry.endpoint}/{self.entry.psmsl.filelist_path}"
        response = httpx.get(url, timeout=60.0)
        response.raise_for_status()
        return [line for line in response.text.splitlines() if line.strip()]

    def _line_to_record(self, line: str) -> dict | None:
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 7:
            return None
        station_id, lat, lon, name, coastline, station_code, qc_flag = parts[:7]
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": station_id,
            "name": name or None,
            "lon": float(lon),
            "lat": float(lat),
            "compartment": "SW",
            "variables": [],
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": {
                "id": station_id,
                "latitude": lat,
                "longitude": lon,
                "name": name,
                "coastline": coastline,
                "station": station_code,
                "qc_flag": qc_flag,
            },
        }
