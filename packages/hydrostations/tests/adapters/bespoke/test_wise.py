import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bespoke.wise import WiseAdapter


def _row(site_id: str, lon: float = 2.0, lat: float = 46.0) -> dict:
    return {
        "countryCode": "FR",
        "monitoringSiteIdentifier": site_id,
        "monitoringSiteName": f"Site {site_id}",
        "lon": lon,
        "lat": lat,
    }


def test_fetch_stations_parses_single_page(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://discodata.eea.europa.eu/sql").mock(
        return_value=httpx.Response(200, json={"results": [_row("FR001"), _row("FR002")]})
    )

    frame = WiseAdapter(register_entries["wise"]).fetch_stations(compartment="Q")

    assert len(frame) == 2
    row = frame.iloc[0]
    assert row["source_id"] == "FR001"
    assert row["name"] == "Site FR001"
    assert row["compartment"] == "Q"
    assert row["source"] == "wise"
    assert row["canonical_id"] == "wise:FR001"
    assert row["raw"]["monitoringSiteIdentifier"] == "FR001"
    assert frame.geometry.iloc[0].x == 2.0
    assert frame.geometry.iloc[0].y == 46.0


def test_fetch_stations_paginates_until_short_page(mocked_api: respx.MockRouter, register_entries):
    entry = register_entries["wise"]
    page_size = entry.wise.page_size
    full_page = [_row(f"FR{i:04d}") for i in range(page_size)]
    short_page = [_row("FRlast1"), _row("FRlast2")]

    route = mocked_api.get("https://discodata.eea.europa.eu/sql")
    route.side_effect = [
        httpx.Response(200, json={"results": full_page}),
        httpx.Response(200, json={"results": short_page}),
    ]

    frame = WiseAdapter(entry).fetch_stations(compartment="Q")

    assert len(frame) == page_size + 2
    assert route.call_count == 2
    second_call_params = dict(route.calls[1].request.url.params)
    assert second_call_params["p"] == "2"


def test_fetch_stations_bbox_and_zone_type_in_query(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get("https://discodata.eea.europa.eu/sql").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    WiseAdapter(register_entries["wise"]).fetch_stations(
        bbox=BBox(min_lon=2.0, min_lat=46.0, max_lon=3.0, max_lat=47.0), compartment="GW"
    )

    query = dict(route.calls[0].request.url.params)["query"]
    assert "groundWaterBody" in query
    assert "lon BETWEEN 2.0 AND 3.0" in query
    assert "lat BETWEEN 46.0 AND 47.0" in query


def test_fetch_stations_sw_compartment_maps_multiple_zone_types(
    mocked_api: respx.MockRouter, register_entries
):
    route = mocked_api.get("https://discodata.eea.europa.eu/sql").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    WiseAdapter(register_entries["wise"]).fetch_stations(compartment="SW")

    query = dict(route.calls[0].request.url.params)["query"]
    assert "lakeWaterBody" in query
    assert "coastalWaterBody" in query
    assert "transitionalWaterBody" in query


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = WiseAdapter(register_entries["wise"]).fetch_stations(compartment="P")
    assert frame.empty
