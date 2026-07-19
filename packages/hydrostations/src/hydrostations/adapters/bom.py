"""BoM Water Data Online (Australia) adapter.

BoM Water Data Online runs on a KISTERS WISKI/KiWIS backend
(https://www.bom.gov.au/waterdata/services), which exposes station lists via
a `getStationList` request returning JSON shaped as `[header_row, *rows]`.
Verified live against the real endpoint for both `Q` and `GW`.

This is genuinely a reusable protocol (KiWIS backs many agencies, per the
design spec's own source table) -- generalizing it into a shared
`KiWisAdapter` is a separate, later step. That generalization also fixes a
real fragility in the row access below: `table.itertuples()` + attribute
access only works because BoM's specific deployment happens to return
identifier-safe column headers, which isn't guaranteed for a different
KiWIS deployment. Left as-is here since this file's job right now is just
the register cutover, not the protocol generalization.
"""

from __future__ import annotations

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records


class BomAdapter(SourceAdapter):
    protocol = "kiwis"

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
        cfg = self.entry.kiwis
        params = {
            "service": "kisters",
            "type": "queryServices",
            "request": "getStationList",
            "datasource": cfg.datasource,
            "format": "json",
            "parametertype_name": cfg.parameter_type_by_compartment[compartment],
            "returnfields": ",".join(cfg.return_fields),
        }
        if bbox is not None:
            params["bbox"] = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"

        response = httpx.get(
            self.entry.endpoint, params=params, timeout=30.0, follow_redirects=True
        )
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
                    "source": self.source,
                    "source_id": getattr(row, cfg.id_field),
                    "name": getattr(row, cfg.name_field),
                    "lon": float(getattr(row, cfg.lon_field)),
                    "lat": float(getattr(row, cfg.lat_field)),
                    "compartment": compartment,
                    "variables": [cfg.parameter_type_by_compartment[compartment]],
                    "first_obs": None,
                    "last_obs": None,
                    "wsi": None,
                    "license": self.license,
                    "redistribution_ok": self.redistribution_ok,
                    "raw": row._asdict(),
                }
            )
        return records
