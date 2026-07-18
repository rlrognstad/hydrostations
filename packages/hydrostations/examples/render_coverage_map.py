"""Render a world map of declared network/compartment coverage.

Pulls directly from hydrostations' own adapter registry -- each adapter's
`coverage` bboxes, `compartments`, and `license` -- and writes a single
self-contained interactive HTML map. No live station data, no external
requests to build it: this shows the same static declaration
`hydrostations.lookup_coverage()` uses, just as a picture instead of a
lookup. Whether each adapter is actually wired up (vs. a stub) is checked
live with one small, remote-ocean probe request per adapter, so that part
does need network access.

This is meant to need almost no editing as adapters are added: any new
adapter's `coverage`/`compartments` are picked up automatically from the
registry. The one thing you may need to touch is `NETWORK_COLOR_SLOTS`
below -- see its docstring.

Run:
    uv run --package hydrostations python examples/render_coverage_map.py
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import httpx

from hydrostations.adapters.base import BBox
from hydrostations.core import _default_registry
from hydrostations.exceptions import AdapterNotImplementedError

SVG_WIDTH = 1000
SVG_HEIGHT = 500  # 2:1 for a full -180..180 x -90..90 Plate Carree world map

# Natural Earth 110m countries (public domain, no attribution required) --
# fetched once at build time purely for visual context (which continent is
# this box even over?), then simplified and embedded like everything else.
# Coarse on purpose: this is a backdrop, not real admin-boundary data.
_WORLD_OUTLINE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)
_WORLD_OUTLINE_SIMPLIFY_TOLERANCE = 0.2  # degrees

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
    "NWIS": "#2a78d6",  # slot 1 blue
    "BOM": "#008300",  # slot 2 green
    "WISE": "#e87ba4",  # slot 3 magenta
    "HIDROWEB": "#eda100",  # slot 4 yellow
    "SIEREM": "#1baf7a",  # slot 5 aqua
}
_FALLBACK_COLOR = "#898781"  # muted ink; used if a network has no assigned slot yet

GLOBAL_COVERAGE_THRESHOLD = (359.0, 179.0)  # (min lon-span, min lat-span) to count as "global"


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


def fetch_world_outline() -> list[dict]:
    response = httpx.get(_WORLD_OUTLINE_URL, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    gdf = gpd.GeoDataFrame.from_features(response.json()["features"], crs="EPSG:4326")
    gdf["geometry"] = gdf.simplify(_WORLD_OUTLINE_SIMPLIFY_TOLERANCE, preserve_topology=True)

    countries = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        rings = [
            [project_point(x, y) for x, y in p.exterior.coords]
            for p in polys
            if p.exterior is not None
        ]
        if rings:
            countries.append({"rings": rings})
    return countries


def build_map_data() -> dict:
    world = fetch_world_outline()
    regional = []
    global_networks = []

    for adapter in _default_registry().values():
        implemented = _is_implemented(adapter)
        entry_base = {
            "network": adapter.network,
            "compartments": list(adapter.compartments),
            "license": adapter.license,
            "implemented": implemented,
        }
        if _is_global(adapter.coverage):
            global_networks.append(entry_base)
            continue
        color = NETWORK_COLOR_SLOTS.get(adapter.network, _FALLBACK_COLOR)
        regional.append(
            {
                **entry_base,
                "color": color,
                "boxes": [project_bbox(b) for b in adapter.coverage],
            }
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
  .land-poly {{ fill: var(--land-fill); stroke: var(--land-stroke); stroke-width: 0.75; }}
  .graticule {{ stroke: var(--graticule); stroke-width: 1; }}
  .global-wash {{ fill: var(--global-wash); }}
  .coverage-box {{ fill-opacity: 0.14; stroke-width: 1.6; cursor: pointer; }}
  .coverage-box:hover {{ fill-opacity: 0.28; }}
  .coverage-box.stub {{ stroke-dasharray: 5 3; fill-opacity: 0.06; }}
  .coverage-box.stub:hover {{ fill-opacity: 0.14; }}
  .box-label {{
    font-size: 11px;
    font-weight: 600;
    fill: var(--text-primary);
    paint-order: stroke;
    stroke: var(--surface-1);
    stroke-width: 3px;
    pointer-events: none;
  }}

  .legend {{ flex: 0 0 240px; font-size: 13px; }}
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
    align-items: flex-start;
    gap: 8px;
    padding: 6px 4px;
    border-radius: 6px;
  }}
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

  @media (max-width: 720px) {{
    .layout {{ flex-direction: column; }}
    .legend {{ flex: 1 1 auto; }}
  }}
</style>

<div class="viz-root">
  <div class="viz-card">
    <h1>hydrostations: declared network coverage</h1>
    <p class="subtitle">
      Each network's own declared coverage area, generated directly from the
      adapter registry -- not live station counts. Solid borders are wired-up
      adapters (verified with a live probe request when this page was
      generated); dashed are stubs with a declared area but no working
      fetch yet. Hover any region for details.
    </p>
    <div class="layout">
      <div class="map-wrap">
        <svg id="map" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"></svg>
      </div>
      <div class="legend" id="legend">
        <h2>Networks</h2>
      </div>
    </div>
  </div>
</div>
<div id="tooltip"></div>

<script>
(function () {{
  const data = {data_json};

  const svg = document.getElementById('map');
  const legend = document.getElementById('legend');
  const tooltip = document.getElementById('tooltip');
  const wrap = document.querySelector('.map-wrap');
  const NS = 'http://www.w3.org/2000/svg';

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
  }}

  for (const net of data.regional) {{
    for (const box of net.boxes) {{
      const rect = el('rect', {{
        x: box.x, y: box.y, width: box.w, height: box.h,
        fill: net.color, stroke: net.color,
        class: 'coverage-box' + (net.implemented ? '' : ' stub'),
      }});
      rect.addEventListener('mousemove', e => showTooltip(e, net.network,
        net.compartments.join(', ') + (net.implemented ? '' : ' &middot; not yet implemented')));
      rect.addEventListener('mouseleave', hideTooltip);
      svg.appendChild(rect);

      if (box.w > 40 && box.h > 14) {{
        const label = el('text', {{
          x: box.x + box.w / 2, y: box.y + box.h / 2,
          'text-anchor': 'middle', 'dominant-baseline': 'middle',
          class: 'box-label',
        }});
        label.textContent = net.network;
        label.style.pointerEvents = 'none';
        svg.appendChild(label);
      }}
    }}
  }}

  function legendRow(colorSwatchHtml, label, meta) {{
    const row = document.createElement('div');
    row.className = 'legend-item';
    row.innerHTML = colorSwatchHtml +
      '<div class="legend-text"><span class="legend-label">' + label +
      '</span><span class="legend-meta">' + meta + '</span></div>';
    return row;
  }}

  for (const net of data.regional) {{
    const swatchClass = 'swatch' + (net.implemented ? '' : ' stub');
    const swatchStyle = net.implemented ? ('background:' + net.color + ';') : '';
    const swatch = '<span class="' + swatchClass + '" style="' + swatchStyle + '"></span>';
    const status = net.implemented ? 'implemented' : 'stub';
    legend.appendChild(legendRow(swatch, net.network, net.compartments.join(', ') + ' &middot; ' + status));
  }}
  for (const net of data.global_networks) {{
    const swatchClass = 'swatch' + (net.implemented ? '' : ' stub');
    const swatch = '<span class="' + swatchClass + '" style="background: var(--global-wash);"></span>';
    const status = net.implemented ? 'implemented' : 'stub';
    legend.appendChild(legendRow(swatch, net.network + ' (global)', net.compartments.join(', ') + ' &middot; ' + status));
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
        print(f"  {net['network']}: {net['compartments']} ({status})")


if __name__ == "__main__":
    main()
