"""HidroWeb / SNIRH (ANA, Brazil) adapter.

ANA's modern `hidrowebservice` REST API does require an auth token, but
that's only for downloading actual time-series values. The station
*inventory* -- location, name, type, what's operational -- is served
separately, openly, through a standard Esri ArcGIS Feature Service on
ANA's SNIRH open-data platform (portal1.snirh.gov.br), no auth, verified
live: 40,576 real stations nationwide, bbox-queryable, GeoJSON output.

Compartment is derived from the `TipoEstacao` field (verified live, exactly
two values exist): "Fluviométrica" (streamflow) -> Q, "Pluviométrica"
(rain gauge) -> P.

The service's field list also carries per-measurement-type operational
date ranges (e.g. `MedicaoDescargaLiquidaInicio`/`...Fim`), but which
field is the "right" one for a given station's actual period of record is
ambiguous from the inventory alone (a Fluviométrica station's `TipoEstacao`
doesn't guarantee `MedicaoDescargaLiquida` is "Sim") -- first_obs/last_obs
are left null here rather than guess, same as BoM.

`maxRecordCount` is 1000; paginated via `resultOffset`.

This is genuinely a reusable protocol (Esri ArcGIS Feature Server is common
among government open-data portals worldwide) -- generalizing it into a
shared `ArcGisFeatureServerAdapter` is a separate, later step. For now this
still reads its config from the register entry rather than module
constants.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records


class HidroWebAdapter(SourceAdapter):
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
        return {
            "source": self.source,
            "source_id": str(props[cfg.id_field]),
            "name": props.get(cfg.name_field),
            "lon": lon,
            "lat": lat,
            "compartment": compartment,
            "variables": [props.get("TipoEstacao")] if props.get("TipoEstacao") else [],
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": props,
        }
