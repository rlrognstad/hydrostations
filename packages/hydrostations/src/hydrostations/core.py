from __future__ import annotations

import warnings
from collections.abc import Sequence

import geopandas as gpd
import pandas as pd

from hydrostations.adapters.base import StationAdapter
from hydrostations.adapters.bom import BomAdapter
from hydrostations.adapters.hidroweb import HidroWebAdapter
from hydrostations.adapters.nwis import NwisAdapter
from hydrostations.adapters.sierem import SieremAdapter
from hydrostations.adapters.wise import WiseAdapter
from hydrostations.basins import resolve_basin_bbox
from hydrostations.exceptions import AdapterNotImplementedError
from hydrostations.schema import COMPARTMENTS, empty_stations_frame, validate_stations_frame


def _default_registry() -> dict[str, StationAdapter]:
    return {
        "nwis": NwisAdapter(),
        "wise": WiseAdapter(),
        "bom": BomAdapter(),
        "hidroweb": HidroWebAdapter(),
        "sierem": SieremAdapter(),
    }


def get_stations(
    *,
    basin: str | None = None,
    compartment: str | None = None,
    network: str | Sequence[str] | None = None,
) -> gpd.GeoDataFrame:
    """Fetch stations across one or more networks as a normalized GeoDataFrame.

    `basin` is resolved to a bounding box for spatial filtering -- a
    temporary approach pending the HydroBASINS crosswalk (see
    `hydrostations.basins`). Networks with a not-yet-implemented adapter are
    silently skipped when `network` is unset (a broad query), but raise if
    explicitly requested by name.
    """
    if compartment is not None and compartment not in COMPARTMENTS:
        raise ValueError(f"compartment must be one of {COMPARTMENTS}, got {compartment!r}")

    bbox = resolve_basin_bbox(basin) if basin is not None else None
    registry = _default_registry()

    if network is None:
        selected = list(registry.values())
        explicit = False
    else:
        names = [network] if isinstance(network, str) else list(network)
        selected = []
        for name in names:
            try:
                selected.append(registry[name.lower()])
            except KeyError as exc:
                raise ValueError(
                    f"unknown network {name!r}; known networks: {sorted(registry)}"
                ) from exc
        explicit = True

    frames = []
    for adapter in selected:
        if compartment is not None and compartment not in adapter.compartments:
            continue
        try:
            frame = adapter.fetch_stations(bbox=bbox, compartment=compartment)
        except AdapterNotImplementedError as exc:
            if explicit:
                raise
            warnings.warn(str(exc), stacklevel=2)
            continue
        if frame.empty:
            continue
        validate_stations_frame(frame)
        frames.append(frame)

    if not frames:
        return empty_stations_frame()

    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
