"""Generic OGC WFS 2.0 protocol adapter.

WFS 2.0 is a real, widely-used OGC standard -- GeoServer backs a lot of
government open data (proven here by GGMN's real deployment). A new
agency on this protocol is a register entry, not a new Python class.
Endpoint, page size, and per-compartment collection config (type name,
id/name/start/end field names) all come from the register entry's `wfs`
config block.

`sort_by` is an optional workaround knob, not a spec requirement: some
GeoServer deployments (verified on GGMN's) throw a server-side
NullPointerException when `startIndex` is combined with a `bbox` filter
but no explicit sort. A future WFS source without that bug just omits it.

Timestamp normalization (tz-aware "...Z" input -> tz-naive output, to
match the shared schema's naive datetime64[ns] columns) is handled via
`schema.parse_timestamp()` -- a genuinely cross-adapter concern (Hub'Eau
needs the same normalization for a different reason: date-only strings),
not WFS/GGMN-specific.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.register.models import WfsCollectionConfig
from hydrostations.schema import parse_timestamp, stations_frame_from_records


class WfsAdapter(SourceAdapter):
    protocol = "wfs"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.wfs
        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments or c not in cfg.collections:
                continue
            records.extend(self._fetch_collection(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_collection(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        cfg = self.entry.wfs
        collection = cfg.collections[compartment]
        records = []
        start_index = 0
        while True:
            params = {
                "service": "WFS",
                "version": cfg.version,
                "request": "GetFeature",
                "typeNames": collection.type_name,
                "outputFormat": "application/json",
                "count": str(cfg.page_size),
                "startIndex": str(start_index),
            }
            if cfg.sort_by:
                params["sortBy"] = cfg.sort_by
            if bbox is not None:
                params["bbox"] = (
                    f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat},EPSG:4326"
                )

            response = httpx.get(self.entry.endpoint, params=params, timeout=60.0)
            response.raise_for_status()
            features = response.json().get("features", [])
            records.extend(
                self._feature_to_record(f, compartment, collection) for f in features
            )

            if len(features) < cfg.page_size:
                break
            start_index += cfg.page_size

        return records

    def _feature_to_record(
        self, feature: dict, compartment: str, collection: WfsCollectionConfig
    ) -> dict:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        return {
            "source": self.source,
            "source_id": str(props[collection.id_field]),
            "name": props.get(collection.name_field),
            "lon": lon,
            "lat": lat,
            "compartment": compartment,
            "variables": [],
            "first_obs": parse_timestamp(props.get(collection.start_field)),
            "last_obs": parse_timestamp(props.get(collection.end_field)),
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": props,
        }
