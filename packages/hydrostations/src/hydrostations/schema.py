from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

# Aligned with WOI's compartment structure: streamflow, groundwater,
# precipitation, and a catch-all for everything else (e.g. water quality)
# until the cube's compartment structure grows a dedicated code for it.
COMPARTMENTS = ("Q", "GW", "P", "other")

COLUMNS = (
    "station_id",
    "name",
    "geometry",
    "compartment",
    "network",
    "start_date",
    "end_date",
    "wsi",
    "license",
    "redistribution_ok",
)

_NON_GEOMETRY_DTYPES = {
    "station_id": "string",
    "name": "string",
    "compartment": "string",
    "network": "string",
    "start_date": "datetime64[ns]",
    "end_date": "datetime64[ns]",
    "wsi": "string",
    "license": "string",
    "redistribution_ok": "boolean",
}


def empty_stations_frame() -> gpd.GeoDataFrame:
    """An empty, correctly-typed stations GeoDataFrame."""
    data = {col: pd.Series(dtype=dtype) for col, dtype in _NON_GEOMETRY_DTYPES.items()}
    return gpd.GeoDataFrame(data, geometry=gpd.GeoSeries([], crs="EPSG:4326"))


def stations_frame_from_records(records: Iterable[Mapping[str, Any]]) -> gpd.GeoDataFrame:
    """Build a normalized stations GeoDataFrame from adapter-fetched records.

    Each record must provide `lon`/`lat` (consumed to build `geometry`) plus
    the non-geometry columns in `COLUMNS`; missing optional columns (e.g.
    `wsi`) default to null.
    """
    records = list(records)
    if not records:
        return empty_stations_frame()

    df = pd.DataFrame.from_records(records)
    geometry = [Point(lon, lat) for lon, lat in zip(df.pop("lon"), df.pop("lat"), strict=True)]

    for col, dtype in _NON_GEOMETRY_DTYPES.items():
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].astype(dtype)

    frame = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    frame = frame[list(COLUMNS)]
    validate_stations_frame(frame)
    return frame


def validate_stations_frame(frame: gpd.GeoDataFrame) -> None:
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"stations frame missing required columns: {missing}")
    bad_compartments = set(frame["compartment"].dropna()) - set(COMPARTMENTS)
    if bad_compartments:
        raise ValueError(f"unknown compartment codes: {bad_compartments}")
