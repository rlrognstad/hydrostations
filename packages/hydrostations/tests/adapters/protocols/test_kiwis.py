import httpx
import respx

from hydrostations.adapters.protocols.kiwis import KiWisAdapter

# Tested against the real BoM register entry -- our only current kiwis
# instance -- which also doubles as a regression check that the
# generalized adapter still serves BoM correctly.

_KIWIS_RESPONSE = [
    ["station_no", "station_name", "station_latitude", "station_longitude"],
    ["410730", "Cooper Creek at Currareva", "-25.9", "141.1"],
]


def test_fetch_stations_parses_kiwis_response(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://www.bom.gov.au/waterdata/services").mock(
        return_value=httpx.Response(200, json=_KIWIS_RESPONSE)
    )

    frame = KiWisAdapter(register_entries["bom"]).fetch_stations(compartment="Q")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "410730"
    assert row["name"] == "Cooper Creek at Currareva"
    assert row["source"] == "bom"
    assert row["source_class"] == "agency"
    assert row["canonical_id"] == "bom:410730"
    assert row["variables"] == ["Water Course Discharge"]
    assert row["raw"]["station_no"] == "410730"
    assert frame.geometry.iloc[0].x == 141.1
    assert frame.geometry.iloc[0].y == -25.9


def test_fetch_stations_indexes_by_configured_field_not_attribute_access(
    mocked_api: respx.MockRouter, register_entries
):
    # The real bug this generalization fixed: a naive itertuples()+attribute
    # pattern is fragile to a KiWIS deployment's exact header set. Building
    # dict(zip(header, row)) and indexing by the configured field name only
    # cares that the configured field is present, not that every column
    # header happens to be a valid Python identifier.
    response = [
        ["station_no", "station_name", "station_latitude", "station_longitude", "extra col!"],
        ["410731", "Another Station", "-26.0", "142.0", "unused"],
    ]
    mocked_api.get("https://www.bom.gov.au/waterdata/services").mock(
        return_value=httpx.Response(200, json=response)
    )

    frame = KiWisAdapter(register_entries["bom"]).fetch_stations(compartment="Q")

    assert frame.iloc[0]["name"] == "Another Station"
    assert frame.iloc[0]["raw"]["extra col!"] == "unused"


def test_fetch_stations_handles_empty_response(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://www.bom.gov.au/waterdata/services").mock(
        return_value=httpx.Response(200, json=[])
    )

    frame = KiWisAdapter(register_entries["bom"]).fetch_stations(compartment="GW")
    assert frame.empty
