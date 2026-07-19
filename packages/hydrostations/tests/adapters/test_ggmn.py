import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.ggmn import GgmnAdapter


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


def test_fetch_stations_parses_single_page(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://ggis.un-igrac.org/geoserver/ows").mock(
        return_value=httpx.Response(200, json={"features": [_feature(1), _feature(2)]})
    )

    frame = GgmnAdapter(register_entries["ggmn"]).fetch_stations(compartment="GW")

    assert len(frame) == 2
    row = frame.iloc[0]
    assert row["source_id"] == "1"
    assert row["name"] == "Well 1"
    assert row["compartment"] == "GW"
    assert row["source"] == "ggmn"
    assert row["canonical_id"] == "ggmn:1"
    # tz-aware input must come out tz-naive, matching the shared schema
    assert row["first_obs"].tzinfo is None
    assert str(row["first_obs"].date()) == "2022-04-20"
    assert row["raw"]["id"] == 1
    assert frame.geometry.iloc[0].x == 6.0
    assert frame.geometry.iloc[0].y == 50.0


def test_fetch_stations_paginates_until_short_page(mocked_api: respx.MockRouter, register_entries):
    entry = register_entries["ggmn"]
    page_size = entry.wfs.page_size
    full_page = [_feature(i) for i in range(page_size)]
    short_page = [_feature(page_size), _feature(page_size + 1)]

    route = mocked_api.get("https://ggis.un-igrac.org/geoserver/ows")
    route.side_effect = [
        httpx.Response(200, json={"features": full_page}),
        httpx.Response(200, json={"features": short_page}),
    ]

    frame = GgmnAdapter(entry).fetch_stations(compartment="GW")

    assert len(frame) == page_size + 2
    assert route.call_count == 2
    second_call_params = dict(route.calls[1].request.url.params)
    assert second_call_params["startIndex"] == str(page_size)


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = GgmnAdapter(register_entries["ggmn"]).fetch_stations(compartment="Q")
    assert frame.empty


def test_fetch_stations_includes_bbox_param(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get("https://ggis.un-igrac.org/geoserver/ows").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    GgmnAdapter(register_entries["ggmn"]).fetch_stations(
        bbox=BBox(min_lon=4.0, min_lat=50.0, max_lon=7.0, max_lat=54.0), compartment="GW"
    )

    params = dict(route.calls[0].request.url.params)
    assert params["bbox"] == "4.0,50.0,7.0,54.0,EPSG:4326"
    assert params["sortBy"] == "id"
