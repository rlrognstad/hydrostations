"""GRDC (Global Runoff Data Centre) adapter.

The documented access path is a web portal (portal.grdc.bafg.de) that
requires accepting the GRDC Data Sharing Conditions and emails a download
link within 24h -- not something a synchronous `fetch_stations()` call can
use. Live investigation found a second, genuinely open path: the station
catalogue itself (`GRDC_Stations.xlsx`, zipped) is served anonymously over
FTP (`ftp.bafg.de`), no login, no click-through. This adapter only reaches
that catalogue -- discharge series retrieval isn't implemented in this
library yet for any source, so the portal's stricter series-access terms
don't currently matter here, only the catalogue's.

11,416 real stations confirmed in the 2025-07-24 snapshot (global, every
WMO region), lat/long always present. `area`/`altitude` both use `-999` as
a documented missing-value sentinel (474 and 4,158 stations respectively)
-- handled as null, same pattern as GHCN-Daily's `-999.9`. `first_obs`/
`last_obs` come from `t_start`/`t_end` (the combined daily+monthly record
envelope, always populated, year precision only) rather than the `d_*`/
`m_*` fields, which are null for stations that only have one record type.

Fetching is FTP, not HTTP -- `_fetch_zip_bytes()` isolates the one call
that reaches the network (via `urllib.request`, stdlib, no new HTTP-client
dependency) so tests can monkeypatch it directly; there's no respx-style
transport mock for FTP the way every other bulk adapter's tests use for
HTTP.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile

import geopandas as gpd
import pandas as pd

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import stations_frame_from_records

_MISSING_VALUE_SENTINEL = -999


class GrdcAdapter(BulkFileAdapter):
    protocol = "grdc_ftp"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if compartment is not None and compartment not in self.compartments:
            return stations_frame_from_records([])

        table = self._fetch_catalogue()
        records = [self._row_to_record(row) for row in table.to_dict("records")]
        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _fetch_catalogue(self) -> pd.DataFrame:
        data = self._fetch_zip_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with zf.open(self.entry.grdc.xlsx_member) as f:
                return pd.read_excel(f)

    def _fetch_zip_bytes(self) -> bytes:
        with urllib.request.urlopen(self.entry.endpoint, timeout=60) as response:
            return response.read()

    def _row_to_record(self, row: dict) -> dict:
        area = row.get("area")
        altitude = row.get("altitude")
        area_valid = area is not None and area > _MISSING_VALUE_SENTINEL
        altitude_valid = altitude is not None and altitude > _MISSING_VALUE_SENTINEL
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": str(row["grdc_no"]),
            "name": row.get("station") or None,
            "lon": row["long"],
            "lat": row["lat"],
            "compartment": "Q",
            "variables": [],
            "elevation_m": altitude if altitude_valid else None,
            "catchment_area_km2": area if area_valid else None,
            "first_obs": f"{int(row['t_start'])}-01-01",
            "last_obs": f"{int(row['t_end'])}-12-31",
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }
