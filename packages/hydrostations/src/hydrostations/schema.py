from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

# Streamflow, groundwater, precipitation, soil moisture, evapotranspiration,
# surface water (lakes/reservoirs/coastal), snow, water quality.
COMPARTMENTS = ("Q", "GW", "P", "SM", "ET", "SW", "SNOW", "WQ")


def parse_timestamp(value: str | None) -> pd.Timestamp:
    """Normalize a source's native timestamp string to the tz-naive form
    `first_obs`/`last_obs` require.

    Handles both tz-aware ("...Z"-suffixed ISO8601, e.g. WFS/GeoJSON
    sources) and date-only strings (e.g. Hub'Eau's GW dates) -- `utc=True`
    treats a bare date as UTC midnight, then the tz is stripped to match
    the shared schema's naive datetime64[ns] columns.
    """
    if value is None:
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return parsed.tz_localize(None) if parsed is not pd.NaT else parsed


@dataclass(frozen=True)
class Station:
    """The per-record contract every source (agency/network) adapter emits.

    Deliberately excludes basin/hydrography linkage (basin_id, river_reach_id,
    aquifer_id) -- that stays entirely in the separate `hydrocrosswalk`
    package, joined on afterward via `assign_crosswalk()`. Also excludes the
    observed-vs-declared accessibility ladder (openness_metadata_declared,
    openness_observed, latency_days, etc.) -- that only becomes measurable
    once time-series retrieval (get_series) exists, which it doesn't yet;
    `license`/`redistribution_ok` are kept as the simpler stand-in.

    `positional_uncertainty_m`, `elevation_m`, `catchment_area_km2`, and
    `reporting_interval` are real fields in the contract but every current
    adapter leaves them null -- none of the five live sources expose enough
    to populate them yet. That's a placeholder, not an oversight.

    `variables` carries each source's *native* parameter code/type string
    (e.g. NWIS's "00060", BoM's "Water Course Discharge"), not a canonical
    vocabulary -- building a real cross-source vocabulary is unstarted work.

    Note this makes the frame not strictly flat: `variables` is a list cell
    and `raw` is a dict cell, unlike every other column. A consumer doing
    naive CSV/Parquet export should be aware of that.
    """

    canonical_id: str            # f"{source}:{source_id}" -- provisional, not deduplicated
    source: str                  # register source_id, e.g. "bom" (lowercase)
    source_id: str               # native id at source
    wsi: str | None              # WMO WIGOS Station Identifier, where known
    name: str | None
    compartment: str             # one of COMPARTMENTS
    variables: list[str]         # native param code/type strings available here
    geometry: Point              # EPSG:4326
    positional_uncertainty_m: float | None
    elevation_m: float | None
    catchment_area_km2: float | None
    first_obs: pd.Timestamp | None
    last_obs: pd.Timestamp | None
    reporting_interval: str | None
    license: str | None
    redistribution_ok: bool
    retrieved_at: pd.Timestamp    # stamped once per fetch_stations() call
    raw: dict                     # untouched native record (GeoJSON properties, KiWIS row, ...)


COLUMNS = (
    "canonical_id",
    "source",
    "source_id",
    "wsi",
    "name",
    "compartment",
    "variables",
    "geometry",
    "positional_uncertainty_m",
    "elevation_m",
    "catchment_area_km2",
    "first_obs",
    "last_obs",
    "reporting_interval",
    "license",
    "redistribution_ok",
    "retrieved_at",
    "raw",
)

_NON_GEOMETRY_DTYPES = {
    "canonical_id": "string",
    "source": "string",
    "source_id": "string",
    "wsi": "string",
    "name": "string",
    "compartment": "string",
    "positional_uncertainty_m": "Float64",
    "elevation_m": "Float64",
    "catchment_area_km2": "Float64",
    "first_obs": "datetime64[ns]",
    "last_obs": "datetime64[ns]",
    "reporting_interval": "string",
    "license": "string",
    "redistribution_ok": "boolean",
    "retrieved_at": "datetime64[ns]",
}

# Container-typed columns handled separately from _NON_GEOMETRY_DTYPES since
# .astype() doesn't apply to list/dict cells the way it does to scalars.
_CONTAINER_DEFAULTS = {
    "variables": list,
    "raw": dict,
}


def empty_stations_frame() -> gpd.GeoDataFrame:
    """An empty, correctly-typed stations GeoDataFrame."""
    data = {col: pd.Series(dtype=dtype) for col, dtype in _NON_GEOMETRY_DTYPES.items()}
    for col in _CONTAINER_DEFAULTS:
        data[col] = pd.Series(dtype="object")
    frame = gpd.GeoDataFrame(data, geometry=gpd.GeoSeries([], crs="EPSG:4326"))
    return frame[list(COLUMNS)]


def stations_frame_from_records(records: Iterable[Mapping[str, Any]]) -> gpd.GeoDataFrame:
    """Build a normalized stations GeoDataFrame from adapter-fetched records.

    Each record must provide `lon`/`lat` (consumed to build `geometry`) plus
    `source`/`source_id` (used to auto-derive `canonical_id` if not given
    explicitly) and the other `Station` fields; missing optional columns
    default to null (or `[]`/`{}` for `variables`/`raw`). `retrieved_at` is
    auto-stamped once for the whole batch if not already present, so
    adapters don't each need to compute it themselves.
    """
    records = list(records)
    if not records:
        return empty_stations_frame()

    df = pd.DataFrame.from_records(records)
    geometry = [Point(lon, lat) for lon, lat in zip(df.pop("lon"), df.pop("lat"), strict=True)]

    if "canonical_id" not in df.columns:
        df["canonical_id"] = df["source"] + ":" + df["source_id"].astype(str)

    if "retrieved_at" not in df.columns:
        now = pd.Timestamp(datetime.now(UTC)).tz_localize(None)
        df["retrieved_at"] = now

    for col, dtype in _NON_GEOMETRY_DTYPES.items():
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].astype(dtype)

    for col, default in _CONTAINER_DEFAULTS.items():
        if col not in df.columns:
            df[col] = [default() for _ in range(len(df))]
        else:
            df[col] = df[col].apply(lambda v, default=default: default() if v is None else v)

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
