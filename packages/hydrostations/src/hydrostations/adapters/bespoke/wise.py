"""WISE (Water Information System for Europe, EEA) adapter.

Uses the EEA's DiscoData SQL API (https://discodata.eea.europa.eu/sql),
querying [WISE_SOE].[v1r1].[Waterbase_S_WISE_SpatialObject_DerivedData]
directly -- no auth, plain SQL over HTTP, JSON output. Verified live: this
is NOT bulk-download-only as originally assumed; it's a real queryable
station table.

Compartment is derived from the table's `specialisedZoneType` column
(verified live): "riverWaterBody" -> Q, "groundWaterBody" -> GW, and
"lakeWaterBody"/"coastalWaterBody"/"transitionalWaterBody" -> SW. Rows
with a null/unrelated zone type (e.g. "riverBasinDistrictSubUnit", which is
an administrative area, not a station) are excluded.

No period-of-record fields exist on this table (that lives in separate,
much larger observation tables); first_obs/last_obs are left null here,
same as the BoM adapter.

Query timeout is 20s server-side (per EEA's own Discodata user guide), so
large regions are paged via `p`/`nrOfHits` rather than fetched in one call.

Bespoke (not a generalized protocol adapter): EEA's DiscoData SQL-over-HTTP
is a one-off platform, no second known user, so there's no reuse payoff in
abstracting it. Config (table name, zone-type-per-compartment) comes from
the register entry rather than module constants.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records


class WiseAdapter(SourceAdapter):
    protocol = "wise_discodata"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments:
                continue
            records.extend(self._fetch_compartment(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_compartment(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        cfg = self.entry.wise
        zone_types = ", ".join(f"'{z}'" for z in cfg.zone_types_by_compartment[compartment])
        where = [
            "monitoringSiteIdentifier IS NOT NULL",
            "lon IS NOT NULL",
            f"specialisedZoneType IN ({zone_types})",
        ]
        if bbox is not None:
            where.append(f"lon BETWEEN {bbox.min_lon} AND {bbox.max_lon}")
            where.append(f"lat BETWEEN {bbox.min_lat} AND {bbox.max_lat}")

        query = (
            "SELECT countryCode, monitoringSiteIdentifier, monitoringSiteName, lon, lat "
            f"FROM {cfg.table} WHERE " + " AND ".join(where)
        )

        records = []
        page = 1
        while True:
            response = httpx.get(
                self.entry.endpoint,
                params={"query": query, "p": str(page), "nrOfHits": str(cfg.page_size)},
                timeout=30.0,
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
            records.extend(self._row_to_record(row, compartment) for row in rows)

            if len(rows) < cfg.page_size:
                break
            page += 1

        return records

    def _row_to_record(self, row: dict, compartment: str) -> dict:
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": row["monitoringSiteIdentifier"],
            "name": row.get("monitoringSiteName"),
            "lon": row["lon"],
            "lat": row["lat"],
            "compartment": compartment,
            "variables": [],
            "first_obs": None,
            "last_obs": None,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }
