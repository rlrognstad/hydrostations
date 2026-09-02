"""SIEREM (HydroSciences Montpellier) adapter -- African station catalogue.

SIEREM (http://www.hydrosciences.fr/sierem/) has no queryable API, but its
Google-Earth layer is a genuinely machine-readable static tree of KML:

* `SieremGoogleBassin.kml` -- the master index: ~647 `<NetworkLink>`s, each
  an href to one per-drainage-basin, per-station-type file
  (`kmz_files/<BASIN><TYPE>.kml`, e.g. `NIGERHYDRO.kml`,
  `SENEGALPLUVI.kml`). ~165 of the hrefs are basin-outline polygons
  (`<BASIN>B.kml`), skipped here.
* Each `<BASIN><TYPE>.kml` holds the actual `<Placemark>`s: `<name>`,
  `<Point><coordinates>`, and a CDATA HTML block carrying
  `<b>{id} - {NAME}</b>`, the country, `Altitude : {n|null} m`, and -- for
  many stations -- inline series date ranges (`... du D-M-YYYY au
  D-M-YYYY ...`).

`sierem.type_by_compartment` maps the filename type token to a compartment
(`{Q: [HYDRO], P: [PLUVI, PLGRA]}` by default). Confirmed live: 125 HYDRO
files, 151 PLUVI+PLGRA files.

No server-side spatial filter -- the whole tree is fetched and filtered
client-side via `BulkFileAdapter._filter_by_bbox()`, same archetype as
GHCN-Daily/GRDC/PSMSL. `live: false` because SIEREM is a genuine dated
snapshot, not a refreshed feed.

Performance: a Q+P query fetches ~276 KML files (one HTTP request each, a
shared keep-alive client) -- tens of seconds, the slowest source in the
register alongside CoCoRaHS. A file that fails to fetch or parse is
skipped, not fatal, since one bad file out of hundreds shouldn't sink the
whole call.
"""

from __future__ import annotations

import re

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.base import BulkFileAdapter
from hydrostations.schema import stations_frame_from_records

_NETWORKLINK_HREF_RE = re.compile(r"<href>\s*([^<\s]+)\s*</href>", re.IGNORECASE)
_PLACEMARK_RE = re.compile(r"<Placemark>(.*?)</Placemark>", re.IGNORECASE | re.DOTALL)
_NAME_RE = re.compile(r"<name>(.*?)</name>", re.IGNORECASE | re.DOTALL)
_COORDS_RE = re.compile(r"<coordinates>\s*([^<]+?)\s*</coordinates>", re.IGNORECASE)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_BOLD_RE = re.compile(r"<b>(.*?)</b>", re.IGNORECASE | re.DOTALL)
_ID_RE = re.compile(r"(\d{4,})\s*-\s*")
_ALT_RE = re.compile(r"Altitude\s*:\s*(\S+)\s*m", re.IGNORECASE)
_DATE_RANGE_RE = re.compile(
    r"du\s+(\d{1,2})-(\d{1,2})-(\d{4})\s+au\s+(\d{1,2})-(\d{1,2})-(\d{4})", re.IGNORECASE
)


class SieremAdapter(BulkFileAdapter):
    protocol = "bulk_kml"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.sierem
        compartments = [compartment] if compartment else list(self.compartments)
        compartments = [
            c for c in compartments if c in self.compartments and c in cfg.type_by_compartment
        ]
        if not compartments:
            return stations_frame_from_records([])

        hrefs = self._fetch_index()
        records: list[dict] = []
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            for c in compartments:
                tokens = tuple(cfg.type_by_compartment[c])
                seen: set[str] = set()
                for href in hrefs:
                    if not _stem(href).endswith(tokens):
                        continue
                    for record in self._fetch_file(client, href, c):
                        if record["source_id"] in seen:
                            continue
                        seen.add(record["source_id"])
                        records.append(record)

        frame = stations_frame_from_records(records)
        return self._filter_by_bbox(frame, bbox)

    def _fetch_index(self) -> list[str]:
        url = f"{self.entry.endpoint.rstrip('/')}/{self.entry.sierem.index_kml}"
        response = httpx.get(url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        return _NETWORKLINK_HREF_RE.findall(response.content.decode("latin-1"))

    def _fetch_file(self, client: httpx.Client, url: str, compartment: str) -> list[dict]:
        try:
            response = client.get(url)
            response.raise_for_status()
            text = response.content.decode("latin-1")
        except (httpx.HTTPError, UnicodeDecodeError):
            return []
        return [
            record
            for match in _PLACEMARK_RE.findall(text)
            if (record := self._placemark_to_record(match, compartment)) is not None
        ]

    def _placemark_to_record(self, placemark: str, compartment: str) -> dict | None:
        coords = _COORDS_RE.search(placemark)
        cdata = _CDATA_RE.search(placemark)
        if coords is None or cdata is None:
            return None
        parts = coords.group(1).split(",")
        if len(parts) < 2:
            return None
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            return None  # some placemarks carry `null,null` coordinates
        block = cdata.group(1)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block))
        station_id = _ID_RE.search(text)
        if station_id is None:
            return None

        bolds = [re.sub(r"<[^>]+>", "", b).strip() for b in _BOLD_RE.findall(block)]
        name_tag = _NAME_RE.search(placemark)
        first_obs, last_obs = _series_span(text)
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": station_id.group(1),
            "name": (name_tag.group(1).strip() if name_tag else None) or None,
            "lon": lon,
            "lat": lat,
            "compartment": compartment,
            "variables": [],
            "elevation_m": _altitude_m(text),
            "first_obs": first_obs,
            "last_obs": last_obs,
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": {
                "id": station_id.group(1),
                "country": bolds[1] if len(bolds) > 1 else None,
                "description": text.strip(),
            },
        }


def _stem(href: str) -> str:
    name = href.rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".kml") else name


def _altitude_m(text: str) -> float | None:
    match = _ALT_RE.search(text)
    if match is None or match.group(1).lower() == "null":
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _series_span(text: str) -> tuple[str | None, str | None]:
    """Earliest start / latest end across every `du D-M-YYYY au D-M-YYYY`
    range in the placemark description, as ISO date strings."""
    ranges = _DATE_RANGE_RE.findall(text)
    if not ranges:
        return None, None
    starts = [f"{y}-{int(m):02d}-{int(d):02d}" for d, m, y, *_ in ranges]
    ends = [f"{y}-{int(m):02d}-{int(d):02d}" for *_, d, m, y in ranges]
    return min(starts), max(ends)
