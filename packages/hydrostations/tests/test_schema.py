import pytest

from hydrostations.schema import COLUMNS, empty_stations_frame, stations_frame_from_records


def test_empty_stations_frame_has_expected_columns():
    frame = empty_stations_frame()
    assert list(frame.columns) == [c for c in COLUMNS if c != "geometry"] + ["geometry"]
    assert frame.empty


def test_stations_frame_from_records_builds_geometry():
    frame = stations_frame_from_records(
        [
            {
                "station_id": "1",
                "name": "Test Station",
                "lon": 2.5,
                "lat": 12.0,
                "compartment": "Q",
                "network": "NWIS",
                "start_date": "2000-01-01",
                "end_date": None,
                "wsi": None,
                "license": "Public domain",
                "redistribution_ok": True,
            }
        ]
    )
    assert len(frame) == 1
    assert frame.geometry.iloc[0].x == 2.5
    assert frame.geometry.iloc[0].y == 12.0
    assert bool(frame["redistribution_ok"].iloc[0]) is True


def test_stations_frame_from_records_rejects_unknown_compartment():
    with pytest.raises(ValueError, match="unknown compartment"):
        stations_frame_from_records(
            [
                {
                    "station_id": "1",
                    "name": "Test Station",
                    "lon": 0.0,
                    "lat": 0.0,
                    "compartment": "bogus",
                    "network": "NWIS",
                    "start_date": None,
                    "end_date": None,
                    "wsi": None,
                    "license": "Public domain",
                    "redistribution_ok": True,
                }
            ]
        )
