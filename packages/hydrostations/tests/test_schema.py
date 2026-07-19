import pytest

from hydrostations.schema import COLUMNS, empty_stations_frame, stations_frame_from_records


def _record(**overrides):
    record = {
        "source": "nwis",
        "source_id": "1",
        "name": "Test Station",
        "lon": 2.5,
        "lat": 12.0,
        "compartment": "Q",
        "first_obs": "2000-01-01",
        "last_obs": None,
        "wsi": None,
        "license": "Public domain",
        "redistribution_ok": True,
    }
    record.update(overrides)
    return record


def test_empty_stations_frame_has_expected_columns():
    frame = empty_stations_frame()
    assert list(frame.columns) == list(COLUMNS)
    assert frame.empty


def test_stations_frame_from_records_builds_geometry():
    frame = stations_frame_from_records([_record()])

    assert len(frame) == 1
    assert frame.geometry.iloc[0].x == 2.5
    assert frame.geometry.iloc[0].y == 12.0
    assert bool(frame["redistribution_ok"].iloc[0]) is True


def test_stations_frame_from_records_derives_canonical_id():
    frame = stations_frame_from_records([_record(source="bom", source_id="410730")])

    assert frame["canonical_id"].iloc[0] == "bom:410730"


def test_stations_frame_from_records_respects_explicit_canonical_id():
    frame = stations_frame_from_records([_record(canonical_id="custom:id")])

    assert frame["canonical_id"].iloc[0] == "custom:id"


def test_stations_frame_from_records_auto_stamps_retrieved_at():
    frame = stations_frame_from_records([_record()])

    assert frame["retrieved_at"].iloc[0] is not None
    assert frame["retrieved_at"].iloc[0].tzinfo is None


def test_stations_frame_from_records_defaults_variables_and_raw():
    frame = stations_frame_from_records([_record()])

    assert frame["variables"].iloc[0] == []
    assert frame["raw"].iloc[0] == {}


def test_stations_frame_from_records_preserves_variables_and_raw():
    frame = stations_frame_from_records(
        [_record(variables=["00060"], raw={"site_no": "1", "station_nm": "Test Station"})]
    )

    assert frame["variables"].iloc[0] == ["00060"]
    assert frame["raw"].iloc[0] == {"site_no": "1", "station_nm": "Test Station"}


def test_stations_frame_from_records_rejects_unknown_compartment():
    with pytest.raises(ValueError, match="unknown compartment"):
        stations_frame_from_records([_record(compartment="bogus")])
