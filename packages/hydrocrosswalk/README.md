# hydrocrosswalk

Joins drainage basins ([HydroBASINS](https://www.hydrosheds.org/products/hydrobasins)),
administrative boundaries ([geoBoundaries](https://www.geoboundaries.org/)), and
[H3](https://h3geo.org/) hex cells into a single reference table. Any location that's
already been resolved to an H3 cell can be looked up against a basin ID and an admin
unit at once, instead of doing three separate spatial joins.

```python
from hydrocrosswalk import build_crosswalk

table = build_crosswalk(
    region="af",                 # HydroBASINS continent code
    hydrobasins_level=4,         # Pfafstetter level (1=coarse ... 12=fine)
    countries=["NER", "MLI", "GIN", "NGA", "BEN", "BFA", "CIV", "CMR", "TCD", "DZA"],
    h3_resolution=4,
    bbox=(-12.0, 4.0, 16.0, 25.0),  # optional: restrict to one basin/region
)
# -> DataFrame: h3_cell, h3_resolution, hybas_id, pfaf_id, main_bas,
#    hydrobasins_level, shapeName, shapeISO, shapeGroup, admin_license, ...
```

This is a **pipeline, not a published dataset**: every call fetches fresh from
HydroSHEDS and geoBoundaries and joins locally. Nothing is cached, bundled, or
redistributed by this package — see "Licensing" below for why that matters.

## Performance

A regional run (10 countries, 68 level-4 HydroBASINS sub-basins, H3 resolution 4,
~6,200 output rows — the Niger basin, roughly 2.1M km²) takes about **10 seconds**,
dominated by network I/O against HydroSHEDS/geoBoundaries rather than computation.
A full-continent or global, fine-resolution run would be a different order of
magnitude (more countries × admin levels, larger basin files) and hasn't been
exercised here.

## Licensing

- **HydroBASINS** (WWF/HydroSHEDS) is covered by a license that permits use but
  states: *"In no event shall Licensee license or distribute the Licensed Materials
  as a stand-alone product"* (HydroSHEDS License Agreement, Appendix A, Section
  2.1.2). Because of this, **`hydrocrosswalk` never re-exports HydroBASINS polygon
  geometries** — only the derived `hybas_id`/`pfaf_id` integer join keys are
  carried into the output. This is a reasonable-effort compliance interpretation,
  not a legal certification; get it reviewed before publishing computed output
  from this pipeline anywhere. See
  [hydrosheds.org/products/hydrobasins](https://www.hydrosheds.org/products/hydrobasins).
- **geoBoundaries** boundaries are openly licensed, but the exact license **varies
  per country** by underlying source (some CC BY 4.0, others CC BY-SA, etc.) —
  `hydrocrosswalk` captures the real `admin_license` value per record rather than
  assuming one blanket license.
- **H3** cell indexes are a public, standard identifier scheme; carrying them
  forward introduces no licensing concerns of its own.

## Development

```bash
uv run --package hydrocrosswalk pytest
uv run --package hydrocrosswalk ruff check .
```
