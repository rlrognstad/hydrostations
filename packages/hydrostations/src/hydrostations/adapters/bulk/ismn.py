"""ISMN (International Soil Moisture Network) adapter.

The documented access path is registration + ToU acceptance on
ismn.earth to download per-network sensor archives -- true for the actual
time-series, which this library doesn't fetch for any source yet. Live
investigation found the station *metadata* is reachable differently:
ismn.earth's own interactive data-viewer (a Leaflet map) is backed by a
public, no-auth JSON endpoint its own JS fetches on page load
(`network_station_details.json`), refreshed at least daily (confirmed via
its own `created_at` field). 3,335 real stations across 89 networks,
confirmed live -- coordinates and first/last-observation timestamps always
present.

A station's free-text `variableText` (e.g. "soil moisture<br>
precipitation<br>") is matched against `entry.ismn.variable_by_compartment`
per compartment -- a station reporting more than one relevant variable
type gets one record per matching compartment, same shape as CoCoRaHS.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import parse_timestamp, stations_frame_from_records


class IsmnAdapter(BulkFileAdapter):
    protocol = "ismn_bulk"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.ismn
        compartments = [compartment] if compartment else list(self.compartments)
        compartments = [
            c for c in compartments if c in self.compartments and c in cfg.variable_by_compartment
        ]
        if not compartments:
            return stations_frame_from_records([])

        networks = self._fetch_networks()
        records = []
        for network in networks:
            for station in network["Stations"]:
                station_variables = self._station_variables(station)
                for c in compartments:
                    matched = station_variables & set(cfg.variable_by_compartment[c])
                    if matched:
                        records.append(
                            self._to_record(station, network["networkID"], c, sorted(matched))
                        )

        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _fetch_networks(self) -> list[dict]:
        response = httpx.get(self.entry.endpoint, timeout=60.0)
        response.raise_for_status()
        return response.json()["Networks"]

    @staticmethod
    def _station_variables(station: dict) -> set[str]:
        return {v.strip() for v in station["variableText"].split("<br>") if v.strip()}

    def _to_record(
        self, station: dict, network_id: str, compartment: str, variables: list[str]
    ) -> dict:
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": str(station["stationID"]),
            "name": station.get("station_name"),
            "lon": station["lng"],
            "lat": station["lat"],
            "compartment": compartment,
            "variables": variables,
            "first_obs": parse_timestamp(station.get("minimum")),
            "last_obs": parse_timestamp(station.get("maximum")),
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": {"networkID": network_id, **station},
        }
