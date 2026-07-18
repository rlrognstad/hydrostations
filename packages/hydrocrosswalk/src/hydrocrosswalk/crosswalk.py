"""Build the HydroBASINS x geoBoundaries x H3 crosswalk.

Output is an ID-only join table -- H3 cell index, HydroBASINS
HYBAS_ID/PFAF_ID, and geoBoundaries admin fields. See
`hydrocrosswalk.sources.hydrobasins` for why HydroBASINS polygon
geometries themselves are never carried into the output.

This module only fetches and joins; it doesn't cache or publish anything.
Each call re-fetches from HydroSHEDS and geoBoundaries directly.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from hydrocrosswalk.h3grid import cell_to_point, cells_for_geometry
from hydrocrosswalk.sources.geoboundaries import fetch_admin_boundaries
from hydrocrosswalk.sources.hydrobasins import HYDROBASINS_LICENSE_NOTE, fetch_hydrobasins


def build_crosswalk(
    *,
    region: str,
    hydrobasins_level: int,
    countries: list[str],
    h3_resolution: int,
    admin_level: str = "ADM0",
    bbox: tuple[float, float, float, float] | None = None,
) -> pd.DataFrame:
    """Build a crosswalk table joining H3 cells to basins and admin units.

    `bbox` (min_lon, min_lat, max_lon, max_lat), if given, restricts which
    HydroBASINS polygons are used -- useful for building a crosswalk for
    one basin rather than an entire continent.
    """
    basins = fetch_hydrobasins(region=region, level=hydrobasins_level)
    if bbox is not None:
        basins = basins[basins.intersects(box(*bbox))]

    records = []
    for basin in basins.itertuples(index=False):
        for cell in cells_for_geometry(basin.geometry, resolution=h3_resolution):
            records.append(
                {
                    "h3_cell": cell,
                    "h3_resolution": h3_resolution,
                    "hybas_id": int(basin.HYBAS_ID),
                    "pfaf_id": int(basin.PFAF_ID),
                    "main_bas": int(basin.MAIN_BAS),
                    "hydrobasins_level": hydrobasins_level,
                }
            )

    table = pd.DataFrame.from_records(records)
    if table.empty:
        return table
    table = table.drop_duplicates(subset="h3_cell")

    admin = fetch_admin_boundaries(countries, adm_level=admin_level)
    cell_points = gpd.GeoDataFrame(
        {"h3_cell": table["h3_cell"]},
        geometry=[cell_to_point(c) for c in table["h3_cell"]],
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(cell_points, admin, how="left", predicate="within")
    joined = joined.drop_duplicates(subset="h3_cell").drop(columns=["geometry", "index_right"])

    admin_cols = [c for c in joined.columns if c != "h3_cell"]
    table = table.merge(joined[["h3_cell", *admin_cols]], on="h3_cell", how="left")
    table["hydrobasins_license_note"] = HYDROBASINS_LICENSE_NOTE
    return table
