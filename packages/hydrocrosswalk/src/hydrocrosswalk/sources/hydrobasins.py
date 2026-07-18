"""HydroBASINS drainage-basin polygons (HydroSHEDS / WWF).

Downloads a continent-level HydroBASINS shapefile at a given Pfafstetter
level from HydroSHEDS's data server (data.hydrosheds.org).

IMPORTANT -- these polygon geometries are used internally for the spatial
join only. The published crosswalk never re-exports them: the HydroSHEDS
License Agreement (Appendix A of the HydroSHEDS Technical Documentation,
which HydroBASINS is explicitly covered by) grants distribution rights for
Derivative Works but states "In no event shall Licensee license or
distribute the Licensed Materials as a stand-alone product" (Section
2.1.2). Only the derived HYBAS_ID/PFAF_ID integer join keys are carried
into `hydrocrosswalk`'s output. This is a reasonable-effort compliance
interpretation, not a legal certification -- get it reviewed before a real
publication of the dataset.

Citation: Lehner, B., Grill G. (2013): Global river hydrography and network
routing: baseline data and new approaches to study the world's large river
systems. Hydrological Processes, 27(15): 2171-2186.
See https://www.hydrosheds.org/products/hydrobasins.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import httpx

_BASE_URL = "https://data.hydrosheds.org/file/hydrobasins/standard"

# HydroSHEDS's continent region codes (version 1.1), used in HydroBASINS
# file names, e.g. hybas_af_lev04_v1c.zip.
REGIONS = ("af", "ar", "as", "au", "eu", "gr", "na", "sa", "si")

HYDROBASINS_LICENSE_NOTE = (
    "hybas_id/pfaf_id reference WWF's HydroBASINS dataset "
    "(c) World Wildlife Fund, Inc. Only integer IDs are carried in this "
    "crosswalk; the underlying HydroBASINS polygon geometries are not "
    "redistributed here, per the HydroSHEDS License Agreement Section "
    "2.1.2. See https://www.hydrosheds.org/products/hydrobasins and cite "
    "Lehner & Grill (2013), Hydrological Processes 27(15): 2171-2186."
)


def fetch_hydrobasins(region: str, level: int) -> gpd.GeoDataFrame:
    if region not in REGIONS:
        raise ValueError(f"unknown HydroBASINS region {region!r}; known regions: {REGIONS}")
    if not 1 <= level <= 12:
        raise ValueError(f"HydroBASINS level must be 1-12, got {level}")

    filename = f"hybas_{region}_lev{level:02d}_v1c"
    url = f"{_BASE_URL}/{filename}.zip"
    response = httpx.get(url, timeout=120.0, follow_redirects=True)
    response.raise_for_status()

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"{filename}.zip"
        zip_path.write_bytes(response.content)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        shp_path = next(Path(tmp).glob("*.shp"))
        return gpd.read_file(shp_path)
