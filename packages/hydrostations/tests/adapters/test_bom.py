import httpx
import respx

from hydrostations.adapters.bom import BomAdapter

_KIWIS_RESPONSE = [
    ["station_no", "station_name", "station_latitude", "station_longitude"],
    ["410730", "Cooper Creek at Currareva", "-25.9", "141.1"],
]


def test_fetch_stations_parses_kiwis_response(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://www.bom.gov.au/waterdata/services").mock(
        return_value=httpx.Response(200, json=_KIWIS_RESPONSE)
    )

    frame = BomAdapter(register_entries["bom"]).fetch_stations(compartment="Q")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "410730"
    assert row["name"] == "Cooper Creek at Currareva"
    assert row["source"] == "bom"
    assert row["canonical_id"] == "bom:410730"
    assert row["variables"] == ["Water Course Discharge"]
    assert row["raw"]["station_no"] == "410730"
    assert frame.geometry.iloc[0].x == 141.1
    assert frame.geometry.iloc[0].y == -25.9


def test_fetch_stations_handles_empty_response(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://www.bom.gov.au/waterdata/services").mock(
        return_value=httpx.Response(200, json=[])
    )

    frame = BomAdapter(register_entries["bom"]).fetch_stations(compartment="GW")
    assert frame.empty
