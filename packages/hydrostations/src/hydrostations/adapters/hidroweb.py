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
doesn't guarantee `MedicaoDescargaLiquida` is "Sim") -- start_date/end_date
are left null here rather than guess, same as BoM.

`maxRecordCount` is 1000; paginated via `resultOffset`.

Licensing: the dataset's own metadata states "É permitida a reprodução de
dados e de informações, desde que citada a fonte" (reproduction permitted,
attribution required) -- not a named license (e.g. not literally CC BY),
but functionally an attribution-required open policy.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, StationAdapter
from hydrostations.schema import stations_frame_from_records

_BASE_URL = (
    "https://portal1.snirh.gov.br/server/rest/services/"
    "Esta%C3%A7%C3%B5es_Hidrometeorol%C3%B3gicas_SNIRH/FeatureServer/0/query"
)
_PAGE_SIZE = 1000

_LICENSE = (
    'Reproduction permitted with attribution ("E permitida a reproducao de '
    'dados e de informacoes, desde que citada a fonte"), Agencia Nacional '
    "de Aguas e Saneamento Basico (ANA) / SNIRH -- "
    "see https://dadosabertos.ana.gov.br"
)

# Coarse declared coverage: Brazil.
_COVERAGE_BBOXES = (BBox(min_lon=-74.0, min_lat=-34.0, max_lon=-34.0, max_lat=5.5),)

# TipoEstacao values (verified live -- exactly these two exist).
_STATION_TYPES = {
    "Q": "Fluviométrica",
    "P": "Pluviométrica",
}


class HidroWebAdapter(StationAdapter):
    network = "HIDROWEB"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("Q", "P")
    coverage = _COVERAGE_BBOXES

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
        params = {
            "where": f"TipoEstacao='{_STATION_TYPES[compartment]}'",
            "outFields": "Codigo,Nome,TipoEstacao",
            "f": "geojson",
            "resultRecordCount": str(_PAGE_SIZE),
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
                _BASE_URL, params={**params, "resultOffset": str(offset)}, timeout=30.0
            )
            response.raise_for_status()
            features = response.json().get("features", [])
            records.extend(_feature_to_record(f, compartment, self.license) for f in features)

            if len(features) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        return records


def _feature_to_record(feature: dict, compartment: str, license_text: str) -> dict:
    props = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"]
    return {
        "station_id": str(props["Codigo"]),
        "name": props.get("Nome"),
        "lon": lon,
        "lat": lat,
        "compartment": compartment,
        "network": "HIDROWEB",
        "start_date": None,
        "end_date": None,
        "wsi": None,
        "license": license_text,
        "redistribution_ok": True,
    }
