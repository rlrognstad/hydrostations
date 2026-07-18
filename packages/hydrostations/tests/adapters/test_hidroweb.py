import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.hidroweb import _PAGE_SIZE, HidroWebAdapter


def _feature(
    codigo: int, nome: str = "Test Station", lon: float = -60.0, lat: float = -3.0
) -> dict:
    return {
        "type": "Feature",
        "properties": {"Codigo": codigo, "Nome": nome, "TipoEstacao": "Fluviométrica"},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def test_fetch_stations_parses_single_page(mocked_api: respx.MockRouter):
    mocked_api.get(url__regex=r"snirh\.gov\.br.*query").mock(
        return_value=httpx.Response(200, json={"features": [_feature(1), _feature(2)]})
    )

    frame = HidroWebAdapter().fetch_stations(compartment="Q")

    assert len(frame) == 2
    row = frame.iloc[0]
    assert row["station_id"] == "1"
    assert row["name"] == "Test Station"
    assert row["compartment"] == "Q"
    assert row["network"] == "HIDROWEB"
    assert frame.geometry.iloc[0].x == -60.0
    assert frame.geometry.iloc[0].y == -3.0


def test_fetch_stations_paginates_until_short_page(mocked_api: respx.MockRouter):
    full_page = [_feature(i) for i in range(_PAGE_SIZE)]
    short_page = [_feature(_PAGE_SIZE), _feature(_PAGE_SIZE + 1)]

    route = mocked_api.get(url__regex=r"snirh\.gov\.br.*query")
    route.side_effect = [
        httpx.Response(200, json={"features": full_page}),
        httpx.Response(200, json={"features": short_page}),
    ]

    frame = HidroWebAdapter().fetch_stations(compartment="Q")

    assert len(frame) == _PAGE_SIZE + 2
    assert route.call_count == 2
    second_call_params = dict(route.calls[1].request.url.params)
    assert second_call_params["resultOffset"] == str(_PAGE_SIZE)


def test_fetch_stations_where_clause_matches_compartment(mocked_api: respx.MockRouter):
    route = mocked_api.get(url__regex=r"snirh\.gov\.br.*query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    HidroWebAdapter().fetch_stations(compartment="P")

    where = dict(route.calls[0].request.url.params)["where"]
    assert "Pluviométrica" in where


def test_fetch_stations_includes_bbox_geometry(mocked_api: respx.MockRouter):
    route = mocked_api.get(url__regex=r"snirh\.gov\.br.*query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    HidroWebAdapter().fetch_stations(
        bbox=BBox(min_lon=-61.0, min_lat=-4.0, max_lon=-59.0, max_lat=-2.0), compartment="Q"
    )

    params = dict(route.calls[0].request.url.params)
    assert params["geometry"] == "-61.0,-4.0,-59.0,-2.0"
    assert params["geometryType"] == "esriGeometryEnvelope"


def test_fetch_stations_unsupported_compartment_skips_request(mocked_api: respx.MockRouter):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = HidroWebAdapter().fetch_stations(compartment="GW")
    assert frame.empty
