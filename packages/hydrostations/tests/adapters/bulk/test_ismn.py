import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.ismn import IsmnAdapter

_ENDPOINT = "https://ismn.earth/static/dataviewer/network_station_details.json"


def _station(
    station_id=1,
    name="Station1",
    lat=40.0,
    lng=-105.0,
    variable_text="soil moisture<br>",
    **overrides,
):
    station = {
        "stationID": station_id,
        "station_name": name,
        "lat": lat,
        "lng": lng,
        "variableText": variable_text,
        "minimum": "2010-02-08 01:00:00",
        "maximum": "2020-02-10 02:00:00",
    }
    station.update(overrides)
    return station


def _payload(networks: list[dict]) -> dict:
    return {"Networks": networks, "created_at": "2026-07-25T08:00:51"}


def test_fetch_stations_matches_variables_to_compartments(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json=_payload(
                [
                    {
                        "networkID": "NET1",
                        "Stations": [_station(variable_text="soil moisture<br>precipitation<br>")],
                    }
                ]
            ),
        )
    )

    frame = IsmnAdapter(register_entries["ismn"]).fetch_stations()

    # One record per matching compartment for the same station.
    assert sorted(frame["compartment"]) == ["P", "SM"]
    assert (frame["source_id"] == "1").all()
    assert (frame["source"] == "ismn").all()
    row = frame[frame["compartment"] == "SM"].iloc[0]
    assert row["variables"] == ["soil moisture"]
    assert str(row["first_obs"].date()) == "2010-02-08"
    assert str(row["last_obs"].date()) == "2020-02-10"


def test_fetch_stations_skips_unrelated_variables(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json=_payload(
                [
                    {
                        "networkID": "NET1",
                        "Stations": [
                            _station(variable_text="soil temperature<br>air temperature<br>")
                        ],
                    }
                ]
            ),
        )
    )

    frame = IsmnAdapter(register_entries["ismn"]).fetch_stations()

    assert frame.empty


def test_fetch_stations_filters_by_bbox_client_side(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json=_payload(
                [
                    {
                        "networkID": "NET1",
                        "Stations": [
                            _station(station_id=1, lat=40.0, lng=-105.0),
                            _station(station_id=2, lat=10.0, lng=10.0),
                        ],
                    }
                ]
            ),
        )
    )

    frame = IsmnAdapter(register_entries["ismn"]).fetch_stations(
        bbox=BBox(min_lon=-108.0, min_lat=38.0, max_lon=-102.0, max_lat=41.0), compartment="SM"
    )

    assert len(frame) == 1
    assert frame.iloc[0]["source_id"] == "1"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = IsmnAdapter(register_entries["ismn"]).fetch_stations(compartment="Q")
    assert frame.empty
