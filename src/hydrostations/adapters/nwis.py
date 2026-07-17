"""USGS NWIS (National Water Information System) adapter.

Uses the NWIS Site Web Service (https://waterservices.usgs.gov/nwis/site/)
in RDB (tab-delimited) format, with `seriesCatalogOutput=true` to recover
each site's period of record for the requested parameter.

NWIS also rejects any bBox request larger than ~25 square degrees (400
error). `_COVERAGE_BBOXES` avoids the common case -- a query bbox entirely
outside the US -- but a large *in-coverage* bbox (e.g. all of CONUS) can
still exceed the limit; tiling such requests isn't implemented yet.
"""

from __future__ import annotations

import io

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, StationAdapter, bboxes_intersect
from hydrostations.schema import stations_frame_from_records

_BASE_URL = "https://waterservices.usgs.gov/nwis/site/"

# Coarse coverage area (CONUS + AK/HI/PR). Used to skip fetching entirely
# when the requested bbox can't possibly intersect NWIS data -- otherwise a
# bbox this large would also trip NWIS's own bounding-box size limit (~25
# sq. degrees; larger requests 400).
_COVERAGE_BBOXES = (
    BBox(min_lon=-125.0, min_lat=24.0, max_lon=-66.0, max_lat=50.0),  # CONUS
    BBox(min_lon=-170.0, min_lat=51.0, max_lon=-129.0, max_lat=72.0),  # Alaska
    BBox(min_lon=-160.0, min_lat=18.0, max_lon=-154.0, max_lat=23.0),  # Hawaii
    BBox(min_lon=-68.0, min_lat=17.0, max_lon=-65.0, max_lat=19.0),  # Puerto Rico
)

# NWIS site-type codes for the compartments this adapter supports.
_SITE_TYPES = {
    "Q": "ST",  # stream
    "GW": "GW",  # groundwater well
}

# Parameter codes used to determine each site's period of record.
_PARM_CODES = {
    "Q": "00060",  # discharge, cubic feet per second
    "GW": "72019",  # depth to water level, feet below land surface
}

_LICENSE = "Public domain (U.S. Geological Survey)"


class NwisAdapter(StationAdapter):
    network = "NWIS"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("Q", "GW")

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if bbox is not None and not any(bboxes_intersect(bbox, c) for c in _COVERAGE_BBOXES):
            return stations_frame_from_records([])

        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments:
                continue
            records.extend(self._fetch_compartment(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_compartment(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        params = {
            "format": "rdb",
            "siteType": _SITE_TYPES[compartment],
            "siteStatus": "all",
            # NWIS rejects siteOutput=expanded combined with
            # seriesCatalogOutput=true ("feature not supported"); basic
            # output still carries station_nm/dec_lat_va/dec_long_va.
            "siteOutput": "basic",
            "seriesCatalogOutput": "true",
            "parameterCd": _PARM_CODES[compartment],
        }
        if bbox is not None:
            params["bBox"] = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"

        response = httpx.get(_BASE_URL, params=params, timeout=30.0)
        response.raise_for_status()
        table = _parse_rdb(response.text)
        if table.empty:
            return []

        grouped = table.groupby("site_no", as_index=False).agg(
            station_nm=("station_nm", "first"),
            dec_lat_va=("dec_lat_va", "first"),
            dec_long_va=("dec_long_va", "first"),
            begin_date=("begin_date", "min"),
            end_date=("end_date", "max"),
        )

        records = []
        for row in grouped.itertuples(index=False):
            records.append(
                {
                    "station_id": row.site_no,
                    "name": row.station_nm,
                    "lon": float(row.dec_long_va),
                    "lat": float(row.dec_lat_va),
                    "compartment": compartment,
                    "network": self.network,
                    "start_date": pd.to_datetime(row.begin_date, errors="coerce"),
                    "end_date": pd.to_datetime(row.end_date, errors="coerce"),
                    "wsi": None,
                    "license": self.license,
                    "redistribution_ok": self.redistribution_ok,
                }
            )
        return records


def _parse_rdb(text: str) -> pd.DataFrame:
    """Parse NWIS RDB tab-delimited output into a DataFrame.

    RDB format: comment lines starting with `#`, then a header line, then a
    format-code line (e.g. `5s\\t15s\\t...`) that must be dropped, then data.
    """
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    if len(lines) < 2:
        return pd.DataFrame()
    buf = io.StringIO("\n".join([lines[0], *lines[2:]]))
    return pd.read_csv(buf, sep="\t", dtype=str)
