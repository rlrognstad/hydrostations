import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bespoke.nwis import NwisAdapter

_RDB_RESPONSE = (
    "# comment line, ignored\n"
    "agency_cd\tsite_no\tstation_nm\tdec_lat_va\tdec_long_va\tbegin_date\tend_date\n"
    "5s\t15s\t50s\t16s\t16s\t10d\t10d\n"
    "USGS\t01646500\tPOTOMAC RIVER NEAR WASH, DC\t38.9500\t-77.1200\t1930-01-01\t2020-01-01\n"
    "USGS\t01646500\tPOTOMAC RIVER NEAR WASH, DC\t38.9500\t-77.1200\t2020-01-02\t2023-06-01\n"
)


def test_fetch_stations_parses_and_aggregates_period_of_record(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get("https://waterservices.usgs.gov/nwis/site/").mock(
        return_value=httpx.Response(200, text=_RDB_RESPONSE)
    )

    frame = NwisAdapter(register_entries["nwis"]).fetch_stations(
        bbox=BBox(min_lon=-78, min_lat=38, max_lon=-77, max_lat=39),
        compartment="Q",
    )

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "01646500"
    assert row["name"] == "POTOMAC RIVER NEAR WASH, DC"
    assert row["compartment"] == "Q"
    assert row["source"] == "nwis"
    assert row["canonical_id"] == "nwis:01646500"
    assert bool(row["redistribution_ok"]) is True
    assert str(row["first_obs"].date()) == "1930-01-01"
    assert str(row["last_obs"].date()) == "2023-06-01"
    assert row["variables"] == ["00060"]
    assert row["raw"]["site_no"] == "01646500"
    assert frame.geometry.iloc[0].x == -77.12
    assert frame.geometry.iloc[0].y == 38.95


def test_fetch_stations_handles_empty_response(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://waterservices.usgs.gov/nwis/site/").mock(
        return_value=httpx.Response(200, text="# no sites found\n")
    )

    frame = NwisAdapter(register_entries["nwis"]).fetch_stations(compartment="GW")
    assert frame.empty


def test_fetch_stations_skips_out_of_coverage_bbox_without_http_call(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered for waterservices.usgs.gov -- if the adapter made
    # a request anyway, respx would raise for the unmatched call.
    frame = NwisAdapter(register_entries["nwis"]).fetch_stations(
        bbox=BBox(min_lon=8.0, min_lat=42.0, max_lon=30.0, max_lat=51.0),
        compartment="Q",
    )
    assert frame.empty
