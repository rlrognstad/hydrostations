import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.protocols.ogc_features import OgcFeaturesAdapter

# Tested against the real ECCC register entry -- our only current
# ogc_features instance -- which also doubles as a regression check that
# the generalized adapter still serves ECCC correctly.


def _feature(station_number: str, lon: float = -75.8, lat: float = 45.35) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "STATION_NUMBER": station_number,
            "STATION_NAME": f"RIVER AT {station_number}",
        },
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def test_fetch_stations_parses_single_page(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://api.weather.gc.ca/collections/hydrometric-stations/items").mock(
        return_value=httpx.Response(
            200, json={"features": [_feature("02KF005"), _feature("02KF015")]}
        )
    )

    frame = OgcFeaturesAdapter(register_entries["eccc"]).fetch_stations(compartment="Q")

    assert len(frame) == 2
    row = frame.iloc[0]
    assert row["source_id"] == "02KF005"
    assert row["name"] == "RIVER AT 02KF005"
    assert row["compartment"] == "Q"
    assert row["source"] == "eccc"
    assert row["canonical_id"] == "eccc:02KF005"
    assert row["raw"]["STATION_NUMBER"] == "02KF005"
    assert frame.geometry.iloc[0].x == -75.8
    assert frame.geometry.iloc[0].y == 45.35


def test_fetch_stations_paginates_until_short_page(mocked_api: respx.MockRouter, register_entries):
    entry = register_entries["eccc"]
    page_size = entry.ogc_features.page_size
    full_page = [_feature(f"S{i:05d}") for i in range(page_size)]
    short_page = [_feature("SLAST1"), _feature("SLAST2")]

    route = mocked_api.get("https://api.weather.gc.ca/collections/hydrometric-stations/items")
    route.side_effect = [
        httpx.Response(200, json={"features": full_page}),
        httpx.Response(200, json={"features": short_page}),
    ]

    frame = OgcFeaturesAdapter(entry).fetch_stations(compartment="Q")

    assert len(frame) == page_size + 2
    assert route.call_count == 2
    second_call_params = dict(route.calls[1].request.url.params)
    assert second_call_params["offset"] == str(page_size)


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = OgcFeaturesAdapter(register_entries["eccc"]).fetch_stations(compartment="GW")
    assert frame.empty


def test_fetch_stations_includes_bbox_param(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get("https://api.weather.gc.ca/collections/hydrometric-stations/items").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    OgcFeaturesAdapter(register_entries["eccc"]).fetch_stations(
        bbox=BBox(min_lon=-76.0, min_lat=45.0, max_lon=-75.0, max_lat=46.0), compartment="Q"
    )

    params = dict(route.calls[0].request.url.params)
    assert params["bbox"] == "-76.0,45.0,-75.0,46.0"
