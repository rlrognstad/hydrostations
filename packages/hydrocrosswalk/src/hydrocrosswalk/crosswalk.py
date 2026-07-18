"""Join HydroBASINS x geoBoundaries x H3 -- either as a standalone grid
(`build_crosswalk`) or as enrichment for someone else's points
(`assign_crosswalk`).

HydroBASINS polygon geometries are used internally for spatial joins only
and never re-exported -- see `hydrocrosswalk.sources.hydrobasins` for why.

This module only fetches and joins; it doesn't cache or publish anything.
Each call re-fetches from HydroSHEDS and geoBoundaries directly, unless
pre-fetched `basins`/`admin` frames are passed in.
"""

from __future__ import annotations

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import box

from hydrocrosswalk.h3grid import cell_to_point, cells_for_geometry
from hydrocrosswalk.sources.geoboundaries import fetch_admin_boundaries
from hydrocrosswalk.sources.hydrobasins import HYDROBASINS_LICENSE_NOTE, fetch_hydrobasins


def _match_polygon_fields(
    points: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame, value_cols: list[str]
) -> pd.DataFrame:
    """Point-in-polygon join, one match per point, aligned by position."""
    working = points[["geometry"]].reset_index(drop=True)
    working["_pos"] = range(len(working))
    joined = gpd.sjoin(working, polygons[[*value_cols, "geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates(subset="_pos").sort_values("_pos")
    return joined[value_cols].reset_index(drop=True)


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
    table = table.drop_duplicates(subset="h3_cell").reset_index(drop=True)

    admin = fetch_admin_boundaries(countries, adm_level=admin_level)
    cell_points = gpd.GeoDataFrame(
        {"h3_cell": table["h3_cell"]},
        geometry=[cell_to_point(c) for c in table["h3_cell"]],
        crs="EPSG:4326",
    )
    admin_cols = [c for c in admin.columns if c != "geometry"]
    admin_matches = _match_polygon_fields(cell_points, admin, admin_cols)
    table = pd.concat([table, admin_matches], axis=1)
    table["hydrobasins_license_note"] = HYDROBASINS_LICENSE_NOTE
    return table


def assign_crosswalk(
    points: gpd.GeoDataFrame,
    *,
    h3_resolution: int,
    region: str | None = None,
    hydrobasins_level: int | None = None,
    countries: list[str] | None = None,
    admin_level: str = "ADM0",
    basins: gpd.GeoDataFrame | None = None,
    admin: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Enrich any point GeoDataFrame with h3_cell, HydroBASINS IDs, and admin fields.

    `points` can be output from any source (e.g. `hydrostations.get_stations()`)
    -- this function doesn't know or care where the points came from, it just
    needs a `geometry` column of Points. All original columns are preserved.

    Pass pre-fetched `basins`/`admin` (from `fetch_hydrobasins`/
    `fetch_admin_boundaries`) to avoid re-downloading across repeated calls,
    e.g. when assigning crosswalk fields to several batches of points from
    the same region. Otherwise `region`/`hydrobasins_level` and `countries`
    are required so they can be fetched here.
    """
    if basins is None:
        if region is None or hydrobasins_level is None:
            raise ValueError("pass `basins`, or both `region` and `hydrobasins_level`")
        basins = fetch_hydrobasins(region=region, level=hydrobasins_level)
    if admin is None:
        if countries is None:
            raise ValueError("pass `admin`, or `countries`")
        admin = fetch_admin_boundaries(countries, adm_level=admin_level)

    result = points.copy()
    result["h3_cell"] = [h3.latlng_to_cell(pt.y, pt.x, h3_resolution) for pt in points.geometry]

    basin_matches = _match_polygon_fields(points, basins, ["HYBAS_ID", "PFAF_ID", "MAIN_BAS"])
    result["hybas_id"] = basin_matches["HYBAS_ID"].to_numpy()
    result["pfaf_id"] = basin_matches["PFAF_ID"].to_numpy()
    result["main_bas"] = basin_matches["MAIN_BAS"].to_numpy()

    admin_cols = [c for c in admin.columns if c != "geometry"]
    admin_matches = _match_polygon_fields(points, admin, admin_cols)
    for col in admin_cols:
        result[col] = admin_matches[col].to_numpy()

    result["hydrobasins_license_note"] = HYDROBASINS_LICENSE_NOTE
    return result
