import geopandas as gpd
from shapely.geometry import box

import hydrocrosswalk.crosswalk as crosswalk_module
from hydrocrosswalk.crosswalk import build_crosswalk
from hydrocrosswalk.sources.hydrobasins import HYDROBASINS_LICENSE_NOTE


def _fake_basins():
    return gpd.GeoDataFrame(
        {
            "HYBAS_ID": [1, 2],
            "PFAF_ID": [10, 20],
            "MAIN_BAS": [1, 1],
        },
        geometry=[box(0, 0, 1, 1), box(10, 10, 11, 11)],
        crs="EPSG:4326",
    )


def _fake_admin():
    return gpd.GeoDataFrame(
        {"shapeName": ["Testland"], "shapeGroup": ["TST"]},
        geometry=[box(-1, -1, 2, 2)],
        crs="EPSG:4326",
    )


def test_build_crosswalk_joins_basins_admin_and_h3(monkeypatch):
    monkeypatch.setattr(crosswalk_module, "fetch_hydrobasins", lambda region, level: _fake_basins())
    monkeypatch.setattr(
        crosswalk_module, "fetch_admin_boundaries", lambda countries, adm_level: _fake_admin()
    )

    table = build_crosswalk(
        region="af",
        hydrobasins_level=4,
        countries=["TST"],
        h3_resolution=6,
    )

    assert len(table) > 0
    assert set(table["hybas_id"]) <= {1, 2}
    # basin 1 (box 0,0-1,1) falls inside the admin polygon; basin 2 doesn't.
    matched = table[table["hybas_id"] == 1]
    unmatched = table[table["hybas_id"] == 2]
    assert (matched["shapeName"] == "Testland").all()
    assert unmatched["shapeName"].isna().all()
    assert (table["hydrobasins_license_note"] == HYDROBASINS_LICENSE_NOTE).all()
    # never re-export basin geometry
    assert "geometry" not in table.columns


def test_build_crosswalk_bbox_filters_basins(monkeypatch):
    monkeypatch.setattr(crosswalk_module, "fetch_hydrobasins", lambda region, level: _fake_basins())
    monkeypatch.setattr(
        crosswalk_module, "fetch_admin_boundaries", lambda countries, adm_level: _fake_admin()
    )

    table = build_crosswalk(
        region="af",
        hydrobasins_level=4,
        countries=["TST"],
        h3_resolution=6,
        bbox=(0, 0, 1, 1),
    )

    assert set(table["hybas_id"]) == {1}
