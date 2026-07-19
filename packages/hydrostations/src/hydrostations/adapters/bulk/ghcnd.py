"""GHCN-Daily (NOAA/NCEI Global Historical Climatology Network) adapter.

Global, in-situ, fixed-width text files hosted anonymously on a public S3
bucket (`noaa-ghcn-pds.s3.amazonaws.com`) -- no auth, confirmed live. This
is distinct from NOAA's documented CDO API (`ncei.noaa.gov/cdo-web/api`),
which requires a token; the bulk static files are the real no-friction
path to this data.

Two files, fetched once each regardless of how many compartments are
requested: `ghcnd-stations.txt` (~122k stations: id/lat/lon/elevation/
name, fixed-width columns per the dataset's own README) and
`ghcnd-inventory.txt` (~782k rows: which element each station reports and
over what year range -- confirmed live via `grep`, e.g. 130,421 stations
report `PRCP`). A station is included in a compartment if the inventory
lists any of that compartment's configured element codes for it --
`element_by_compartment` in the register entry, not hardcoded, since GHCN
also carries `SNOW`/`SNWD` elements that could feed a `SNOW` compartment
later without a new adapter.

No server-side spatial filter (it's two static files) -- fetched in full,
filtered client-side via `BulkFileAdapter._filter_by_bbox()`, same shape
as SIEREM/NRFA/SNOTEL/CoCoRaHS.

`elevation_m` is genuinely already in meters here (confirmed against known
Colorado high-altitude stations, e.g. ~3,535 m for a Nederland-area
station -- not plausible in feet) -- unlike SNOTEL/CoCoRaHS, which needed
a feet-to-meters conversion. `first_obs`/`last_obs` are derived from the
inventory's FIRSTYEAR/LASTYEAR (year-only, not exact dates) across
whichever configured elements matched -- Jan 1 / Dec 31 of those years,
a real precision limitation worth knowing, not exact observation dates.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import stations_frame_from_records


class GhcndAdapter(BulkFileAdapter):
    protocol = "ghcnd_bulk"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.ghcnd
        compartments = [compartment] if compartment else list(self.compartments)
        compartments = [
            c for c in compartments if c in self.compartments and c in cfg.element_by_compartment
        ]
        if not compartments:
            return stations_frame_from_records([])

        stations = self._fetch_stations_metadata()
        inventory = self._fetch_inventory()

        records = []
        for c in compartments:
            elements = set(cfg.element_by_compartment[c])
            for station_id, meta in stations.items():
                matches = [
                    (first_year, last_year)
                    for element, first_year, last_year in inventory.get(station_id, [])
                    if element in elements
                ]
                if not matches:
                    continue
                first_year = min(m[0] for m in matches)
                last_year = max(m[1] for m in matches)
                records.append(self._to_record(station_id, meta, c, first_year, last_year))

        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _fetch_stations_metadata(self) -> dict[str, dict]:
        cfg = self.entry.ghcnd
        response = httpx.get(f"{self.entry.endpoint}/{cfg.stations_path}", timeout=60.0)
        response.raise_for_status()
        stations = {}
        for line in response.text.splitlines():
            if not line.strip():
                continue
            stations[line[0:11]] = {
                "lat": float(line[12:20]),
                "lon": float(line[21:30]),
                "elevation_m": float(line[31:37]),
                "name": line[41:71].strip(),
            }
        return stations

    def _fetch_inventory(self) -> dict[str, list[tuple[str, int, int]]]:
        cfg = self.entry.ghcnd
        response = httpx.get(f"{self.entry.endpoint}/{cfg.inventory_path}", timeout=60.0)
        response.raise_for_status()
        inventory: dict[str, list[tuple[str, int, int]]] = {}
        for line in response.text.splitlines():
            if not line.strip():
                continue
            entry = (line[31:35], int(line[36:40]), int(line[41:45]))
            inventory.setdefault(line[0:11], []).append(entry)
        return inventory

    def _to_record(
        self, station_id: str, meta: dict, compartment: str, first_year: int, last_year: int
    ) -> dict:
        elevation = meta["elevation_m"]
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": station_id,
            "name": meta["name"] or None,
            "lon": meta["lon"],
            "lat": meta["lat"],
            "compartment": compartment,
            "variables": [],
            # -999.9 is the dataset's own "no elevation" sentinel (per the
            # README's field spec), not a literal below-sea-level value.
            "elevation_m": elevation if elevation > -999 else None,
            "first_obs": f"{first_year}-01-01",
            "last_obs": f"{last_year}-12-31",
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": {
                "station_id": station_id,
                **meta,
                "first_year": first_year,
                "last_year": last_year,
            },
        }
