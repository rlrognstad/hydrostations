"""H3 hexagonal grid generation.

H3 cell indexes are public, standard identifiers (https://h3geo.org) --
covering a polygon with H3 cells and carrying the resulting cell IDs
forward introduces no redistribution concerns of its own.
"""

from __future__ import annotations

import h3
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry


def cells_for_geometry(geometry: BaseGeometry, resolution: int) -> set[str]:
    return h3.geo_to_cells(geometry, res=resolution)


def cell_to_point(cell: str) -> Point:
    lat, lng = h3.cell_to_latlng(cell)
    return Point(lng, lat)


def cell_to_polygon(cell: str) -> Polygon:
    # h3 returns (lat, lng) pairs; shapely wants (lng, lat).
    boundary = h3.cell_to_boundary(cell)
    return Polygon([(lng, lat) for lat, lng in boundary])
