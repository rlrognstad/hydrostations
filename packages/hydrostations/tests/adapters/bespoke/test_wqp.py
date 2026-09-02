import httpx
import pytest
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bespoke.wqp import WqpAdapter

_URL = "https://www.waterqualitydata.us/data/Station/search"
_HEADER = (
    "MonitoringLocationIdentifier,MonitoringLocationName,LatitudeMeasure,"
    "LongitudeMeasure,VerticalMeasure/MeasureValue,VerticalMeasure/MeasureUnitCode"
)


def _csv(*rows: str) -> str:
    return "\n".join([_HEADER, *rows]) + "\n"


def _row(
    mlid="USGS-01646500",
    name="POTOMAC RIVER NEAR WASH DC",
    lat="38.9500",
    lon="-77.1200",
    elev="",
    unit="",
) -> str:
    return f"{mlid},{name},{lat},{lon},{elev},{unit}"


def test_fetch_stations_parses_csv_with_bbox(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_URL).mock(return_value=httpx.Response(200, text=_csv(_row())))

    frame = WqpAdapter(register_entries["wqp"]).fetch_stations(
        bbox=BBox(min_lon=-78, min_lat=38, max_lon=-77, max_lat=39),
        compartment="WQ",
    )

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source"] == "wqp"
    assert row["source_id"] == "USGS-01646500"
    assert row["canonical_id"] == "wqp:USGS-01646500"
    assert row["name"] == "POTOMAC RIVER NEAR WASH DC"
    assert row["compartment"] == "WQ"
    assert bool(row["redistribution_ok"]) is True
    assert str(row["first_obs"]) == "NaT"
    assert row["variables"] == []
    assert row["raw"]["MonitoringLocationIdentifier"] == "USGS-01646500"
    assert frame.geometry.iloc[0].x == -77.12
    assert frame.geometry.iloc[0].y == 38.95


def test_fetch_stations_converts_elevation_units(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_URL).mock(
        return_value=httpx.Response(
            200,
            text=_csv(
                _row(mlid="FEET", elev="340", unit="feet"),
                _row(mlid="FT", elev="1000", unit="ft"),
                _row(mlid="METRES", elev="103.6", unit="m"),
                _row(mlid="BLANK", elev="", unit=""),
            ),
        )
    )

    frame = WqpAdapter(register_entries["wqp"]).fetch_stations(
        bbox=BBox(min_lon=-78, min_lat=38, max_lon=-77, max_lat=39)
    )

    by_id = frame.set_index("source_id")["elevation_m"]
    assert by_id["FEET"] == pytest.approx(103.632)
    assert by_id["FT"] == pytest.approx(304.8)
    assert by_id["METRES"] == pytest.approx(103.6)
    assert by_id["BLANK"] is None or str(by_id["BLANK"]) == "<NA>"


def test_fetch_stations_missing_name_is_null(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_URL).mock(
        return_value=httpx.Response(200, text=_csv(_row(name="")))
    )

    frame = WqpAdapter(register_entries["wqp"]).fetch_stations(
        bbox=BBox(min_lon=-78, min_lat=38, max_lon=-77, max_lat=39)
    )

    assert frame.iloc[0]["name"] is None or str(frame.iloc[0]["name"]) == "<NA>"


def test_fetch_stations_empty_response_returns_empty_frame(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_URL).mock(return_value=httpx.Response(200, text=_csv()))

    frame = WqpAdapter(register_entries["wqp"]).fetch_stations(
        bbox=BBox(min_lon=-78, min_lat=38, max_lon=-77, max_lat=39)
    )
    assert frame.empty


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- respx would raise on any unmatched call.
    frame = WqpAdapter(register_entries["wqp"]).fetch_stations(compartment="Q")
    assert frame.empty


def test_fetch_stations_out_of_coverage_bbox_skipped_without_http_call(
    mocked_api: respx.MockRouter, register_entries
):
    # bbox over Europe -- skip_out_of_coverage is set on the wqp entry.
    frame = WqpAdapter(register_entries["wqp"]).fetch_stations(
        bbox=BBox(min_lon=2.0, min_lat=45.0, max_lon=8.0, max_lat=50.0),
        compartment="WQ",
    )
    assert frame.empty


def test_fetch_stations_without_bbox_queries_each_coverage_box(
    mocked_api: respx.MockRouter, register_entries
):
    route = mocked_api.get(_URL).mock(return_value=httpx.Response(200, text=_csv()))

    entry = register_entries["wqp"]
    WqpAdapter(entry).fetch_stations()

    assert route.call_count == len(entry.coverage)
