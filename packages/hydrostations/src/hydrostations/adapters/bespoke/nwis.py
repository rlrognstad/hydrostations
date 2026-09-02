"""USGS NWIS (National Water Information System) adapter.

Uses the NWIS Site Web Service (https://waterservices.usgs.gov/nwis/site/)
in RDB (tab-delimited) format, with `seriesCatalogOutput=true` to recover
each site's period of record for the requested parameter.

NWIS also rejects any bBox request larger than ~25 square degrees (400
error). The register's `skip_out_of_coverage` flag (set for this source
only) avoids the common case -- a query bbox entirely outside the US -- but
a large *in-coverage* bbox (e.g. all of CONUS) can still exceed the limit;
tiling such requests isn't implemented yet.

Bespoke (not a generalized protocol adapter): RDB is USGS-specific, no
second known user, so there's no reuse payoff in abstracting it. Config
(site types, parameter codes) still comes from the register entry rather
than module constants.
"""

from __future__ import annotations

import io

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records

_BASE_URL = "https://waterservices.usgs.gov/nwis/site/"


class NwisAdapter(SourceAdapter):
    protocol = "nwis_rdb"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if self._skip_out_of_coverage(bbox):
            return stations_frame_from_records([])

        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments:
                continue
            records.extend(self._fetch_compartment(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_compartment(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        cfg = self.entry.nwis
        # A compartment may map to several parameter codes -- SW (lakes/
        # reservoirs) spans the water-surface-elevation family plus storage,
        # which NWIS reports under different codes by vertical datum. NWIS
        # accepts the comma-separated list verbatim; `variables` gets it
        # split back out.
        param_codes = cfg.param_code_by_compartment[compartment]
        params = {
            "format": "rdb",
            "siteType": cfg.site_type_by_compartment[compartment],
            "siteStatus": "all",
            # NWIS rejects siteOutput=expanded combined with
            # seriesCatalogOutput=true ("feature not supported"); basic
            # output still carries station_nm/dec_lat_va/dec_long_va.
            "siteOutput": "basic",
            "seriesCatalogOutput": "true",
            "parameterCd": param_codes,
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
                    "source": self.source,
                    "source_class": self.source_class,
                    "source_id": row.site_no,
                    "name": row.station_nm,
                    "lon": float(row.dec_long_va),
                    "lat": float(row.dec_lat_va),
                    "compartment": compartment,
                    "variables": param_codes.split(","),
                    "first_obs": pd.to_datetime(row.begin_date, errors="coerce"),
                    "last_obs": pd.to_datetime(row.end_date, errors="coerce"),
                    "wsi": None,
                    "license": self.license,
                    "redistribution_ok": self.redistribution_ok,
                    "raw": row._asdict(),
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
