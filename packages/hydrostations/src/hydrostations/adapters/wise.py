"""WISE (Water Information System for Europe, EEA) adapter.

Uses the EEA's DiscoData SQL API (https://discodata.eea.europa.eu/sql),
querying [WISE_SOE].[v1r1].[Waterbase_S_WISE_SpatialObject_DerivedData]
directly -- no auth, plain SQL over HTTP, JSON output. Verified live: this
is NOT bulk-download-only as originally assumed; it's a real queryable
station table.

Compartment is derived from the table's `specialisedZoneType` column
(verified live): "riverWaterBody" -> Q, "groundWaterBody" -> GW, and
"lakeWaterBody"/"coastalWaterBody"/"transitionalWaterBody" -> other. Rows
with a null/unrelated zone type (e.g. "riverBasinDistrictSubUnit", which is
an administrative area, not a station) are excluded.

No period-of-record fields exist on this table (that lives in separate,
much larger observation tables); start_date/end_date are left null here,
same as the BoM adapter.

Query timeout is 20s server-side (per EEA's own Discodata user guide), so
large regions are paged via `p`/`nrOfHits` rather than fetched in one call.

Licensing: EEA's default data policy is ODC-BY (Open Data Commons
Attribution License) unless a specific dataset states otherwise --
https://www.eea.europa.eu/en/datahub/eea-data-policy. No WISE-SoE-specific
override found.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, StationAdapter
from hydrostations.schema import stations_frame_from_records

_BASE_URL = "https://discodata.eea.europa.eu/sql"
_TABLE = "[WISE_SOE].[v1r1].[Waterbase_S_WISE_SpatialObject_DerivedData]"
_PAGE_SIZE = 5000

_LICENSE = (
    "ODC-BY (Open Data Commons Attribution License), European Environment "
    "Agency (EEA) -- default EEA data policy unless a specific dataset "
    "states otherwise; see https://www.eea.europa.eu/en/datahub/eea-data-policy"
)

# Coarse declared coverage: Europe (WISE-SoE's WFD reporting scope).
_COVERAGE_BBOXES = (BBox(min_lon=-25.0, min_lat=34.0, max_lon=45.0, max_lat=71.0),)

# specialisedZoneType values (verified live) that count as each compartment.
_ZONE_TYPES = {
    "Q": ("riverWaterBody",),
    "GW": ("groundWaterBody",),
    "other": ("lakeWaterBody", "coastalWaterBody", "transitionalWaterBody"),
}


class WiseAdapter(StationAdapter):
    network = "WISE"
    license = _LICENSE
    redistribution_ok = True
    compartments = ("Q", "GW", "other")
    coverage = _COVERAGE_BBOXES

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
        zone_types = ", ".join(f"'{z}'" for z in _ZONE_TYPES[compartment])
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
            f"FROM {_TABLE} WHERE " + " AND ".join(where)
        )

        records = []
        page = 1
        while True:
            response = httpx.get(
                _BASE_URL,
                params={"query": query, "p": str(page), "nrOfHits": str(_PAGE_SIZE)},
                timeout=30.0,
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
            records.extend(_row_to_record(row, compartment, self.license) for row in rows)

            if len(rows) < _PAGE_SIZE:
                break
            page += 1

        return records


def _row_to_record(row: dict, compartment: str, license_text: str) -> dict:
    return {
        "station_id": row["monitoringSiteIdentifier"],
        "name": row.get("monitoringSiteName"),
        "lon": row["lon"],
        "lat": row["lat"],
        "compartment": compartment,
        "network": "WISE",
        "start_date": None,
        "end_date": None,
        "wsi": None,
        "license": license_text,
        "redistribution_ok": True,
    }
