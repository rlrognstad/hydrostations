"""Generic Socrata (SODA / SoQL) protocol adapter.

Socrata's Open Data API powers a large share of government open-data
portals worldwide (proven here by Colombia's datos.gov.co -- IDEAM's real,
no-auth national station catalogue). A new agency whose catalogue lives on
any Socrata domain is a register entry, not a new Python class: everything
portal-specific (domain `endpoint`, dataset id, field names, and which
native station-type values feed each compartment) comes from the entry's
`socrata` config block.

The query is standard SoQL over HTTPS: `$select` the fields actually read,
`$where` a `category in (...)` clause plus a numeric lat/lon bounding box
when one is given (real server-side spatial filtering -- so this is a
protocol adapter, not a bulk one), `$order` by id for stable
`$limit`/`$offset` paging.

No auth. Tokenless traffic is rate-limited by Socrata and a burst of
requests can transiently 429/500/503; a normal query here is only a
handful of pages, well within that.
"""

from __future__ import annotations

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import parse_timestamp, stations_frame_from_records


class SocrataAdapter(SourceAdapter):
    protocol = "socrata"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.socrata
        compartments = [compartment] if compartment else list(self.compartments)
        compartments = [
            c
            for c in compartments
            if c in self.compartments and c in cfg.category_by_compartment
        ]
        records: list[dict] = []
        for c in compartments:
            records.extend(self._fetch_compartment(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_compartment(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        cfg = self.entry.socrata
        fields = [cfg.id_field, cfg.name_field, cfg.lat_field, cfg.lon_field, cfg.category_field]
        for optional in (cfg.elevation_field, cfg.first_obs_field, cfg.last_obs_field):
            if optional and optional not in fields:
                fields.append(optional)

        categories = cfg.category_by_compartment[compartment]
        quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in categories)
        where = [f"{cfg.category_field} in ({quoted})"]
        if bbox is not None:
            where.append(f"{cfg.lat_field} between {bbox.min_lat} and {bbox.max_lat}")
            where.append(f"{cfg.lon_field} between {bbox.min_lon} and {bbox.max_lon}")

        url = f"{self.entry.endpoint}/resource/{cfg.dataset_id}.json"
        base = {
            "$select": ", ".join(fields),
            "$where": " and ".join(where),
            "$order": cfg.id_field,
            "$limit": str(cfg.page_size),
        }

        records: list[dict] = []
        offset = 0
        while True:
            response = httpx.get(url, params={**base, "$offset": str(offset)}, timeout=30.0)
            response.raise_for_status()
            rows = response.json()
            for row in rows:
                record = self._row_to_record(row, compartment)
                if record is not None:
                    records.append(record)
            if len(rows) < cfg.page_size:
                break
            offset += cfg.page_size

        return records

    def _row_to_record(self, row: dict, compartment: str) -> dict | None:
        cfg = self.entry.socrata
        try:
            lon = float(row[cfg.lon_field])
            lat = float(row[cfg.lat_field])
        except (KeyError, TypeError, ValueError):
            return None

        category = row.get(cfg.category_field)
        elevation = _to_float(row.get(cfg.elevation_field)) if cfg.elevation_field else None
        first_obs = self._parse_date(row.get(cfg.first_obs_field)) if cfg.first_obs_field else None
        last_obs = self._parse_date(row.get(cfg.last_obs_field)) if cfg.last_obs_field else None
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": str(row[cfg.id_field]),
            "name": row.get(cfg.name_field),
            "lon": lon,
            "lat": lat,
            "compartment": compartment,
            "variables": [category] if category else [],
            "elevation_m": elevation,
            "first_obs": first_obs,
            "last_obs": last_obs,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }

    def _parse_date(self, value: object) -> pd.Timestamp:
        fmt = self.entry.socrata.date_format
        if fmt is None:
            return parse_timestamp(value if isinstance(value, str) else None)
        return pd.to_datetime(value, format=fmt, errors="coerce")


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
