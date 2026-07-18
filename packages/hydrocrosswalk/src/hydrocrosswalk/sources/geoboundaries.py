"""geoBoundaries administrative boundary polygons.

Uses the geoBoundaries REST API
(https://www.geoboundaries.org/api/current/gbOpen/{ISO3}/{ADM_LEVEL}/) to
fetch metadata per country, then downloads the linked GeoJSON. Every
geoBoundaries record carries its own license (it varies by underlying
national source -- some are CC BY 4.0, others CC BY-SA, etc.), so the
license is captured per row rather than assumed constant.
"""

from __future__ import annotations

import geopandas as gpd
import httpx
import pandas as pd

_API_BASE = "https://www.geoboundaries.org/api/current/gbOpen"


def fetch_admin_boundaries(iso3_codes: list[str], adm_level: str = "ADM0") -> gpd.GeoDataFrame:
    frames = []
    for iso3 in iso3_codes:
        meta_response = httpx.get(
            f"{_API_BASE}/{iso3}/{adm_level}/", timeout=30.0, follow_redirects=True
        )
        meta_response.raise_for_status()
        meta = meta_response.json()
        if "gjDownloadURL" not in meta:
            raise ValueError(f"no {adm_level} boundary available for {iso3!r}: {meta}")

        geojson_response = httpx.get(meta["gjDownloadURL"], timeout=60.0, follow_redirects=True)
        geojson_response.raise_for_status()

        gdf = gpd.GeoDataFrame.from_features(
            geojson_response.json()["features"], crs="EPSG:4326"
        )
        gdf["admin_license"] = meta["boundaryLicense"]
        gdf["admin_license_source"] = meta["licenseSource"]
        frames.append(gdf)

    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
