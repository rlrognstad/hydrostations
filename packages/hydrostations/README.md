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

Early scaffold. Implemented adapters: **NWIS** (USGS), **BoM** (Australia).
Stubbed, not yet implemented: **WISE** (EEA), **HidroWeb** (ANA, Brazil),
**SIEREM** (HydroSciences Montpellier) — each has a module docstring
explaining why (bulk-download-only, auth-gated, or portal-only access,
respectively) and what's needed before it can be built.

`basin=` resolution is currently a small hardcoded name-to-bounding-box
lookup (`hydrostations.basins`), a placeholder pending integration with the
HydroBASINS x GADM x H3 crosswalk.

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
re-publishing raw records.
