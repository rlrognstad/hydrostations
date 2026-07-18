import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.ggmn import _PAGE_SIZE, GgmnAdapter


def _feature(fid: int, lon: float = 6.0, lat: float = 50.0) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": fid,
            "name": f"Well {fid}",
            "first_recorded_measurement": "2022-04-20T10:29:28Z",
            "last_recorded_measurement": "2025-11-23T23:00:00Z",
        },
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def test_fetch_stations_parses_single_page(mocked_api: respx.MockRouter):
    mocked_api.get("https://ggis.un-igrac.org/geoserver/ows").mock(
        return_value=httpx.Response(
            200, json={"features": [_feature(1), _feature(2)]}
        )
    )

    frame = GgmnAdapter().fetch_stations(compartment="GW")

    assert len(frame) == 2
    row = frame.iloc[0]
    assert row["station_id"] == "1"
    assert row["name"] == "Well 1"
    assert row["compartment"] == "GW"
    assert row["network"] == "GGMN"
    # tz-aware input must come out tz-naive, matching the shared schema
    assert row["start_date"].tzinfo is None
    assert str(row["start_date"].date()) == "2022-04-20"
    assert frame.geometry.iloc[0].x == 6.0
    assert frame.geometry.iloc[0].y == 50.0


def test_fetch_stations_paginates_until_short_page(mocked_api: respx.MockRouter):
    full_page = [_feature(i) for i in range(_PAGE_SIZE)]
    short_page = [_feature(_PAGE_SIZE), _feature(_PAGE_SIZE + 1)]

    route = mocked_api.get("https://ggis.un-igrac.org/geoserver/ows")
    route.side_effect = [
        httpx.Response(200, json={"features": full_page}),
        httpx.Response(200, json={"features": short_page}),
    ]

    frame = GgmnAdapter().fetch_stations(compartment="GW")

    assert len(frame) == _PAGE_SIZE + 2
    assert route.call_count == 2
    second_call_params = dict(route.calls[1].request.url.params)
    assert second_call_params["startIndex"] == str(_PAGE_SIZE)


def test_fetch_stations_unsupported_compartment_skips_request(mocked_api: respx.MockRouter):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = GgmnAdapter().fetch_stations(compartment="Q")
    assert frame.empty


def test_fetch_stations_includes_bbox_param(mocked_api: respx.MockRouter):
    route = mocked_api.get("https://ggis.un-igrac.org/geoserver/ows").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    GgmnAdapter().fetch_stations(
        bbox=BBox(min_lon=4.0, min_lat=50.0, max_lon=7.0, max_lat=54.0), compartment="GW"
    )

    params = dict(route.calls[0].request.url.params)
    assert params["bbox"] == "4.0,50.0,7.0,54.0,EPSG:4326"
