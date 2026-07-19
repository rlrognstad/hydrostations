import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.hidroweb import HidroWebAdapter


def _feature(
    codigo: int, nome: str = "Test Station", lon: float = -60.0, lat: float = -3.0
) -> dict:
    return {
        "type": "Feature",
        "properties": {"Codigo": codigo, "Nome": nome, "TipoEstacao": "Fluviométrica"},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def test_fetch_stations_parses_single_page(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(url__regex=r"snirh\.gov\.br.*query").mock(
        return_value=httpx.Response(200, json={"features": [_feature(1), _feature(2)]})
    )

    frame = HidroWebAdapter(register_entries["hidroweb"]).fetch_stations(compartment="Q")

    assert len(frame) == 2
    row = frame.iloc[0]
    assert row["source_id"] == "1"
    assert row["name"] == "Test Station"
    assert row["compartment"] == "Q"
    assert row["source"] == "hidroweb"
    assert row["canonical_id"] == "hidroweb:1"
    assert row["raw"]["Codigo"] == 1
    assert frame.geometry.iloc[0].x == -60.0
    assert frame.geometry.iloc[0].y == -3.0


def test_fetch_stations_paginates_until_short_page(mocked_api: respx.MockRouter, register_entries):
    entry = register_entries["hidroweb"]
    page_size = entry.arcgis.page_size
    full_page = [_feature(i) for i in range(page_size)]
    short_page = [_feature(page_size), _feature(page_size + 1)]

    route = mocked_api.get(url__regex=r"snirh\.gov\.br.*query")
    route.side_effect = [
        httpx.Response(200, json={"features": full_page}),
        httpx.Response(200, json={"features": short_page}),
    ]

    frame = HidroWebAdapter(entry).fetch_stations(compartment="Q")

    assert len(frame) == page_size + 2
    assert route.call_count == 2
    second_call_params = dict(route.calls[1].request.url.params)
    assert second_call_params["resultOffset"] == str(page_size)


def test_fetch_stations_where_clause_matches_compartment(
    mocked_api: respx.MockRouter, register_entries
):
    route = mocked_api.get(url__regex=r"snirh\.gov\.br.*query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    HidroWebAdapter(register_entries["hidroweb"]).fetch_stations(compartment="P")

    where = dict(route.calls[0].request.url.params)["where"]
    assert "Pluviométrica" in where


def test_fetch_stations_includes_bbox_geometry(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get(url__regex=r"snirh\.gov\.br.*query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    HidroWebAdapter(register_entries["hidroweb"]).fetch_stations(
        bbox=BBox(min_lon=-61.0, min_lat=-4.0, max_lon=-59.0, max_lat=-2.0), compartment="Q"
    )

    params = dict(route.calls[0].request.url.params)
    assert params["geometry"] == "-61.0,-4.0,-59.0,-2.0"
    assert params["geometryType"] == "esriGeometryEnvelope"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = HidroWebAdapter(register_entries["hidroweb"]).fetch_stations(compartment="GW")
    assert frame.empty
