"""Generic KISTERS WISKI/KiWIS protocol adapter.

KiWIS is not an open standard, but it's a *platform* running under a large
number of hydrological agencies (proven here by BoM's real deployment) --
a new agency on this protocol is a register entry, not a new Python class.
Endpoint, `datasource`, field names, and the parameter-type-name per
compartment all come from the register entry's `kiwis` config block.

Row access is deliberately NOT `DataFrame.itertuples()` + attribute access:
that only works if the API's own column headers happen to be
identifier-safe Python attribute names, which isn't guaranteed across
different KiWIS deployments (a header with a space, for example, would
silently break or mangle). Building a `dict(zip(header, row))` per record
and indexing by the configured field name avoids that fragility.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records


class KiWisAdapter(SourceAdapter):
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
        records = (dict(zip(header, row, strict=True)) for row in rows)
        return [
            self._row_to_record(r, compartment)
            for r in records
            # A minority of rows come back with an empty-string lon/lat
            # (confirmed live: BoM, queried with no bbox at all) -- a
            # station with no location isn't usable data, so skip it
            # rather than crash on float('').
            if r.get(cfg.lon_field) and r.get(cfg.lat_field)
        ]

    def _row_to_record(self, row: dict[str, str], compartment: str) -> dict:
        cfg = self.entry.kiwis
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": row[cfg.id_field],
            "name": row.get(cfg.name_field),
            "lon": float(row[cfg.lon_field]),
            "lat": float(row[cfg.lat_field]),
            "compartment": compartment,
            "variables": [cfg.parameter_type_by_compartment[compartment]],
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }
