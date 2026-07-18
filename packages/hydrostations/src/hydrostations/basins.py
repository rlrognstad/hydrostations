from __future__ import annotations

from hydrostations.adapters.base import BBox

# Bounding boxes for a handful of major basins, used to pre-filter adapter
# API queries (e.g. NWIS's bBox param) before fetching. These are real
# HydroBASINS-derived bounds -- not hand-drawn -- computed once via
# hydrocrosswalk by taking a reference point on each river, finding its
# HydroBASINS level-4 sub-basin, grouping all sub-basins sharing the same
# MAIN_BAS, and taking the union's total_bounds. See
# `hydrocrosswalk.sources.hydrobasins.fetch_hydrobasins` for the live join;
# this dict is a cheap, dependency-free snapshot for basin-name lookup only
# -- it doesn't need updating unless HydroBASINS itself changes.
_BASIN_BBOXES: dict[str, BBox] = {
    "niger": BBox(min_lon=-11.588029, min_lat=4.387514, max_lon=15.858333, max_lat=23.950567),
    "amazon": BBox(min_lon=-79.6125, min_lat=-20.479167, max_lon=-50.341049, max_lat=5.283333),
    "mekong": BBox(min_lon=93.858069, min_lat=9.611933, max_lon=108.775353, max_lat=33.820833),
    "murray-darling": BBox(
        min_lon=138.811933, min_lat=-37.679167, max_lon=152.4875, max_lat=-24.591667
    ),
    "danube": BBox(min_lon=8.154167, min_lat=42.082766, max_lon=29.717284, max_lat=50.245793),
}


def resolve_basin_bbox(basin: str) -> BBox:
    key = basin.strip().lower()
    try:
        return _BASIN_BBOXES[key]
    except KeyError as exc:
        known = ", ".join(sorted(_BASIN_BBOXES))
        raise ValueError(
            f"unknown basin {basin!r}; no bounding box registered. "
            f"Known basins: {known}. This is a small name-to-bbox lookup for "
            "pre-filtering API queries; for full basin/H3 assignment on "
            "arbitrary points, see hydrocrosswalk.assign_crosswalk()."
        ) from exc
