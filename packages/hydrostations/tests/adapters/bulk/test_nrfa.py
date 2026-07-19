import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.nrfa import NrfaAdapter


def _row(station_id: int, lon: float = -1.0, lat: float = 52.0) -> dict:
    return {
        "id": station_id,
        "name": f"River at {station_id}",
        "latitude": lat,
        "longitude": lon,
        "catchment-area": 123.4,
        "gdf-start-date": "1980-01-01",
        "gdf-end-date": "2024-09-30",
    }


def test_fetch_stations_parses_all_stations(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://nrfaapps.ceh.ac.uk/nrfa/ws/station-info").mock(
        return_value=httpx.Response(200, json={"data": [_row(1001), _row(2001)]})
    )

    frame = NrfaAdapter(register_entries["nrfa"]).fetch_stations(compartment="Q")

    assert len(frame) == 2
    row = frame.iloc[0]
    assert row["source_id"] == "1001"
    assert row["name"] == "River at 1001"
    assert row["compartment"] == "Q"
    assert row["source"] == "nrfa"
    assert row["source_class"] == "agency"
    assert row["canonical_id"] == "nrfa:1001"
    assert row["catchment_area_km2"] == 123.4
    assert str(row["first_obs"].date()) == "1980-01-01"
    assert str(row["last_obs"].date()) == "2024-09-30"
    assert row["raw"]["id"] == 1001
    assert frame.geometry.iloc[0].x == -1.0
    assert frame.geometry.iloc[0].y == 52.0


def test_fetch_stations_no_spatial_filter_sent_to_server(
    mocked_api: respx.MockRouter, register_entries
):
    # NRFA has no server-side bbox param -- the same request must be made
    # (station=* every time) regardless of bbox; filtering happens locally.
    route = mocked_api.get("https://nrfaapps.ceh.ac.uk/nrfa/ws/station-info").mock(
        return_value=httpx.Response(200, json={"data": [_row(1001, lon=-1.0, lat=52.0)]})
    )

    NrfaAdapter(register_entries["nrfa"]).fetch_stations(
        bbox=BBox(min_lon=0.0, min_lat=0.0, max_lon=1.0, max_lat=1.0), compartment="Q"
    )

    assert route.call_count == 1
    params = dict(route.calls[0].request.url.params)
    assert params["station"] == "*"
    assert "bbox" not in params


def test_fetch_stations_filters_by_bbox_client_side(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://nrfaapps.ceh.ac.uk/nrfa/ws/station-info").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    _row(1001, lon=-1.0, lat=52.0),  # inside the bbox below
                    _row(2001, lon=10.0, lat=60.0),  # outside
                ]
            },
        )
    )

    frame = NrfaAdapter(register_entries["nrfa"]).fetch_stations(
        bbox=BBox(min_lon=-2.0, min_lat=51.0, max_lon=0.0, max_lat=53.0), compartment="Q"
    )

    assert len(frame) == 1
    assert frame.iloc[0]["source_id"] == "1001"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = NrfaAdapter(register_entries["nrfa"]).fetch_stations(compartment="GW")
    assert frame.empty
