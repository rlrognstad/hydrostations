# hydrostations

A unified station-catalog client for hydrological networks. One API over
multiple networks (USGS NWIS, BoM Water Data Online, and more to come),
returning a normalized GeoDataFrame with provenance.

```python
from hydrostations import get_stations

stations = get_stations(basin="niger", compartment="Q")
# -> GeoDataFrame: station_id, name, geometry, compartment, network,
#    start_date, end_date, wsi, license, redistribution_ok
```

## Status

Early scaffold. Implemented adapters: **NWIS** (USGS), **BoM** (Australia),
**GGMN** (IGRAC, global groundwater), **WISE** (EEA, Europe), **HidroWeb**
(ANA, Brazil). Stubbed, not yet implemented: **SIEREM** (HydroSciences
Montpellier) — its module docstring explains the access model as last
investigated (no live REST API; ~647 static per-basin KML files, no
server-side spatial filtering, needs a bulk-fetch-then-filter design
rather than a simple per-query adapter).

Worth knowing: GGMN, WISE, and HidroWeb were *all* stubbed as "blocked" in
the original design doc, and live investigation found each assumption
outdated -- GGMN's MOU only governs data contributors, WISE has a real
queryable SQL API, and HidroWeb's station inventory (as opposed to its
time-series download) needs no auth at all. Re-check a stub's real access
model before trusting its docstring's blocker as current.

`hydrostations.lookup_coverage(polygon)` answers "which networks and
compartments are declared to cover this area" using each adapter's own
coarse, hand-declared coverage bboxes -- no live API calls, no station
counts:

```python
from hydrostations import lookup_coverage
from shapely.geometry import box

lookup_coverage(box(4.0, 50.0, 7.0, 54.0))
# -> {"WISE": ["Q", "GW", "other"], "GGMN": ["GW"]}
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

stations = get_stations(network="nwis", compartment="Q")
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
| `station_id` | Network-native station identifier |
| `name` | Station name |
| `geometry` | Point location (EPSG:4326) |
| `compartment` | `Q` (streamflow) / `GW` (groundwater) / `P` (precipitation) / `other` |
| `network` | Source network (e.g. `NWIS`) |
| `start_date` / `end_date` | Period of record, where available |
| `wsi` | WIGOS Station Identifier, where a crosswalk exists |
| `license` | Source data license |
| `redistribution_ok` | Whether raw records from this source may be redistributed |

`redistribution_ok` exists because not every source permits it (GRDC, once
its adapter is built, will be the first `False` case) — code that consumes
`hydrostations` output should check this flag before caching or
re-publishing raw records. It's a blunt boolean, though: GGMN's real license
is CC BY-NC-SA 4.0 (non-commercial, share-alike), which doesn't fit a plain
yes/no -- `redistribution_ok=True` there because redistribution genuinely is
allowed, but check the `license` string for the actual conditions before
relying on it commercially.
