import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bespoke.globe import GlobeAdapter

_GLOBAL = "https://api.globe.gov/search/v1/measurement/protocol/measureddate/"
_BBOX = "https://api.globe.gov/search/v1/measurement/protocol/measureddate/lat/lon/"


def _m(site_id, protocol="water_temperatures", date="2020-06-07", lat=42.5, lon=-72.1,
       name="Harvard Pond", elevation=180, country="United States"):
    return {
        "protocol": protocol,
        "measuredDate": date,
        "siteId": site_id,
        "siteName": name,
        "latitude": lat,
        "longitude": lon,
        "elevation": elevation,
        "countryName": country,
        "organizationName": f"School {site_id}",
    }


def _resp(results, count=None):
    return httpx.Response(200, json={"count": count if count is not None else len(results),
                                     "results": results})


def test_aggregates_measurements_into_one_record_per_site(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_GLOBAL).mock(
        return_value=_resp([
            _m(101, "water_temperatures", "2020-06-07"),
            _m(101, "hydrology_phs", "2019-03-01"),
            _m(101, "water_temperatures", "2021-08-15"),
            _m(202, "nitrates", "2022-01-01", lat=10.0, lon=20.0, name="Site 202"),
        ])
    )

    frame = GlobeAdapter(register_entries["globe"]).fetch_stations(compartment="WQ")

    assert sorted(frame["source_id"]) == ["101", "202"]
    row = frame[frame["source_id"] == "101"].iloc[0]
    assert row["source"] == "globe"
    assert row["source_class"] == "citizen"
    assert row["compartment"] == "WQ"
    assert row["name"] == "Harvard Pond"
    assert row["elevation_m"] == 180.0
    assert row["variables"] == ["hydrology_phs", "water_temperatures"]
    assert str(row["first_obs"].date()) == "2019-03-01"
    assert str(row["last_obs"].date()) == "2021-08-15"
    assert row["raw"]["country"] == "United States"
    assert frame.geometry[frame["source_id"] == "101"].iloc[0].x == -72.1


def test_bbox_query_hits_lat_lon_endpoint(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get(_BBOX).mock(return_value=_resp([_m(1)]))

    GlobeAdapter(register_entries["globe"]).fetch_stations(
        bbox=BBox(min_lon=-80.0, min_lat=40.0, max_lon=-70.0, max_lat=45.0),
        compartment="WQ",
    )

    params = route.calls.last.request.url.params
    assert params["minlat"] == "40.0"
    assert params["maxlon"] == "-70.0"


def test_splits_a_window_that_hits_the_result_cap(
    mocked_api: respx.MockRouter, register_entries
):
    # First call: count over the cap -> adapter must split and recurse,
    # discarding this page's own results. Next two calls: small windows.
    route = mocked_api.get(_GLOBAL).mock(
        side_effect=[
            _resp([_m(999)], count=9000),
            _resp([_m(1, "nitrates", "2019-05-05")]),
            _resp([_m(2, "nitrates", "2024-05-05", lat=1.0, lon=2.0)]),
        ]
    )

    frame = GlobeAdapter(register_entries["globe"]).fetch_stations(compartment="WQ")

    assert route.call_count == 3
    assert sorted(frame["source_id"]) == ["1", "2"]
    assert "999" not in set(frame["source_id"])


def test_pages_within_a_window(mocked_api: respx.MockRouter, register_entries):
    entry = register_entries["globe"]
    size = entry.globe.page_size
    full = [_m(i) for i in range(size)]
    tail = [_m(size + 1, lat=5.0, lon=5.0)]
    route = mocked_api.get(_GLOBAL).mock(
        side_effect=[_resp(full, count=size + 1), _resp(tail, count=size + 1)]
    )

    frame = GlobeAdapter(entry).fetch_stations(compartment="WQ")

    assert route.call_count == 2
    assert route.calls[1].request.url.params["from"] == str(size)
    assert len(frame) == size + 1


def test_skips_rows_missing_site_or_coordinates(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_GLOBAL).mock(
        return_value=_resp([
            _m(1),
            {"protocol": "nitrates", "measuredDate": "2020-01-01", "siteId": None,
             "latitude": 1.0, "longitude": 2.0},
            {"protocol": "nitrates", "measuredDate": "2020-01-01", "siteId": 5,
             "latitude": None, "longitude": 2.0},
        ])
    )

    frame = GlobeAdapter(register_entries["globe"]).fetch_stations(compartment="WQ")
    assert list(frame["source_id"]) == ["1"]


def test_unsupported_compartment_skips_request(mocked_api: respx.MockRouter, register_entries):
    # No route registered -- respx raises on any unmatched call.
    frame = GlobeAdapter(register_entries["globe"]).fetch_stations(compartment="Q")
    assert frame.empty
