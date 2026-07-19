"""Static source/compartment coverage lookup by geographic area.

Answers "which sources and compartments are declared to cover this area?"
using each adapter's own declared `coverage` bboxes and `compartments` --
no live API calls, no station counts. For live counts, call get_stations()
for the area and count the rows yourself.

Coverage areas are coarse, hand-declared approximations (e.g. NWIS = CONUS
+ AK/HI/PR; WISE = a Europe bounding box) meant for a quick "is this source
even worth trying here" check -- not authoritative service-area boundaries.
See each source's register entry for its specific coverage bboxes.
"""

from __future__ import annotations

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from hydrostations.core import _default_registry


def lookup_coverage(polygon: BaseGeometry) -> dict[str, list[str]]:
    """Which sources (and their compartments) declare coverage overlapping `polygon`.

    Returns `{source: [compartment, ...]}` for every adapter whose declared
    coverage area intersects `polygon`, using each adapter's full
    `compartments` list -- this is a static declaration, not a live query,
    so it doesn't tell you whether stations actually exist there.
    """
    result: dict[str, list[str]] = {}
    for adapter in _default_registry().values():
        bboxes = (box(b.min_lon, b.min_lat, b.max_lon, b.max_lat) for b in adapter.coverage)
        if any(b.intersects(polygon) for b in bboxes):
            result[adapter.source] = list(adapter.compartments)
    return result
