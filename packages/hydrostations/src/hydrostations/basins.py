from __future__ import annotations

from hydrostations.adapters.base import BBox

# Temporary, coarse bounding boxes for a handful of major basins. This is a
# placeholder for spatial filtering pending integration with the HydroBASINS
# x GADM x H3 crosswalk (a separate, related deliverable), which will supply
# real basin polygons and proper point-in-polygon assignment instead of bbox
# filtering.
_BASIN_BBOXES: dict[str, BBox] = {
    "niger": BBox(min_lon=-12.0, min_lat=4.0, max_lon=16.0, max_lat=25.0),
    "amazon": BBox(min_lon=-80.0, min_lat=-20.0, max_lon=-44.0, max_lat=6.0),
    "mekong": BBox(min_lon=94.0, min_lat=8.0, max_lon=107.0, max_lat=34.0),
    "murray-darling": BBox(min_lon=138.0, min_lat=-38.0, max_lon=154.0, max_lat=-24.0),
    "danube": BBox(min_lon=8.0, min_lat=42.0, max_lon=30.0, max_lat=51.0),
}


def resolve_basin_bbox(basin: str) -> BBox:
    key = basin.strip().lower()
    try:
        return _BASIN_BBOXES[key]
    except KeyError as exc:
        known = ", ".join(sorted(_BASIN_BBOXES))
        raise ValueError(
            f"unknown basin {basin!r}; no bounding box registered. "
            f"Known basins: {known}. Basin resolution is a temporary bbox "
            "lookup pending the HydroBASINS crosswalk integration."
        ) from exc
