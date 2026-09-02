"""GLOBE Program (globe.gov) adapter -- global citizen-science sites.

GLOBE is an international STEM programme: students and citizen scientists
in ~125 countries take standardized environmental measurements at
registered school/site locations. There is no station endpoint -- only a
measurement search API (`api.globe.gov/search/v1`) -- so "stations" here
are derived by aggregating measurements to their `siteId`
(`first_obs`/`last_obs` = min/max `measuredDate` seen, `variables` = the
GLOBE protocols observed at that site).

Two real constraints, both confirmed live:

* The backend is Elasticsearch with the default 10,000-row
  `max_result_window` -- `from + size` past ~10k returns "all shards
  failed". So the adapter can't just page through a multi-year global
  result set; it walks the date range with **adaptive windowing**: query
  a window, and if its `count` is at/over the cap, split it in half and
  recurse, down to single days.
* No station endpoint means a global fetch is inherently heavy -- this is
  the slowest source in the register (minutes for a broad query). A
  `bbox` query uses the API's `/lat/lon/` endpoint (real server-side
  spatial filter) and is far lighter. `globe.start_date` bounds how far
  back to look (and floors `first_obs`); sites with nothing since then
  are omitted.

`globe.protocols_by_compartment` maps GLOBE protocol API-names to
compartments (config-driven, like GHCN's `element_by_compartment`).
`precipitations` is deliberately unmapped by default: very high volume,
and P is already well covered.

`source_class: citizen` -- the observers are students/volunteers, same
call as CoCoRaHS.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.schema import stations_frame_from_records

# ES max_result_window; stay just under it so paging never straddles the wall.
_RESULT_CAP = 9000


class GlobeAdapter(SourceAdapter):
    protocol = "globe_api"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.globe
        compartments = [compartment] if compartment else list(self.compartments)
        compartments = [
            c
            for c in compartments
            if c in self.compartments and c in cfg.protocols_by_compartment
        ]

        records: list[dict] = []
        for c in compartments:
            records.extend(self._fetch_compartment(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_compartment(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        cfg = self.entry.globe
        protocols = ",".join(cfg.protocols_by_compartment[compartment])
        base = {
            "protocols": protocols,
            "geojson": "FALSE",
            "sample": "FALSE",
            "size": str(cfg.page_size),
        }
        if bbox is not None:
            url = f"{self.entry.endpoint}/measurement/protocol/measureddate/lat/lon/"
            base |= {
                "minlat": bbox.min_lat,
                "maxlat": bbox.max_lat,
                "minlon": bbox.min_lon,
                "maxlon": bbox.max_lon,
            }
        else:
            url = f"{self.entry.endpoint}/measurement/protocol/measureddate/"

        start = _parse_date(cfg.start_date)
        end = datetime.now(UTC).date()
        sites: dict[object, dict] = {}
        with httpx.Client(timeout=90.0) as client:
            self._walk(client, url, base, start, end, cfg.page_size, sites)

        return [self._site_to_record(s, compartment) for s in sites.values()]

    def _walk(
        self,
        client: httpx.Client,
        url: str,
        base: dict,
        start: date,
        end: date,
        page_size: int,
        sites: dict,
    ) -> None:
        """Fetch [start, end]; if it's over the result cap, split and recurse."""
        params = {**base, "startdate": start.isoformat(), "enddate": end.isoformat()}
        first = client.get(url, params={**params, "from": "0"})
        first.raise_for_status()
        payload = first.json()

        if payload.get("count", 0) >= _RESULT_CAP and start < end:
            mid = start + (end - start) // 2
            self._walk(client, url, base, start, mid, page_size, sites)
            self._walk(client, url, base, mid + timedelta(days=1), end, page_size, sites)
            return

        offset = 0
        while True:
            results = payload.get("results", [])
            for row in results:
                _accumulate(sites, row)
            if len(results) < page_size:
                break
            offset += page_size
            page = client.get(url, params={**params, "from": str(offset)})
            page.raise_for_status()
            payload = page.json()

    def _site_to_record(self, site: dict, compartment: str) -> dict:
        elevation = site.get("elevation")
        protocols = sorted(p for p in site["protocols"] if p)
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": str(site["site_id"]),
            "name": site.get("name"),
            "lon": site["lon"],
            "lat": site["lat"],
            "compartment": compartment,
            "variables": protocols,
            "elevation_m": float(elevation) if isinstance(elevation, (int, float)) else None,
            "first_obs": site.get("first"),
            "last_obs": site.get("last"),
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": {
                "site_id": site["site_id"],
                "site_name": site.get("name"),
                "country": site.get("country"),
                "organization": site.get("organization"),
                "protocols": protocols,
            },
        }


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _accumulate(sites: dict, row: dict) -> None:
    site_id = row.get("siteId")
    lat, lon = row.get("latitude"), row.get("longitude")
    if site_id is None or lat is None or lon is None:
        return
    measured = row.get("measuredDate")
    site = sites.get(site_id)
    if site is None:
        sites[site_id] = {
            "site_id": site_id,
            "name": row.get("siteName"),
            "lat": float(lat),
            "lon": float(lon),
            "elevation": row.get("elevation"),
            "country": row.get("countryName"),
            "organization": row.get("organizationName"),
            "protocols": {row.get("protocol")},
            "first": measured,
            "last": measured,
        }
        return
    site["protocols"].add(row.get("protocol"))
    if measured:
        if not site["first"] or measured < site["first"]:
            site["first"] = measured
        if not site["last"] or measured > site["last"]:
            site["last"] = measured
