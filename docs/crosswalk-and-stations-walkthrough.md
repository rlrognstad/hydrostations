# Runbook: generate a crosswalk, then pull and tag station data

Walks through the two packages together: build a HydroBASINS × geoBoundaries ×
H3 reference grid with `hydrocrosswalk`, pull real station data with
`hydrostations` for the same region, then tag each station with its exact
basin/H3 cell/admin unit using `hydrocrosswalk.assign_crosswalk()`.

Both packages fetch live data on every call — nothing here is cached or
bundled. Expect real network I/O at each step.

This example uses the Murray-Darling basin (Australia) because it's one of
the named basins in `hydrostations.basins` *and* has a real, implemented
adapter (BoM) behind it, so every step below uses genuine data end to end.

## Prerequisites

```bash
uv sync   # installs both packages into the shared workspace venv
```

## Step 1 — Generate the crosswalk for a region

```python
from hydrocrosswalk import build_crosswalk

# Murray-Darling bbox -- the same one hydrostations.basins derives from
# real HydroBASINS geometry (see hydrostations/src/hydrostations/basins.py).
bbox = (138.811933, -37.679167, 152.4875, -24.591667)

table = build_crosswalk(
    region="au",            # HydroBASINS continent code for Australia
    hydrobasins_level=4,    # Pfafstetter level: coarser sub-basins
    countries=["AUS"],      # geoBoundaries ISO3 codes to join against
    h3_resolution=4,
    bbox=bbox,
)
```

**Result (as run 2026-07-18):** 1,346 H3 cells covering 25 distinct
HydroBASINS level-4 sub-basins, each tagged with its Australian admin unit.
Took ~11 seconds, dominated by the HydroBASINS/geoBoundaries downloads.

This table is the crosswalk itself — a lookup from location → basin → admin
— independent of any station data. It answers "what basin/admin unit is at
this H3 cell?" for the whole region, whether or not a station exists there.

## Step 2 — Pull real station data for the same region

```python
from hydrostations import get_stations

# basin= resolves to the same bbox used to build the crosswalk above.
stations = get_stations(basin="murray-darling", source="bom", compartment="Q")
```

**Result:** 3,323 real streamflow stations from BoM Water Data Online.

**Operational note:** BoM's API returned a transient `500 Internal Server
Error` on the first attempt during this walkthrough; a simple retry
succeeded. This adapter has no built-in retry logic yet — treat BoM calls as
occasionally flaky and retry on 5xx.

Also note: this bbox is the real, HydroBASINS-derived one (tightened during
the crosswalk-integration work), not the original hand-drawn box — it
returned 3,323 stations here vs. 4,253 under the old, looser bbox. If you're
comparing results against an earlier run, the bbox itself may be why counts
differ.

## Step 3 — Tag each station with its exact basin/H3 cell/admin unit

```python
from hydrocrosswalk import assign_crosswalk

enriched = assign_crosswalk(
    stations,
    h3_resolution=4,       # match the resolution used to build the grid in step 1
    region="au",
    hydrobasins_level=4,
    countries=["AUS"],
)
```

**Result:** all of `stations`' original columns, plus `h3_cell`, `hybas_id`,
`pfaf_id`, `main_bas`, and the geoBoundaries admin fields
(`shapeName`/`shapeGroup`/...). In this run: 3,322 of 3,323 stations matched
a basin (1 unmatched — likely a coastal/boundary edge case); the 21 distinct
basins actually touched by real stations were all a subset of the 25 basins
in the step-1 grid (some sub-basins simply have no gauge in them, which is
expected).

`assign_crosswalk` re-fetches HydroBASINS/geoBoundaries data by default —
pass pre-fetched `basins=`/`admin=` (from `fetch_hydrobasins`/
`fetch_admin_boundaries`) if you're calling it repeatedly against the same
region, to avoid re-downloading each time.

## Sanity-checking the two steps against each other

Because both steps draw from the same HydroBASINS source, every basin ID
seen on a real station should already appear in the step-1 grid:

```python
grid_basins = set(table["hybas_id"].dropna())
station_basins = set(enriched["hybas_id"].dropna())
assert station_basins <= grid_basins  # no station basin should be "new"
```

If this assertion ever fails, it means the two calls used different
region/level/bbox parameters (or HydroBASINS data changed upstream) — treat
it as a signal the two steps have drifted out of sync, not a HydroBASINS bug.

## Why `hydrostations` and `hydrocrosswalk` don't depend on each other

`assign_crosswalk()` works on *any* GeoDataFrame with a `geometry` column of
points — `hydrostations`' output is just one example. Keeping the two
packages decoupled means `hydrostations` users aren't forced to install
`hydrocrosswalk`'s heavier geospatial dependencies (`h3`, `pyarrow`) unless
they actually want basin/H3 enrichment.
