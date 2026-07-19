"""Archetype for sources with no server-side spatial filter.

The defining trait is "no query API to push `bbox` into," not "static
file" specifically -- SIEREM (per-basin KML files, `live: false`) is the
static-snapshot case; NRFA (a live REST endpoint that just doesn't support
spatial filtering -- `station=*` always returns every station) is the
live-but-unfiltered case. Both need the whole inventory fetched, then
filtered locally. This is architecturally distinct from the
protocol/bespoke adapters, which all push `bbox`/`compartment` filtering
to the remote server. Concrete adapters still implement `fetch_stations()`
themselves (fetching + parsing is inherently source-specific); this base
class only provides the shared client-side bbox filter every adapter here
needs.
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
