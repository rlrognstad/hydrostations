"""Archetype for bulk/snapshot sources with no server-side spatial filter.

A bulk source (e.g. SIEREM's per-basin KML files) has no query API: the only
way to get stations is to download the whole file set and filter locally.
This is architecturally distinct from the protocol/bespoke adapters, which
all push `bbox`/`compartment` filtering to the remote server. Concrete
adapters still implement `fetch_stations()` themselves (download + parse is
inherently source-specific); this base class only provides the shared
client-side bbox filter every bulk adapter needs.
"""

from __future__ import annotations

import geopandas as gpd

from hydrostations.adapters.base import BBox, SourceAdapter


class BulkFileAdapter(SourceAdapter):
    def _filter_by_bbox(self, frame: gpd.GeoDataFrame, bbox: BBox | None) -> gpd.GeoDataFrame:
        """Client-side bbox filter for a fully-materialized frame.

        Bulk sources have no server-side spatial filter to push `bbox`
        into, unlike protocol/bespoke adapters.
        """
        if bbox is None or frame.empty:
            return frame
        return frame.cx[bbox.min_lon : bbox.max_lon, bbox.min_lat : bbox.max_lat]
