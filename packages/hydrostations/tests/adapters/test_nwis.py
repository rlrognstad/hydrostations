import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.nwis import NwisAdapter

_RDB_RESPONSE = (
    "# comment line, ignored\n"
    "agency_cd\tsite_no\tstation_nm\tdec_lat_va\tdec_long_va\tbegin_date\tend_date\n"
    "5s\t15s\t50s\t16s\t16s\t10d\t10d\n"
    "USGS\t01646500\tPOTOMAC RIVER NEAR WASH, DC\t38.9500\t-77.1200\t1930-01-01\t2020-01-01\n"
    "USGS\t01646500\tPOTOMAC RIVER NEAR WASH, DC\t38.9500\t-77.1200\t2020-01-02\t2023-06-01\n"
)


def test_fetch_stations_parses_and_aggregates_period_of_record(mocked_api: respx.MockRouter):
    mocked_api.get("https://waterservices.usgs.gov/nwis/site/").mock(
        return_value=httpx.Response(200, text=_RDB_RESPONSE)
    )

    frame = NwisAdapter().fetch_stations(
        bbox=BBox(min_lon=-78, min_lat=38, max_lon=-77, max_lat=39),
        compartment="Q",
    )

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["station_id"] == "01646500"
    assert row["name"] == "POTOMAC RIVER NEAR WASH, DC"
    assert row["compartment"] == "Q"
    assert row["network"] == "NWIS"
    assert bool(row["redistribution_ok"]) is True
    assert str(row["start_date"].date()) == "1930-01-01"
    assert str(row["end_date"].date()) == "2023-06-01"
    assert frame.geometry.iloc[0].x == -77.12
    assert frame.geometry.iloc[0].y == 38.95


def test_fetch_stations_handles_empty_response(mocked_api: respx.MockRouter):
    mocked_api.get("https://waterservices.usgs.gov/nwis/site/").mock(
        return_value=httpx.Response(200, text="# no sites found\n")
    )

    frame = NwisAdapter().fetch_stations(compartment="GW")
    assert frame.empty


def test_fetch_stations_skips_out_of_coverage_bbox_without_http_call(
    mocked_api: respx.MockRouter,
):
    # No route registered for waterservices.usgs.gov -- if the adapter made
    # a request anyway, respx would raise for the unmatched call.
    frame = NwisAdapter().fetch_stations(
        bbox=BBox(min_lon=8.0, min_lat=42.0, max_lon=30.0, max_lat=51.0),
        compartment="Q",
    )
    assert frame.empty
