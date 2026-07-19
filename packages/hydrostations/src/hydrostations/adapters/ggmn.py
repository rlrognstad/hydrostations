"""GGMN (Global Groundwater Monitoring Network, IGRAC) adapter.

Uses IGRAC's GeoServer WFS 2.0 endpoint (https://ggis.un-igrac.org/geoserver/ows),
querying the `groundwater:GGMN_Levels_Data` layer directly -- no auth, no MOU
needed for read access (an MOU only governs institutions contributing data
into GGMN, a different relationship than reading published records). Output
format is GeoJSON.

Paginates via `startIndex`/`count`; GeoServer here throws a server-side
NullPointerException when `startIndex` is combined with a `bbox` filter but
no explicit `sortBy` -- sorting by `id` avoids it (a real bug worked around,
not a documented requirement, hence the register's `sort_by` config knob).

Licensing: the dataset's own metadata (constraints_other, via
https://ggis.un-igrac.org/api/v2/datasets/2472/) states CC BY-NC-SA 4.0
(Attribution-NonCommercial-ShareAlike), not the plainer "CC BY" sometimes
quoted informally -- and the license identifier itself is `varied_derived`,
since GGMN aggregates data from many national authorities who may attach
their own terms. `redistribution_ok=True` here because redistribution is
genuinely allowed, just conditioned on non-commercial use and share-alike --
conditions this package doesn't have a dedicated field for, so they live in
the `license` string for now.

This is genuinely a reusable protocol (OGC WFS 2.0 is a real standard,
GeoServer backs a lot of government open data) -- generalizing it into a
shared `WfsAdapter` is a separate, later step.
"""

from __future__ import annotations

import geopandas as gpd
import httpx
import pandas as pd

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records


class GgmnAdapter(SourceAdapter):
    protocol = "wfs"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if compartment is not None and compartment not in self.compartments:
            return stations_frame_from_records([])
        c = compartment or self.compartments[0]
        return stations_frame_from_records(self._fetch_all(bbox=bbox, compartment=c))

    def _fetch_all(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
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
            payload = response.json()
            features = payload.get("features", [])
            records.extend(
                self._feature_to_record(f, compartment, collection) for f in features
            )

            if len(features) < cfg.page_size:
                break
            start_index += cfg.page_size

        return records

    def _feature_to_record(self, feature: dict, compartment: str, collection) -> dict:
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
            "first_obs": _parse_timestamp(props.get(collection.start_field)),
            "last_obs": _parse_timestamp(props.get(collection.end_field)),
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": props,
        }


def _parse_timestamp(value: str | None) -> pd.Timestamp:
    # GGMN's timestamps are UTC ("...Z"); the shared schema stores naive
    # datetime64[ns], so the tz has to be dropped after parsing rather than
    # just letting pd.to_datetime infer a tz-aware dtype.
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return parsed.tz_localize(None) if parsed is not pd.NaT else parsed
