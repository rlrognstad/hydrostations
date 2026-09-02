# hydrostations

A unified station-catalog client for hydrological networks. One API over
multiple networks (USGS NWIS, BoM Water Data Online, and more to come),
returning a normalized GeoDataFrame with provenance.

```python
from hydrostations import get_stations

stations = get_stations(basin="niger", compartment="Q")
# -> GeoDataFrame: canonical_id, source, source_id, source_class, name,
#    geometry, compartment, variables, first_obs, last_obs, wsi, license,
#    redistribution_ok, raw, retrieved_at, and more -- see Schema below
```

## Status

Early scaffold. Implemented adapters: **NWIS** (USGS, Q + GW + lake/reservoir
SW), **BoM** (Australia),
**GGMN** (IGRAC, global groundwater), **WISE** (EEA, Europe), **HidroWeb**
(ANA, Brazil), **ECCC** (Water Survey of Canada), **Hub'Eau** (France, Q+GW),
**NRFA** (UK National River Flow Archive), **SNOTEL/SCAN** (USDA NRCS, first
real SNOW + SM sources), **CoCoRaHS** (US volunteer network, P + SNOW),
**GHCN-Daily** (NOAA/NCEI, global precipitation), **GRDC** (Global Runoff
Data Centre, global streamflow catalogue, first `redistribution_ok: false`
source), **ISMN** (International Soil Moisture Network, global SM + P +
SNOW), **AmeriFlux** (Americas, first `ET` source, first per-record
`license`/`redistribution_ok`), **Water Quality Portal** (USGS/EPA/NWQMC
joint aggregator, US, first `WQ` source — the last compartment that had
no source), **PSMSL** (Permanent Service for Mean Sea Level, global
coastal tide gauges — first global `SW` source), **SIEREM** (HydroSciences
Montpellier — first African source: Q + P from ~276 static per-basin KML
files, `live: false`), **IDEAM** (Colombia's national hydro-met agency, Q +
P — first `socrata` protocol adapter, first South American source outside
Brazil), **waterinfo.be** (VMM, Flanders — Q + P + GW; the second `kiwis`
protocol user, first non-BoM validation of that adapter). Every registered
source now has a working adapter.

Worth knowing: GGMN, WISE, HidroWeb, and SIEREM were *all* stubbed as
"blocked" in the original design doc, and live investigation found each
assumption outdated -- GGMN's MOU only governs data contributors, WISE has
a real queryable SQL API, HidroWeb's station inventory (as opposed to its
time-series download) needs no auth at all, and SIEREM's Google-Earth
layer is a machine-readable KML tree. Re-check a "blocked" source's real
access model before trusting an old note as current.

`hydrostations.lookup_coverage(polygon)` answers "which networks and
compartments are declared to cover this area" using each adapter's own
coarse, hand-declared coverage bboxes -- no live API calls, no station
counts:

```python
from hydrostations import lookup_coverage
from shapely.geometry import box

lookup_coverage(box(4.0, 50.0, 7.0, 54.0))
# -> {"wise": ["Q", "GW", "SW"], "ggmn": ["GW"]}
```

`basin=` resolution is a small name-to-bounding-box lookup
(`hydrostations.basins`) used only to pre-filter adapter API queries -- the
bboxes are real HydroBASINS-derived bounds, not hand-drawn. For actually
assigning each station to a basin/H3 cell, use
[`hydrocrosswalk.assign_crosswalk()`](../hydrocrosswalk/) on this package's
output:

```python
from hydrostations import get_stations
from hydrocrosswalk import assign_crosswalk

stations = get_stations(source="nwis", compartment="Q")
enriched = assign_crosswalk(
    stations, h3_resolution=6, region="na", hydrobasins_level=4, countries=["USA"]
)
# -> adds h3_cell, hybas_id, pfaf_id, and geoBoundaries admin fields
```

The two packages don't depend on each other -- `hydrostations` stays free of
`hydrocrosswalk`'s heavier geospatial dependencies, and `assign_crosswalk()`
works on any GeoDataFrame of points, not just this package's output.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management.

```bash
uv sync              # create the venv and install dependencies
uv run pytest        # run tests
uv run ruff check .  # lint
```

## Schema

Every adapter returns a GeoDataFrame with the same columns:

| Column | Meaning |
|---|---|
| `canonical_id` | `f"{source}:{source_id}"` -- provisional, not deduplicated across sources |
| `source` | Register source id, e.g. `"nwis"`, `"bom"` (lowercase) |
| `source_id` | Source-native station identifier |
| `source_class` | `agency` (official hydrological/met service) / `research` (academic compilation or observatory, e.g. GGMN, SIEREM) / `citizen` (volunteer network, e.g. CoCoRaHS) |
| `name` | Station name |
| `geometry` | Point location (EPSG:4326) |
| `compartment` | `Q` (streamflow) / `GW` (groundwater) / `P` (precipitation) / `SM` (soil moisture) / `ET` (evapotranspiration) / `SW` (surface water: lakes, reservoirs, coastal) / `SNOW` / `WQ` (water quality) |
| `variables` | Native parameter code/type strings available at this station (not a canonical vocabulary yet) |
| `elevation_m` | Populated by NRFA, SNOTEL/SCAN, GRDC (where not `-999`-sentinel missing), AmeriFlux, and the Water Quality Portal (from `VerticalMeasure`, feet converted to metres); null elsewhere |
| `catchment_area_km2` | Populated by NRFA and GRDC (where not `-999`-sentinel missing); null elsewhere |
| `positional_uncertainty_m` / `reporting_interval` | Real fields, currently null for every adapter -- placeholders |
| `first_obs` / `last_obs` | Period of record, where available |
| `wsi` | WIGOS Station Identifier, where a crosswalk exists |
| `license` | Source data license |
| `redistribution_ok` | Whether raw records from this source may be redistributed |
| `retrieved_at` | Timestamp this record was fetched (stamped once per `get_stations()` call) |
| `raw` | Untouched native record as returned by the source (dict) |

Sources are driven by a YAML register (`hydrostations/register/sources/*.yaml`), validated
against pydantic models in `hydrostations.register`, and grouped by protocol under
`hydrostations.adapters.protocols` (KiWIS, WFS, ArcGIS Feature Server, OGC API-Features, Socrata --
shared adapter classes, config-only per source), `hydrostations.adapters.bespoke` (NWIS, WISE,
Hub'Eau, Water Quality Portal -- hand-written fetch logic, no second known user of any of these), and
`hydrostations.adapters.bulk` (SIEREM, NRFA, SNOTEL/SCAN, CoCoRaHS, GHCN-Daily, GRDC, ISMN,
AmeriFlux, PSMSL -- sources with no server-side spatial filter, whether a static file snapshot, a live
fetch-everything endpoint, or a live fetch-per-jurisdiction endpoint).

`redistribution_ok` exists because not every source permits it -- GRDC is
the first `False` case, since its discharge series require a signed
Declaration of the Data User and prohibit redistribution (only its station
catalogue, fetched anonymously over FTP, is reachable here) — code that consumes
`hydrostations` output should check this flag before caching or
re-publishing raw records. It's a blunt boolean, though: GGMN's real license
is CC BY-NC-SA 4.0 (non-commercial, share-alike), which doesn't fit a plain
yes/no -- `redistribution_ok=True` there because redistribution genuinely is
allowed, but check the `license` string for the actual conditions before
relying on it commercially. AmeriFlux goes a step further -- its 837 sites
split across two real data policies (CC BY 4.0 vs. an older "Legacy" policy
requiring PI approval), so it's the first adapter to set `license`/
`redistribution_ok` per-record rather than copying one value from the
register entry onto every row.
