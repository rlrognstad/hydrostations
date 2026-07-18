# Hydrostations hydrology packages

A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) containing
related, independently-installable Python packages:

- **[hydrostations](packages/hydrostations/)** — a unified station-catalog client for
  hydrological networks (USGS NWIS, BoM, and more).
- **[hydrocrosswalk](packages/hydrocrosswalk/)** — a HydroBASINS × geoBoundaries × H3
  crosswalk: joins drainage basins, administrative boundaries, and H3 cells into a
  single reference table.

Each package ships its own `pyproject.toml`, dependencies, and tests, and is
independently installable (`pip install ./packages/hydrostations`, etc.) — they're
developed together because they share a common purpose, not because they're coupled.

See [docs/crosswalk-and-stations-walkthrough.md](docs/crosswalk-and-stations-walkthrough.md)
for a runbook walking through both packages together: generate a crosswalk, pull
station data for the same region, then tag each station with its basin/H3 cell.

## Development

```bash
uv sync              # install all workspace members into one shared venv
uv run --package hydrostations pytest
uv run --package hydrocrosswalk pytest
```
