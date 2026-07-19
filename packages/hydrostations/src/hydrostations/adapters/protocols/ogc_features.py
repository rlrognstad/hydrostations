"""Generic OGC API-Features protocol adapter.

OGC API-Features is the standard the hydrometric field is converging on --
confirmed live on two independent agencies during this adapter's build:
ECCC's Water Survey of Canada (api.weather.gc.ca) and USGS's modernized
endpoint (api.waterdata.usgs.gov/ogcapi/v0). Only ECCC is registered as a
source today; a new agency on this standard is a register entry, not a new
Python class.

Pagination is the standard offset/limit form: `numberReturned < limit` (or
the absence of a `rel=next` link) signals the last page -- verified live on
ECCC's `hydrometric-stations` collection.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.register.models import OgcFeaturesCollectionConfig
from hydrostations.schema import stations_frame_from_records


class OgcFeaturesAdapter(SourceAdapter):
    protocol = "ogc_features"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.ogc_features
        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments or c not in cfg.collections:
                continue
            records.extend(self._fetch_collection(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_collection(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        cfg = self.entry.ogc_features
        collection = cfg.collections[compartment]
        records = []
        offset = 0
        while True:
            params = {
                "f": "json",
                "limit": str(cfg.page_size),
                "offset": str(offset),
            }
            if bbox is not None:
                params["bbox"] = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"

            response = httpx.get(
                f"{self.entry.endpoint}/{collection.collection}/items",
                params=params,
                timeout=60.0,
            )
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features", [])
            records.extend(self._feature_to_record(f, compartment, collection) for f in features)

            if len(features) < cfg.page_size:
                break
            offset += cfg.page_size

        return records

    def _feature_to_record(
        self, feature: dict, compartment: str, collection: OgcFeaturesCollectionConfig
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
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": props,
        }
