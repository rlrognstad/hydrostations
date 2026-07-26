"""AmeriFlux adapter.

AmeriFlux's public pages have no visible API link -- the real backing
service was found in the `amerifluxr` R package's own source
(`helper_functions.R`), not AmeriFlux's documentation: a no-auth JSON
endpoint at `amfcdn.lbl.gov`, confirmed live. `site_display/AmeriFlux`
returns the full site list (837 sites confirmed live -- the roadmap
doc's ~480 estimate was a real undercount); `site_availability/AmeriFlux/
BIF/CCBY4.0` returns which of those sites are under the open CC BY 4.0
data policy versus the older "Legacy" policy (PI approval / citation
required). Actual flux data (BASE/BADM) still needs an AmeriFlux account
regardless of site policy -- only the site list is reachable anonymously,
and this library doesn't fetch time series for any source yet.

First register entry to populate `ET` (previously empty), and the first
adapter to set `license`/`redistribution_ok` per-record rather than
copying the register entry's value onto every row -- CC BY 4.0 sites
really are more open than Legacy-policy sites, and every other adapter's
"one license for the whole source" assumption doesn't hold here.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import stations_frame_from_records

_CCBY4_LICENSE = "CC BY 4.0"
_LEGACY_LICENSE = "AmeriFlux Legacy Data Policy (PI approval / citation required)"


class AmerifluxAdapter(BulkFileAdapter):
    protocol = "ameriflux_bulk"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        if compartment is not None and compartment not in self.compartments:
            return stations_frame_from_records([])

        sites = self._fetch_sites()
        ccby4_ids = self._fetch_ccby4_site_ids()
        records = [self._to_record(site, site["SITE_ID"] in ccby4_ids) for site in sites]

        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _fetch_sites(self) -> list[dict]:
        response = httpx.get(f"{self.entry.endpoint}/site_display/AmeriFlux", timeout=60.0)
        response.raise_for_status()
        return response.json()

    def _fetch_ccby4_site_ids(self) -> set[str]:
        response = httpx.get(
            f"{self.entry.endpoint}/site_availability/AmeriFlux/BIF/CCBY4.0", timeout=60.0
        )
        response.raise_for_status()
        return {row[0] for row in response.json()}

    def _to_record(self, site: dict, is_ccby4: bool) -> dict:
        location = site.get("GRP_LOCATION", {})
        elevation = location.get("LOCATION_ELEV")
        tower_end = site.get("TOWER_END")
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": site["SITE_ID"],
            "name": site.get("SITE_NAME"),
            "lon": float(location["LOCATION_LONG"]),
            "lat": float(location["LOCATION_LAT"]),
            "compartment": "ET",
            "variables": [],
            "elevation_m": float(elevation) if elevation not in (None, "") else None,
            "first_obs": f"{site['TOWER_BEGAN']}-01-01" if site.get("TOWER_BEGAN") else None,
            "last_obs": f"{tower_end}-12-31" if tower_end else None,
            "wsi": None,
            "license": _CCBY4_LICENSE if is_ccby4 else _LEGACY_LICENSE,
            "redistribution_ok": is_ccby4,
            "raw": site,
        }
