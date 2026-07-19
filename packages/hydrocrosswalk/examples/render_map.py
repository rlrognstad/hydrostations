"""Render an interactive HTML map of a basin's crosswalk partitions + stations.

Fetches HydroBASINS sub-basins, geoBoundaries admin units, and generates an
H3 grid for a region, dissolves the sub-basins into an overall basin
outline, optionally pulls real `hydrostations` station data for the same
region, and writes a single self-contained HTML file with all layers
overlaid on an SVG map -- a toggleable legend and hover tooltips, no
external requests at view time (everything is embedded in the output file).

This script imports both `hydrocrosswalk` and `hydrostations`, but neither
package imports the other -- gluing them together is the example's job, not
either library's. See docs/crosswalk-and-stations-walkthrough.md for the
narrative walkthrough this script formalizes.

Run:
    uv run --package hydrocrosswalk python examples/render_map.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box

from hydrocrosswalk.crosswalk import assign_crosswalk
from hydrocrosswalk.h3grid import cell_to_polygon, cells_for_geometry
from hydrocrosswalk.sources.geoboundaries import fetch_admin_boundaries
from hydrocrosswalk.sources.hydrobasins import fetch_hydrobasins

BBox = tuple[float, float, float, float]

# Murray-Darling basin (Australia) -- the same region used throughout the
# crosswalk + stations walkthrough. Edit these to render a different basin.
REGION = "au"
HYDROBASINS_LEVEL = 4
COUNTRIES = ["AUS"]
ADMIN_LEVEL = "ADM1"
H3_RESOLUTION = 3
BBOX: BBox = (138.811933, -37.679167, 152.4875, -24.591667)
# A point inside the Murray-Darling basin (near Wentworth, NSW), used to
# identify the correct HydroBASINS MAIN_BAS grouping -- see build_map_data().
REFERENCE_POINT = Point(144.0, -35.0)
DROP_ADMIN_NAMES = {"Other Territories"}  # offshore fragments that distort the projection
SIMPLIFY_TOLERANCE = 0.02  # degrees; keeps the embedded HTML a reasonable size
SVG_WIDTH = 1000
STATION_NETWORK = "bom"
STATION_COMPARTMENT = "Q"

TITLE = "Murray-Darling basin: crosswalk partitions + real stations"
SUBTITLE = (
    "Every polygon and point below is live data pulled via <code>hydrocrosswalk</code> "
    "and <code>hydrostations</code> -- the basin outline, HydroBASINS sub-basins, "
    "geoBoundaries admin units, an H3 hex grid, and real station locations. Toggle "
    "layers in the legend; hover any shape or dot for details."
)


def make_projector(bbox: BBox, width: int) -> tuple[callable, float]:
    """Equirectangular projection (cosine-corrected for latitude) into an
    `width`-wide SVG coordinate space with north up. Fine for a single
    region at this scale; not suitable for anything continent-sized or
    larger."""
    min_lon, min_lat, max_lon, max_lat = bbox
    cos_lat = math.cos(math.radians((min_lat + max_lat) / 2))
    lon_span = (max_lon - min_lon) * cos_lat
    lat_span = max_lat - min_lat
    height = width * (lat_span / lon_span)

    def project(lon: float, lat: float) -> list[float]:
        x = (lon - min_lon) * cos_lat / lon_span * width
        y = (max_lat - lat) / lat_span * height
        return [round(x, 1), round(y, 1)]

    return project, round(height, 1)


def polygon_rings(geom, project) -> list[list[list[float]]]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        geoms = [geom]
    elif geom.geom_type == "MultiPolygon":
        geoms = list(geom.geoms)
    else:
        return []  # stray points/lines from clipping slivers
    return [
        [project(x, y) for x, y in g.exterior.coords] for g in geoms if g.exterior is not None
    ]


def layer_to_json(gdf, project, *, name_field=None, id_field=None) -> list[dict]:
    out = []
    for _, row in gdf.iterrows():
        rings = polygon_rings(row.geometry, project)
        if not rings:
            continue
        entry = {"rings": rings}
        if name_field:
            entry["name"] = row[name_field]
        if id_field:
            entry["id"] = str(row[id_field])
        out.append(entry)
    return out


def fetch_stations() -> gpd.GeoDataFrame | None:
    """Pull real station data via hydrostations for the same region.

    Imported lazily so this script still runs (without the stations layer)
    if hydrostations isn't installed alongside hydrocrosswalk.
    """
    try:
        from hydrostations import get_stations
    except ImportError:
        print("hydrostations not installed -- skipping the stations layer")
        return None
    return get_stations(
        basin="murray-darling", source=STATION_NETWORK, compartment=STATION_COMPARTMENT
    )


def build_map_data() -> dict:
    bbox_geom = box(*BBOX)

    # Select sub-basins by MAIN_BAS (all sub-basins draining to the same
    # outlet), not by "intersects bbox" -- a bbox-intersects filter also
    # pulls in unrelated sub-basins from neighboring catchments that merely
    # clip the rectangle's edge, which both inflates the shape past the
    # bbox and chops it into straight lines wherever those foreign basins
    # take over. MAIN_BAS grouping is what the display bbox itself was
    # originally derived from (see hydrostations.basins), so no clipping is
    # needed here at all -- the real, irregular watershed shape already
    # fits.
    all_basins = fetch_hydrobasins(region=REGION, level=HYDROBASINS_LEVEL)
    containing = all_basins[all_basins.contains(REFERENCE_POINT)]
    main_bas = containing.iloc[0]["MAIN_BAS"]
    basins = all_basins[all_basins["MAIN_BAS"] == main_bas][
        ["HYBAS_ID", "PFAF_ID", "MAIN_BAS", "geometry"]
    ]

    # admin (state) polygons genuinely extend far beyond the basin and DO
    # need a hard clip, or they'd render all the way out to e.g. Sydney/Melbourne.
    admin = fetch_admin_boundaries(COUNTRIES, adm_level=ADMIN_LEVEL)
    admin = admin[~admin["shapeName"].isin(DROP_ADMIN_NAMES)]
    admin = gpd.clip(admin[["shapeName", "geometry"]], bbox_geom)
    admin = admin[~admin.geometry.is_empty & admin.geometry.notna()]

    # get_stations(basin=...) only filters by the rectangular bbox, not the
    # true basin polygon -- so it also returns stations from unrelated
    # nearby catchments (e.g. coastal NSW rivers) that merely fall inside
    # that rectangle. assign_crosswalk() does the precise point-in-polygon
    # match against the real sub-basins fetched above; dropping unmatched
    # rows keeps only stations actually inside the Murray-Darling basin.
    stations = fetch_stations()
    if stations is not None:
        stations = assign_crosswalk(stations, h3_resolution=H3_RESOLUTION, basins=basins, admin=admin)
        n_before = len(stations)
        stations = stations[stations["hybas_id"].notna()]
        print(f"stations: kept {len(stations)}/{n_before} actually inside the basin polygon")

    # H3 grid and the basin outline both come from the same unclipped union,
    # so all three (basins, boundary, h3) show the basin's real shape.
    boundary = basins.geometry.union_all()
    cells = cells_for_geometry(boundary, resolution=H3_RESOLUTION)
    h3_gdf = gpd.GeoDataFrame(
        {"h3_cell": list(cells)},
        geometry=[cell_to_polygon(c) for c in cells],
        crs="EPSG:4326",
    )

    basins["geometry"] = basins.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    admin["geometry"] = admin.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    boundary = boundary.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    basins = basins[~basins.geometry.is_empty & basins.geometry.notna()]
    admin = admin[~admin.geometry.is_empty & admin.geometry.notna()]

    project, height = make_projector(BBOX, SVG_WIDTH)

    return {
        "width": SVG_WIDTH,
        "height": height,
        "boundary": {"rings": polygon_rings(boundary, project), "name": "Basin outline"},
        "admin": layer_to_json(admin, project, name_field="shapeName"),
        "basins": layer_to_json(basins, project, id_field="HYBAS_ID"),
        "h3": layer_to_json(h3_gdf, project, id_field="h3_cell"),
        "stations": (
            []
            if stations is None
            else [
                {
                    "x": project(pt.x, pt.y)[0],
                    "y": project(pt.x, pt.y)[1],
                    "name": row["name"],
                    "id": row["source_id"],
                }
                for pt, (_, row) in zip(stations.geometry, stations.iterrows(), strict=True)
            ]
        ),
    }


HTML_TEMPLATE = """<title>{title}</title>
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --muted:          #898781;
    --border:         rgba(11,11,11,0.10);
    --admin:          #2a78d6;   /* slot 1 blue */
    --basins:         #008300;   /* slot 2 green */
    --h3:             #e87ba4;   /* slot 3 magenta */
    --stations:       #eda100;   /* slot 4 yellow */
    --boundary:       #3a3a38;   /* neutral ink, not a categorical slot */
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --muted:          #898781;
      --border:         rgba(255,255,255,0.10);
      --admin:          #3987e5;
      --basins:         #008300;
      --h3:             #d55181;
      --stations:       #c98500;
      --boundary:       #d6d5cc;
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --muted:          #898781;
    --border:         rgba(255,255,255,0.10);
    --admin:          #3987e5;
    --basins:         #008300;
    --h3:             #d55181;
    --stations:       #c98500;
    --boundary:       #d6d5cc;
  }}

  * {{ box-sizing: border-box; }}
  body {{ margin: 0; }}
  .viz-root {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page);
    color: var(--text-primary);
    padding: 24px;
    min-height: 100vh;
  }}
  .viz-card {{
    max-width: 1100px;
    margin: 0 auto;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px 24px;
  }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 4px; }}
  .subtitle {{ font-size: 13px; color: var(--text-secondary); margin: 0 0 16px; max-width: 70ch; }}
  .layout {{ display: flex; gap: 20px; align-items: flex-start; }}
  .map-wrap {{
    position: relative;
    flex: 1 1 auto;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    background: var(--surface-1);
  }}
  svg {{ display: block; width: 100%; height: auto; }}

  .legend {{ flex: 0 0 220px; font-size: 13px; }}
  .legend h2 {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    font-weight: 600;
    margin: 0 0 10px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 4px;
    border-radius: 6px;
    cursor: pointer;
    user-select: none;
  }}
  .legend-item:hover {{ background: var(--border); }}
  .legend-item input {{ accent-color: var(--text-primary); margin: 0; }}
  .swatch {{ width: 18px; height: 10px; flex: 0 0 auto; border-radius: 2px; }}
  .swatch.line {{ height: 0; border-top-width: 2.5px; border-top-style: solid; }}
  .swatch.dashed {{ border-top-style: dashed; }}
  .swatch.dotted {{ border-top-style: dotted; border-top-width: 3px; }}
  .swatch.dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .legend-label {{ color: var(--text-primary); }}
  .legend-count {{ color: var(--muted); font-size: 12px; margin-left: auto; }}
  .legend-note {{
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.5;
  }}

  .boundary-poly {{ fill: none; stroke: var(--boundary); stroke-width: 3; stroke-linejoin: round; }}
  .basin-poly {{ fill: var(--basins); fill-opacity: 0.06; stroke: var(--basins); stroke-width: 1.6; stroke-dasharray: 6 3; }}
  .admin-poly {{ fill: none; stroke: var(--admin); stroke-width: 2; }}
  .h3-poly {{ fill: var(--h3); fill-opacity: 0.05; stroke: var(--h3); stroke-width: 1; stroke-dasharray: 1.5 2; }}
  .station-dot {{ fill: var(--stations); stroke: var(--surface-1); stroke-width: 1; }}
  .station-dot:hover, .basin-poly:hover, .admin-poly:hover, .h3-poly:hover, .boundary-poly:hover {{ filter: brightness(1.3); }}
  .hit {{ fill: transparent; stroke: transparent; stroke-width: 6px; cursor: pointer; }}

  .layer-hidden {{ display: none; }}

  #tooltip {{
    position: absolute;
    pointer-events: none;
    background: var(--text-primary);
    color: var(--surface-1);
    font-size: 12px;
    line-height: 1.4;
    padding: 6px 9px;
    border-radius: 6px;
    max-width: 220px;
    transform: translate(-50%, -100%);
    margin-top: -10px;
    opacity: 0;
    transition: opacity 0.08s;
    z-index: 10;
    white-space: nowrap;
  }}
  #tooltip.visible {{ opacity: 1; }}
  #tooltip .tt-kind {{ color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 10px; letter-spacing: 0.03em; }}

  @media (max-width: 720px) {{
    .layout {{ flex-direction: column; }}
    .legend {{ flex: 1 1 auto; }}
  }}
</style>

<div class="viz-root">
  <div class="viz-card">
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
    <div class="layout">
      <div class="map-wrap">
        <svg id="map" viewBox="{view_box}" xmlns="http://www.w3.org/2000/svg"></svg>
      </div>
      <div class="legend">
        <h2>Layers</h2>
        <label class="legend-item">
          <input type="checkbox" data-layer="boundary" checked>
          <span class="swatch line" style="border-color: var(--boundary); border-top-width: 3px;"></span>
          <span class="legend-label">Basin outline</span>
          <span class="legend-count" id="count-boundary"></span>
        </label>
        <label class="legend-item">
          <input type="checkbox" data-layer="admin" checked>
          <span class="swatch line" style="border-color: var(--admin);"></span>
          <span class="legend-label">Admin units</span>
          <span class="legend-count" id="count-admin"></span>
        </label>
        <label class="legend-item">
          <input type="checkbox" data-layer="basins" checked>
          <span class="swatch line dashed" style="border-color: var(--basins);"></span>
          <span class="legend-label">HydroBASINS sub-basins</span>
          <span class="legend-count" id="count-basins"></span>
        </label>
        <label class="legend-item">
          <input type="checkbox" data-layer="h3" checked>
          <span class="swatch line dotted" style="border-color: var(--h3);"></span>
          <span class="legend-label">H3 grid</span>
          <span class="legend-count" id="count-h3"></span>
        </label>
        <label class="legend-item">
          <input type="checkbox" data-layer="stations" checked>
          <span class="swatch dot" style="background: var(--stations);"></span>
          <span class="legend-label">Stations</span>
          <span class="legend-count" id="count-stations"></span>
        </label>
        <div class="legend-note">
          Basin and admin polygons are simplified for display and fetched fresh at
          render time from HydroSHEDS / geoBoundaries -- not redistributed as a
          bundled dataset. See docs/crosswalk-and-stations-walkthrough.md.
        </div>
      </div>
    </div>
  </div>
</div>
<div id="tooltip"></div>

<script>
(function () {{
  const data = {data_json};

  const svg = document.getElementById('map');
  const tooltip = document.getElementById('tooltip');
  const wrap = document.querySelector('.map-wrap');
  const NS = 'http://www.w3.org/2000/svg';

  function ringsToPath(rings) {{
    return rings.map(ring => 'M' + ring.map(p => p.join(',')).join('L') + 'Z').join(' ');
  }}

  function makeGroup(id) {{
    const g = document.createElementNS(NS, 'g');
    g.id = id;
    svg.appendChild(g);
    return g;
  }}

  const gBoundary = makeGroup('layer-boundary');
  const gAdmin = makeGroup('layer-admin');
  const gBasins = makeGroup('layer-basins');
  const gH3 = makeGroup('layer-h3');
  const gStations = makeGroup('layer-stations');

  function showTooltip(evt, kind, label) {{
    tooltip.innerHTML = '<div class="tt-kind">' + kind + '</div>' + label;
    tooltip.classList.add('visible');
    moveTooltip(evt);
  }}
  function moveTooltip(evt) {{
    const box = wrap.getBoundingClientRect();
    tooltip.style.left = (evt.clientX - box.left) + 'px';
    tooltip.style.top = (evt.clientY - box.top) + 'px';
  }}
  function hideTooltip() {{ tooltip.classList.remove('visible'); }}

  function addPolygonLayer(group, items, cssClass, kind, labelFn) {{
    for (const item of items) {{
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d', ringsToPath(item.rings));
      path.setAttribute('class', cssClass);
      path.addEventListener('mousemove', e => showTooltip(e, kind, labelFn(item)));
      path.addEventListener('mouseleave', hideTooltip);
      group.appendChild(path);
    }}
  }}

  addPolygonLayer(gBoundary, [data.boundary], 'boundary-poly', 'Basin', it => it.name);
  addPolygonLayer(gAdmin, data.admin, 'admin-poly', 'Admin unit', it => it.name);
  addPolygonLayer(gBasins, data.basins, 'basin-poly', 'HydroBASINS sub-basin', it => 'HYBAS_ID ' + it.id);
  addPolygonLayer(gH3, data.h3, 'h3-poly', 'H3 cell', it => it.id);

  for (const st of data.stations) {{
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', st.x);
    c.setAttribute('cy', st.y);
    c.setAttribute('r', 2.2);
    c.setAttribute('class', 'station-dot hit');
    c.addEventListener('mousemove', e => showTooltip(e, 'Station', st.name + ' (' + st.id + ')'));
    c.addEventListener('mouseleave', hideTooltip);
    gStations.appendChild(c);
  }}
  // repaint visible dots on top of the larger invisible hit targets
  for (const st of data.stations) {{
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', st.x);
    c.setAttribute('cy', st.y);
    c.setAttribute('r', 2.2);
    c.setAttribute('class', 'station-dot');
    c.style.pointerEvents = 'none';
    gStations.appendChild(c);
  }}

  document.getElementById('count-boundary').textContent = '1';
  document.getElementById('count-admin').textContent = data.admin.length;
  document.getElementById('count-basins').textContent = data.basins.length;
  document.getElementById('count-h3').textContent = data.h3.length;
  document.getElementById('count-stations').textContent = data.stations.length;

  const groups = {{ boundary: gBoundary, admin: gAdmin, basins: gBasins, h3: gH3, stations: gStations }};
  document.querySelectorAll('.legend-item input').forEach(input => {{
    input.addEventListener('change', () => {{
      groups[input.dataset.layer].classList.toggle('layer-hidden', !input.checked);
    }});
  }});
}})();
</script>
"""


def render_html(map_data: dict) -> str:
    pad = 50
    view_box = f"-{pad} -{pad} {map_data['width'] + 2 * pad} {map_data['height'] + 2 * pad}"
    return HTML_TEMPLATE.format(
        title=TITLE,
        subtitle=SUBTITLE,
        view_box=view_box,
        data_json=json.dumps(map_data),
    )


def main() -> None:
    map_data = build_map_data()
    html = render_html(map_data)
    out_path = Path(__file__).parent / "crosswalk_map.html"
    out_path.write_text(html)
    print(f"wrote {out_path} ({len(html) / 1024:.0f} KB)")
    print(
        f"  boundary: 1, admin: {len(map_data['admin'])}, basins: {len(map_data['basins'])}, "
        f"h3: {len(map_data['h3'])}, stations: {len(map_data['stations'])}"
    )


if __name__ == "__main__":
    main()
