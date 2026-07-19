"""Render a world map of declared network/compartment coverage.

Pulls directly from hydrostations' own adapter registry -- each adapter's
`coverage` bboxes, `compartments`, and `license` -- and writes a single
self-contained interactive HTML map. No live station data, no external
requests to build it: this shows the same static declaration
`hydrostations.lookup_coverage()` uses, just as a picture instead of a
lookup. Whether each adapter is actually wired up (vs. a stub) is checked
live with one small, remote-ocean probe request per adapter, so that part
does need network access.

Each source's declared coverage is rendered as a real country/continent
shape, not the raw rectangle -- but always *clipped to that source's own
declared bbox(es)*, never beyond it. A raw country polygon can include
far-flung territory a source never actually claims (confirmed live:
Natural Earth's "France" polygon includes French Guiana, ~7,000km from
Hub'Eau's real mainland-only coverage box) -- clipping to the declared
box first means the rendered shape can only ever be as accurate or *more*
precise than the box, never less, and never overstates it. Sources with
no entry in `_SOURCE_REGION_MATCH` fall back to the plain rectangle.

This is meant to need almost no editing as adapters are added: any new
adapter's `coverage`/`compartments` are picked up automatically from the
registry. You may want to add a `NETWORK_COLOR_SLOTS` entry (see its
docstring) and a `_SOURCE_REGION_MATCH` entry for a real-shape outline.

Run:
    uv run --package hydrostations python examples/render_coverage_map.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import httpx
from shapely.geometry import box as shapely_box
from shapely.ops import unary_union

from hydrostations.adapters.base import BBox
from hydrostations.core import _default_registry
from hydrostations.exceptions import AdapterNotImplementedError

SVG_WIDTH = 1000
SVG_HEIGHT = 500  # 2:1 for a full -180..180 x -90..90 Plate Carree world map

# Natural Earth 110m countries (public domain, no attribution required) --
# also the source of the real per-source coverage shapes, not just the
# backdrop, so this is fetched as a GeoDataFrame (ADM0_A3/CONTINENT kept)
# rather than pre-simplified rings.
_WORLD_OUTLINE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)
_WORLD_OUTLINE_SIMPLIFY_TOLERANCE = 0.2  # degrees
_COVERAGE_SIMPLIFY_TOLERANCE = 0.05  # finer than the backdrop -- these are the real subject

# A bbox picked to be almost certainly station-free for every current and
# future network (open Pacific, far from any coastline) -- used only to
# check, live, whether an adapter is wired up or still a stub. Small enough
# to be fast and to never trip a real API's bbox-size limit.
_PROBE_BBOX = BBox(min_lon=-140.0, min_lat=10.0, max_lon=-139.999, max_lat=10.001)

# Fixed categorical color order (the dataviz palette's validated 8-hue set,
# assigned in order -- never reassign an existing network's slot, and never
# reuse a hue). GGMN doesn't need a slot: coverage spanning the full globe
# is auto-detected below and rendered as a neutral background wash instead
# of competing for a hue. Add new *regional* networks at the next unused
# slot; past slot 8, fold additional networks into a shared "Other" style
# or split the map into facets -- the palette's own guidance for going
# past 4-8 categorical series.
NETWORK_COLOR_SLOTS: dict[str, str] = {
    "nwis": "#2a78d6",  # slot 1 blue
    "bom": "#008300",  # slot 2 green
    "wise": "#e87ba4",  # slot 3 magenta
    "hidroweb": "#eda100",  # slot 4 yellow
    "sierem": "#1baf7a",  # slot 5 aqua
    "eccc": "#eb6834",  # slot 6 orange
    "hubeau": "#4a3aa7",  # slot 7 violet
    "nrfa": "#e34948",  # slot 8 red
}
_FALLBACK_COLOR = "#898781"  # muted ink; used if a network has no assigned slot yet

GLOBAL_COVERAGE_THRESHOLD = (359.0, 179.0)  # (min lon-span, min lat-span) to count as "global"

# Real-shape matching per source: a country (by Natural Earth ADM0_A3 -- NOT
# ISO_A3, which is "-99" for France and some other countries in this
# dataset, confirmed live) or a list of continents. Always clipped to the
# source's own declared coverage bbox(es) afterward -- see module
# docstring. Sources not listed here (or whose match produces an empty
# clip) fall back to the plain rectangle.
_SOURCE_REGION_MATCH: dict[str, dict] = {
    "nwis": {"iso_a3": ["USA"]},
    "bom": {"iso_a3": ["AUS"]},
    "hidroweb": {"iso_a3": ["BRA"]},
    "eccc": {"iso_a3": ["CAN"]},
    "hubeau": {"iso_a3": ["FRA"]},
    "nrfa": {"iso_a3": ["GBR"]},
    "snotel": {"iso_a3": ["USA"]},
    "cocorahs": {"iso_a3": ["USA"]},
    "wise": {"continent": ["Europe"]},
    "sierem": {"continent": ["Africa", "Europe"]},
}


def _is_global(coverage: tuple[BBox, ...]) -> bool:
    min_lon_span, min_lat_span = GLOBAL_COVERAGE_THRESHOLD
    return any(
        (b.max_lon - b.min_lon) >= min_lon_span and (b.max_lat - b.min_lat) >= min_lat_span
        for b in coverage
    )


def _is_implemented(adapter) -> bool:
    try:
        adapter.fetch_stations(bbox=_PROBE_BBOX, compartment=adapter.compartments[0])
    except AdapterNotImplementedError:
        return False
    except Exception:
        # A real network/API error still proves this isn't a stub -- stubs
        # raise AdapterNotImplementedError unconditionally, before any
        # request is made.
        return True
    return True


def project_point(lon: float, lat: float) -> list[float]:
    """Plate Carree: lon -180..180 -> x 0..SVG_WIDTH, lat 90..-90 -> y 0..SVG_HEIGHT."""
    x = (lon + 180.0) / 360.0 * SVG_WIDTH
    y = (90.0 - lat) / 180.0 * SVG_HEIGHT
    return [round(x, 1), round(y, 1)]


def project_bbox(bbox: BBox) -> dict[str, float]:
    x = (bbox.min_lon + 180.0) / 360.0 * SVG_WIDTH
    y = (90.0 - bbox.max_lat) / 180.0 * SVG_HEIGHT
    w = (bbox.max_lon - bbox.min_lon) / 360.0 * SVG_WIDTH
    h = (bbox.max_lat - bbox.min_lat) / 180.0 * SVG_HEIGHT
    return {"x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1)}


def geom_to_rings(geom, *, simplify_tolerance: float) -> list[list[list[float]]]:
    if geom is None or geom.is_empty:
        return []
    geom = geom.simplify(simplify_tolerance, preserve_topology=True)
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    rings = []
    for p in polys:
        if p.exterior is None:
            continue
        rings.append([project_point(x, y) for x, y in p.exterior.coords])
    return rings


def fetch_countries() -> gpd.GeoDataFrame:
    response = httpx.get(_WORLD_OUTLINE_URL, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    gdf = gpd.GeoDataFrame.from_features(response.json()["features"], crs="EPSG:4326")
    return gdf[["ADM0_A3", "CONTINENT", "geometry"]]


def real_coverage_shape(source_id: str, coverage: tuple[BBox, ...], countries: gpd.GeoDataFrame):
    """A source's real country/continent shape, clipped to its own declared
    bbox(es) -- see module docstring for why the clip matters. Returns None
    if there's no region match or the clip is empty, so the caller can fall
    back to the plain rectangle."""
    match = _SOURCE_REGION_MATCH.get(source_id)
    if match is None:
        return None

    if "iso_a3" in match:
        selected = countries[countries["ADM0_A3"].isin(match["iso_a3"])]
    else:
        selected = countries[countries["CONTINENT"].isin(match["continent"])]
    if selected.empty:
        return None

    declared = unary_union([shapely_box(b.min_lon, b.min_lat, b.max_lon, b.max_lat) for b in coverage])
    clipped = unary_union(selected.geometry.to_list()).intersection(declared)
    return clipped if not clipped.is_empty else None


def build_map_data() -> dict:
    countries = fetch_countries()
    world = [
        {"rings": geom_to_rings(geom, simplify_tolerance=_WORLD_OUTLINE_SIMPLIFY_TOLERANCE)}
        for geom in countries.geometry
        if geom is not None and not geom.is_empty
    ]
    world = [c for c in world if c["rings"]]

    regional = []
    global_networks = []

    for adapter in _default_registry().values():
        implemented = _is_implemented(adapter)
        entry_base = {
            "network": adapter.source,
            "compartments": list(adapter.compartments),
            "license": adapter.license,
            "implemented": implemented,
        }
        if _is_global(adapter.coverage):
            global_networks.append(entry_base)
            continue

        color = NETWORK_COLOR_SLOTS.get(adapter.source, _FALLBACK_COLOR)
        shape = real_coverage_shape(adapter.source, adapter.coverage, countries)
        if shape is not None:
            rings = geom_to_rings(shape, simplify_tolerance=_COVERAGE_SIMPLIFY_TOLERANCE)
            centroid = shape.centroid
            label_at = project_point(centroid.x, centroid.y)
            regional.append({**entry_base, "color": color, "rings": rings, "label_at": label_at})
        else:
            regional.append(
                {**entry_base, "color": color, "boxes": [project_bbox(b) for b in adapter.coverage]}
            )

    return {
        "width": SVG_WIDTH,
        "height": SVG_HEIGHT,
        "world": world,
        "regional": regional,
        "global_networks": global_networks,
    }


HTML_TEMPLATE = """<title>hydrostations network coverage</title>
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --muted:          #898781;
    --border:         rgba(11,11,11,0.10);
    --graticule:      #e1e0d9;
    --global-wash:    rgba(137,135,129,0.16);
    --land-fill:      #f2f1ec;
    --land-stroke:    #c3c2b7;
    --chip-bg:        #f2f1ec;
    --chip-active:    #0b0b0b;
    --chip-active-fg: #fcfcfb;
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
      --graticule:      #2c2c2a;
      --global-wash:    rgba(137,135,129,0.22);
      --land-fill:      #232322;
      --land-stroke:    #3a3a38;
      --chip-bg:        #232322;
      --chip-active:    #ffffff;
      --chip-active-fg: #0d0d0d;
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
    --graticule:      #2c2c2a;
    --global-wash:    rgba(137,135,129,0.22);
    --land-fill:      #232322;
    --land-stroke:    #3a3a38;
    --chip-bg:        #232322;
    --chip-active:    #ffffff;
    --chip-active-fg: #0d0d0d;
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
  .subtitle {{ font-size: 13px; color: var(--text-secondary); margin: 0 0 14px; max-width: 70ch; }}

  .compartment-filter {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 16px;
  }}
  .chip {{
    font: inherit;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.02em;
    padding: 5px 11px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--chip-bg);
    color: var(--text-secondary);
    cursor: pointer;
  }}
  .chip.active {{ background: var(--chip-active); color: var(--chip-active-fg); border-color: var(--chip-active); }}

  .layout {{ display: flex; flex-direction: column; gap: 18px; }}
  .map-wrap {{
    position: relative;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    background: var(--surface-1);
  }}
  svg {{ display: block; width: 100%; height: auto; }}
  .land-poly {{ fill: var(--land-fill); stroke: var(--land-stroke); stroke-width: 0.75; }}
  .graticule {{ stroke: var(--graticule); stroke-width: 1; }}
  .global-wash {{ fill: var(--global-wash); }}
  .coverage-shape {{ fill-opacity: 0.22; stroke-width: 1.2; cursor: pointer; }}
  .coverage-shape:hover {{ fill-opacity: 0.4; }}
  .coverage-shape.stub {{ stroke-dasharray: 5 3; fill-opacity: 0.08; }}
  .coverage-shape.stub:hover {{ fill-opacity: 0.16; }}
  .dimmed {{ display: none; }}
  .box-label {{
    font-size: 11px;
    font-weight: 600;
    fill: var(--text-primary);
    paint-order: stroke;
    stroke: var(--surface-1);
    stroke-width: 3px;
    pointer-events: none;
  }}

  .legend {{ font-size: 13px; border-top: 1px solid var(--border); padding-top: 16px; }}
  .legend h2 {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    font-weight: 600;
    margin: 0 0 10px;
  }}
  .legend-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 2px 12px;
  }}
  .legend-item {{
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 6px 4px;
    border-radius: 6px;
    cursor: pointer;
    user-select: none;
  }}
  .legend-item:hover {{ background: var(--border); }}
  .legend-item input {{ margin: 3px 0 0; accent-color: var(--text-primary); }}
  .swatch {{
    width: 14px;
    height: 14px;
    flex: 0 0 auto;
    border-radius: 3px;
    margin-top: 1px;
  }}
  .swatch.stub {{ opacity: 0.45; border: 1.5px dashed var(--muted); background: none !important; }}
  .legend-text {{ display: flex; flex-direction: column; }}
  .legend-label {{ color: var(--text-primary); font-weight: 600; }}
  .legend-meta {{ color: var(--muted); font-size: 11px; }}
  .legend-note {{
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.5;
  }}

  #tooltip {{
    position: absolute;
    pointer-events: none;
    background: var(--text-primary);
    color: var(--surface-1);
    font-size: 12px;
    line-height: 1.4;
    padding: 6px 9px;
    border-radius: 6px;
    max-width: 260px;
    transform: translate(-50%, -100%);
    margin-top: -10px;
    opacity: 0;
    transition: opacity 0.08s;
    z-index: 10;
  }}
  #tooltip.visible {{ opacity: 1; }}
  #tooltip .tt-kind {{ color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 10px; letter-spacing: 0.03em; }}

  @media (max-width: 480px) {{
    .legend-grid {{ grid-template-columns: 1fr; }}
  }}
</style>

<div class="viz-root">
  <div class="viz-card">
    <div class="compartment-filter" id="compartment-filter"></div>
    <div class="layout">
      <div class="map-wrap">
        <svg id="map" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"></svg>
      </div>
      <div class="legend">
        <h2>Networks</h2>
        <div class="legend-grid" id="legend"></div>
      </div>
    </div>
  </div>
</div>
<div id="tooltip"></div>

<script>
(function () {{
  const data = {data_json};
  const ALL_COMPARTMENTS = ["Q", "GW", "P", "SM", "ET", "SW", "SNOW", "WQ"];

  const svg = document.getElementById('map');
  const legend = document.getElementById('legend');
  const compartmentFilterEl = document.getElementById('compartment-filter');
  const tooltip = document.getElementById('tooltip');
  const wrap = document.querySelector('.map-wrap');
  const NS = 'http://www.w3.org/2000/svg';

  const activeCompartments = new Set(ALL_COMPARTMENTS);
  const activeNetworks = new Set(
    [...data.regional, ...data.global_networks].map(n => n.network)
  );

  function el(tag, attrs) {{
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  }}

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

  function ringsToPath(rings) {{
    return rings.map(ring => 'M' + ring.map(p => p.join(',')).join('L') + 'Z').join(' ');
  }}

  function matchesFilter(net) {{
    if (!activeNetworks.has(net.network)) return false;
    return net.compartments.some(c => activeCompartments.has(c));
  }}

  // world outline (context only, no interactivity of its own)
  for (const country of data.world) {{
    svg.appendChild(el('path', {{d: ringsToPath(country.rings), class: 'land-poly'}}));
  }}

  // graticule every 30 degrees lon, 30 degrees lat
  for (let lon = -180; lon <= 180; lon += 30) {{
    const x = (lon + 180) / 360 * data.width;
    svg.appendChild(el('line', {{x1: x, y1: 0, x2: x, y2: data.height, class: 'graticule'}}));
  }}
  for (let lat = -90; lat <= 90; lat += 30) {{
    const y = (90 - lat) / 180 * data.height;
    svg.appendChild(el('line', {{x1: 0, y1: y, x2: data.width, y2: y, class: 'graticule'}}));
  }}

  const shapeEls = [];

  // global-coverage networks: a single background wash, not a competing hue
  for (const net of data.global_networks) {{
    const rect = el('rect', {{
      x: 0, y: 0, width: data.width, height: data.height,
      class: 'global-wash' + (net.implemented ? '' : ' stub'),
    }});
    rect.addEventListener('mousemove', e => showTooltip(e, net.network,
      'Global coverage &middot; ' + net.compartments.join(', ') +
      (net.implemented ? '' : ' &middot; not yet implemented')));
    rect.addEventListener('mouseleave', hideTooltip);
    svg.appendChild(rect);
    shapeEls.push({{ el: rect, net }});
  }}

  for (const net of data.regional) {{
    const shapes = net.rings
      ? [{{ path: ringsToPath(net.rings) }}]
      : net.boxes.map(box => ({{ box }}));

    for (const shape of shapes) {{
      const attrs = shape.path
        ? {{ d: shape.path, fill: net.color, stroke: net.color, class: 'coverage-shape' + (net.implemented ? '' : ' stub') }}
        : {{ x: shape.box.x, y: shape.box.y, width: shape.box.w, height: shape.box.h,
             fill: net.color, stroke: net.color, class: 'coverage-shape' + (net.implemented ? '' : ' stub') }};
      const shapeEl = el(shape.path ? 'path' : 'rect', attrs);
      shapeEl.addEventListener('mousemove', e => showTooltip(e, net.network,
        net.compartments.join(', ') + (net.implemented ? '' : ' &middot; not yet implemented')));
      shapeEl.addEventListener('mouseleave', hideTooltip);
      svg.appendChild(shapeEl);
      shapeEls.push({{ el: shapeEl, net }});
    }}

    const labelAt = net.label_at || (net.boxes.length && net.boxes[0].w > 40 && net.boxes[0].h > 14
      ? {{ x: net.boxes[0].x + net.boxes[0].w / 2, y: net.boxes[0].y + net.boxes[0].h / 2 }}
      : null);
    if (labelAt) {{
      const x = labelAt.x !== undefined ? labelAt.x : labelAt[0];
      const y = labelAt.y !== undefined ? labelAt.y : labelAt[1];
      const label = el('text', {{
        x, y, 'text-anchor': 'middle', 'dominant-baseline': 'middle', class: 'box-label',
      }});
      label.textContent = net.network;
      label.style.pointerEvents = 'none';
      svg.appendChild(label);
      shapeEls.push({{ el: label, net, isLabel: true }});
    }}
  }}

  function applyFilters() {{
    for (const {{ el, net }} of shapeEls) {{
      el.classList.toggle('dimmed', !matchesFilter(net));
    }}
  }}

  // compartment filter chips
  for (const c of ALL_COMPARTMENTS) {{
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip active';
    chip.textContent = c;
    chip.addEventListener('click', () => {{
      if (activeCompartments.has(c)) {{
        activeCompartments.delete(c);
        chip.classList.remove('active');
      }} else {{
        activeCompartments.add(c);
        chip.classList.add('active');
      }}
      applyFilters();
    }});
    compartmentFilterEl.appendChild(chip);
  }}

  function legendRow(net, colorSwatchHtml, label, meta) {{
    const row = document.createElement('label');
    row.className = 'legend-item';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = true;
    input.addEventListener('change', () => {{
      if (input.checked) activeNetworks.add(net.network);
      else activeNetworks.delete(net.network);
      applyFilters();
    }});
    row.appendChild(input);
    const rest = document.createElement('span');
    rest.style.display = 'contents';
    rest.innerHTML = colorSwatchHtml +
      '<div class="legend-text"><span class="legend-label">' + label +
      '</span><span class="legend-meta">' + meta + '</span></div>';
    row.appendChild(rest);
    return row;
  }}

  for (const net of data.regional) {{
    const swatchClass = 'swatch' + (net.implemented ? '' : ' stub');
    const swatchStyle = net.implemented ? ('background:' + net.color + ';') : '';
    const swatch = '<span class="' + swatchClass + '" style="' + swatchStyle + '"></span>';
    legend.appendChild(legendRow(net, swatch, net.network, net.compartments.join(', ')));
  }}
  for (const net of data.global_networks) {{
    const swatchClass = 'swatch' + (net.implemented ? '' : ' stub');
    const swatch = '<span class="' + swatchClass + '" style="background: var(--global-wash);"></span>';
    legend.appendChild(legendRow(net, swatch, net.network + ' (global)', net.compartments.join(', ')));
  }}
}})();
</script>
"""


def render_html(map_data: dict) -> str:
    return HTML_TEMPLATE.format(
        width=map_data["width"],
        height=map_data["height"],
        data_json=json.dumps(map_data),
    )


def main() -> None:
    map_data = build_map_data()
    html = render_html(map_data)
    out_path = Path(__file__).parent / "coverage_map.html"
    out_path.write_text(html)
    print(f"wrote {out_path} ({len(html) / 1024:.0f} KB)")
    for net in map_data["regional"] + map_data["global_networks"]:
        status = "implemented" if net["implemented"] else "stub"
        shape_kind = "real shape" if net.get("rings") else "bbox"
        print(f"  {net['network']}: {net['compartments']} ({status}, {shape_kind})")


if __name__ == "__main__":
    main()
