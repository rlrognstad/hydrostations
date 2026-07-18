import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import httpx
import pytest
import respx
from shapely.geometry import box

from hydrocrosswalk.sources.hydrobasins import fetch_hydrobasins


def _fake_hydrobasins_zip_bytes() -> bytes:
    gdf = gpd.GeoDataFrame(
        {
            "HYBAS_ID": [1040000010, 1040003990],
            "NEXT_DOWN": [0, 0],
            "MAIN_BAS": [1040000010, 1040003990],
            "PFAF_ID": [1110, 1121],
        },
        geometry=[box(0, 0, 1, 1), box(1, 1, 2, 2)],
        crs="EPSG:4326",
    )
    with tempfile.TemporaryDirectory() as tmp:
        shp_path = Path(tmp) / "hybas_af_lev04_v1c.shp"
        gdf.to_file(shp_path)
        zip_path = Path(tmp) / "out.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in Path(tmp).glob("hybas_af_lev04_v1c.*"):
                zf.write(f, arcname=f.name)
        return zip_path.read_bytes()


def test_fetch_hydrobasins_parses_real_shapefile_structure(mocked_api: respx.MockRouter):
    mocked_api.get(
        "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_af_lev04_v1c.zip"
    ).mock(return_value=httpx.Response(200, content=_fake_hydrobasins_zip_bytes()))

    gdf = fetch_hydrobasins(region="af", level=4)

    assert len(gdf) == 2
    assert set(gdf["HYBAS_ID"]) == {1040000010, 1040003990}
    assert gdf.crs is not None


def test_fetch_hydrobasins_rejects_unknown_region():
    with pytest.raises(ValueError, match="unknown HydroBASINS region"):
        fetch_hydrobasins(region="xx", level=4)


def test_fetch_hydrobasins_rejects_invalid_level():
    with pytest.raises(ValueError, match="level must be 1-12"):
        fetch_hydrobasins(region="af", level=13)
