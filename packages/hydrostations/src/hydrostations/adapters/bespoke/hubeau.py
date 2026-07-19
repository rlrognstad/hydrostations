"""Hub'Eau (France, Systeme d'Information sur l'Eau) adapter.

Clean JSON REST, confirmed live for both compartments: real server-side
`bbox` filtering, `page`/`size` pagination with a `next` URL in the
response body. No auth.

Q and GW are genuinely different sub-APIs under the same Hub'Eau platform
(hydrometrie/referentiel/stations vs niveaux_nappes/stations) with
different id/name/coordinate field names -- config-driven per compartment
rather than assumed, same as KiWIS's per-compartment parameter types.

Bespoke (not a generalized protocol adapter): Hub'Eau's REST shape is
platform-specific to this one operator, no second known user, so there's
no reuse payoff in abstracting it.

GW station records have no dedicated station-name field in the API --
`nom_commune` (the commune/town name) is the closest available label, not
a proper station name; see the register entry's own notes.

Q's period-of-record fields are tz-aware "...Z"-suffixed ISO8601; GW's are
bare dates. Both go through `schema.parse_timestamp()`, which handles
either shape.
"""

from __future__ import annotations

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.register.models import HubeauCompartmentConfig
from hydrostations.schema import parse_timestamp, stations_frame_from_records


class HubeauAdapter(SourceAdapter):
    protocol = "hubeau"

    def fetch_stations(
        self,
        *,
        bbox: BBox | None = None,
        compartment: str | None = None,
    ) -> gpd.GeoDataFrame:
        cfg = self.entry.hubeau
        compartments = [compartment] if compartment else list(self.compartments)
        records = []
        for c in compartments:
            if c not in self.compartments or c not in cfg.compartments:
                continue
            records.extend(self._fetch_compartment(bbox=bbox, compartment=c))
        return stations_frame_from_records(records)

    def _fetch_compartment(self, *, bbox: BBox | None, compartment: str) -> list[dict]:
        cfg = self.entry.hubeau
        ccfg = cfg.compartments[compartment]
        url = f"{self.entry.endpoint}/{ccfg.path}"
        params = {"format": "json", "size": str(cfg.page_size)}
        if bbox is not None:
            params["bbox"] = f"{bbox.min_lon},{bbox.min_lat},{bbox.max_lon},{bbox.max_lat}"

        records = []
        while url is not None:
            response = httpx.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            payload = response.json()
            records.extend(
                self._row_to_record(row, compartment, ccfg) for row in payload.get("data", [])
            )
            url = payload.get("next")
            params = None  # already baked into the "next" URL

        return records

    def _row_to_record(
        self, row: dict, compartment: str, ccfg: HubeauCompartmentConfig
    ) -> dict:
        return {
            "source": self.source,
            "source_class": self.source_class,
            "source_id": str(row[ccfg.id_field]),
            "name": row.get(ccfg.name_field),
            "lon": row[ccfg.lon_field],
            "lat": row[ccfg.lat_field],
            "compartment": compartment,
            "variables": [],
            "first_obs": (
                parse_timestamp(row.get(ccfg.first_obs_field)) if ccfg.first_obs_field else None
            ),
            "last_obs": (
                parse_timestamp(row.get(ccfg.last_obs_field)) if ccfg.last_obs_field else None
            ),
            "wsi": None,
            "license": self.license,
            "redistribution_ok": self.redistribution_ok,
            "raw": row,
        }
