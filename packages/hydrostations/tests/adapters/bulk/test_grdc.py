import io
import zipfile

import pandas as pd

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.grdc import GrdcAdapter


def _zip_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    xlsx_buf = io.BytesIO()
    df.to_excel(xlsx_buf, index=False)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("GRDC_Stations.xlsx", xlsx_buf.getvalue())
    return zip_buf.getvalue()


def _row(grdc_no=1104150, station="SIDI BELATAR", lat=36.02, long=0.27, area=43750.0,
         altitude=2.0, t_start=1976, t_end=2001) -> dict:
    return {
        "grdc_no": grdc_no,
        "station": station,
        "country": "DZ",
        "lat": lat,
        "long": long,
        "area": area,
        "altitude": altitude,
        "t_start": t_start,
        "t_end": t_end,
    }


def test_fetch_stations_parses_catalogue(monkeypatch, register_entries):
    monkeypatch.setattr(GrdcAdapter, "_fetch_zip_bytes", lambda self: _zip_bytes([_row()]))

    frame = GrdcAdapter(register_entries["grdc"]).fetch_stations(compartment="Q")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source"] == "grdc"
    assert row["source_id"] == "1104150"
    assert row["name"] == "SIDI BELATAR"
    assert row["compartment"] == "Q"
    assert row["elevation_m"] == 2.0
    assert row["catchment_area_km2"] == 43750.0
    assert str(row["first_obs"].date()) == "1976-01-01"
    assert str(row["last_obs"].date()) == "2001-12-31"
    assert bool(row["redistribution_ok"]) is False


def test_fetch_stations_treats_missing_value_sentinel_as_null(monkeypatch, register_entries):
    monkeypatch.setattr(
        GrdcAdapter,
        "_fetch_zip_bytes",
        lambda self: _zip_bytes([_row(area=-999.0, altitude=-999.0)]),
    )

    frame = GrdcAdapter(register_entries["grdc"]).fetch_stations(compartment="Q")

    row = frame.iloc[0]
    assert pd.isna(row["elevation_m"])
    assert pd.isna(row["catchment_area_km2"])


def test_fetch_stations_filters_by_bbox_client_side(monkeypatch, register_entries):
    monkeypatch.setattr(
        GrdcAdapter,
        "_fetch_zip_bytes",
        lambda self: _zip_bytes(
            [
                _row(grdc_no=1, lat=40.0, long=-105.0),
                _row(grdc_no=2, lat=10.0, long=10.0),
            ]
        ),
    )

    frame = GrdcAdapter(register_entries["grdc"]).fetch_stations(
        bbox=BBox(min_lon=-108.0, min_lat=38.0, max_lon=-102.0, max_lat=41.0), compartment="Q"
    )

    assert len(frame) == 1
    assert frame.iloc[0]["source_id"] == "1"


def test_fetch_stations_unsupported_compartment_skips_fetch(monkeypatch, register_entries):
    def _raise(self):
        raise AssertionError("should not fetch for an unsupported compartment")

    monkeypatch.setattr(GrdcAdapter, "_fetch_zip_bytes", _raise)

    frame = GrdcAdapter(register_entries["grdc"]).fetch_stations(compartment="GW")

    assert frame.empty
