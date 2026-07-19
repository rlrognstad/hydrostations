"""Generic Esri ArcGIS Feature Server protocol adapter.

Esri ArcGIS Feature Server is a common de facto standard among government
open-data portals worldwide (proven here by HidroWeb/SNIRH's real, no-auth
deployment) -- a new agency on this protocol is a register entry, not a
new Python class. Everything agency-specific (endpoint, field names,
where-clause per compartment, and the optional "native variable" field)
comes from the register entry's `arcgis` config block.

Bbox params (`geometryType=esriGeometryEnvelope`, `inSR=4326`,
`spatialRel=esriSpatialRelIntersects`), `f=geojson`, and `resultOffset`
pagination are fixed here as genuine Esri REST mechanics, not
configurable -- they don't vary by deployment.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records


class ArcGisFeatureServerAdapter(SourceAdapter):
    protocol = "arcgis_feature_server"

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
        cfg = self.entry.arcgis
        params = {
            "where": cfg.where_by_compartment[compartment],
            "outFields": ",".join(cfg.out_fields),
            "f": "geojson",
            "resultRecordCount": str(cfg.page_size),
        }
        if bbox is not None:
            params["geometry"] = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"
            params["geometryType"] = "esriGeometryEnvelope"
            params["inSR"] = "4326"
            params["spatialRel"] = "esriSpatialRelIntersects"

        records = []
        offset = 0
        while True:
            response = httpx.get(
                self.entry.endpoint, params={**params, "resultOffset": str(offset)}, timeout=30.0
            )
            response.raise_for_status()
            features = response.json().get("features", [])
            records.extend(self._feature_to_record(f, compartment) for f in features)

            if len(features) < cfg.page_size:
                break
            offset += cfg.page_size

        return records

    def _feature_to_record(self, feature: dict, compartment: str) -> dict:
        cfg = self.entry.arcgis
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        variable = props.get(cfg.variable_field) if cfg.variable_field else None
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": str(props[cfg.id_field]),
            "name": props.get(cfg.name_field),
            "lon": lon,
            "lat": lat,
            "compartment": compartment,
            "variables": [variable] if variable else [],
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": props,
        }
