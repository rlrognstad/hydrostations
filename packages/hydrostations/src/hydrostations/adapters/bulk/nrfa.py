"""National River Flow Archive (NRFA, UKCEH) adapter.

Clean JSON REST (`station-info` web service), but NOT the SOS+WaterML2 the
original design spec assumed -- and it has no server-side spatial filter:
`station=*` returns all ~1,601 stations' metadata in one call, confirmed
live. `BulkFileAdapter._filter_by_bbox()` applies the bbox client-side.

Bonus fields, both confirmed live: `catchment-area` maps directly to the
`Station` schema's `catchment_area_km2` (first source to populate that
previously-always-null placeholder), and `gdf-start-date`/`gdf-end-date`
give a real `first_obs`/`last_obs`.

Streamflow only (Q). NRFA's terms restrict caching API responses beyond
30 days except for performance -- relevant for any downstream caching
layer built on top of hydrostations, not enforced by this adapter itself.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.register.models import NrfaConfig
from hydrostations.schema import parse_timestamp, stations_frame_from_records


class NrfaAdapter(BulkFileAdapter):
    protocol = "nrfa_ws"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if compartment is not None and compartment not in self.compartments:
            return stations_frame_from_records([])

        cfg = self.entry.nrfa
        response = httpx.get(
            self.entry.endpoint,
            params={
                "format": "json-object",
                "station": "*",
                "fields": ",".join(cfg.fields),
            },
            timeout=60.0,
        )
        response.raise_for_status()
        rows = response.json().get("data", [])

        c = compartment or self.compartments[0]
        records = [self._row_to_record(row, c, cfg) for row in rows]
        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _row_to_record(self, row: dict, compartment: str, cfg: NrfaConfig) -> dict:
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": str(row[cfg.id_field]),
            "name": row.get(cfg.name_field),
            "lon": row[cfg.lon_field],
            "lat": row[cfg.lat_field],
            "compartment": compartment,
            "variables": [],
            "catchment_area_km2": row.get("catchment-area"),
            "first_obs": parse_timestamp(row.get("gdf-start-date")),
            "last_obs": parse_timestamp(row.get("gdf-end-date")),
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }
