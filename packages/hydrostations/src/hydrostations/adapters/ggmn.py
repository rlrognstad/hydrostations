"""GGMN (Global Groundwater Monitoring Network, IGRAC) adapter.

Uses IGRAC's GeoServer WFS 2.0 endpoint (https://ggis.un-igrac.org/geoserver/ows),
querying the `groundwater:GGMN_Levels_Data` layer directly -- no auth, no MOU
needed for read access (an MOU only governs institutions contributing data
into GGMN, a different relationship than reading published records). Output
format is GeoJSON.

Paginates via `startIndex`/`count`; GeoServer here throws a server-side
NullPointerException when `startIndex` is combined with a `bbox` filter but
no explicit `sortBy` -- sorting by `id` avoids it (a real bug worked around,
not a documented requirement).

Licensing: the dataset's own metadata (constraints_other, via
https://ggis.un-igrac.org/api/v2/datasets/2472/) states CC BY-NC-SA 4.0
(Attribution-NonCommercial-ShareAlike), not the plainer "CC BY" sometimes
quoted informally -- and the license identifier itself is `varied_derived`,
since GGMN aggregates data from many national authorities who may attach
their own terms. `redistribution_ok=True` here because redistribution is
genuinely allowed, just conditioned on non-commercial use and share-alike --
conditions this package doesn't have a dedicated field for, so they live in
the `license` string for now.
"""

from __future__ import annotations

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, StationAdapter
from hydrostations.schema import stations_frame_from_records

_BASE_URL = "https://ggis.un-igrac.org/geoserver/ows"
_TYPE_NAME = "groundwater:GGMN_Levels_Data"
_PAGE_SIZE = 1000

_LICENSE = (
    "CC BY-NC-SA 4.0 (Attribution-NonCommercial-ShareAlike), International "
    "Groundwater Resources Assessment Centre (IGRAC) -- license varies by "
    "contributing national authority ('varied_derived' in source metadata); "
    "see https://ggis.un-igrac.org/catalogue/#/dataset/2472"
)

# Genuinely global network aggregating national monitoring data.
_COVERAGE_BBOXES = (BBox(min_lon=-180.0, min_lat=-90.0, max_lon=180.0, max_lat=90.0),)


class GgmnAdapter(StationAdapter):
    network = "GGMN"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("GW",)
    coverage = _COVERAGE_BBOXES

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if compartment is not None and compartment not in self.compartments:
            return stations_frame_from_records([])
        return stations_frame_from_records(self._fetch_all(bbox=bbox))

    def _fetch_all(self, *, bbox: BBox | None) -> list[dict]:
        records = []
        start_index = 0
        while True:
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": _TYPE_NAME,
                "outputFormat": "application/json",
                "count": str(_PAGE_SIZE),
                "startIndex": str(start_index),
                "sortBy": "id",
            }
            if bbox is not None:
                params["bbox"] = (
                    f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat},EPSG:4326"
                )

            response = httpx.get(_BASE_URL, params=params, timeout=60.0)
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features", [])
            records.extend(
                _feature_to_record(f, self.license, self.redistribution_ok) for f in features
            )

            if len(features) < _PAGE_SIZE:
                break
            start_index += _PAGE_SIZE

        return records


def _parse_timestamp(value: str | None) -> pd.Timestamp:
    # GGMN's timestamps are UTC ("...Z"); the shared schema stores naive
    # datetime64[ns], so the tz has to be dropped after parsing rather than
    # just letting pd.to_datetime infer a tz-aware dtype.
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return parsed.tz_localize(None) if parsed is not pd.NaT else parsed


def _feature_to_record(feature: dict, license_text: str, redistribution_ok: bool) -> dict:
    props = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"]
    return {
        "station_id": str(props["id"]),
        "name": props.get("name"),
        "lon": lon,
        "lat": lat,
        "compartment": "GW",
        "network": "GGMN",
        "start_date": _parse_timestamp(props.get("first_recorded_measurement")),
        "end_date": _parse_timestamp(props.get("last_recorded_measurement")),
        "wsi": None,
        "license": license_text,
        "redistribution_ok": redistribution_ok,
    }
