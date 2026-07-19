import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.cocorahs import CocorahsAdapter


def _stations_xml(*stations: str) -> str:
    return f"<Cocorahs><Stations>{''.join(stations)}</Stations></Cocorahs>"


def _station(
    number: str,
    status: str = "Reporting",
    lon: float = -105.0,
    lat: float = 40.0,
    elevation_ft: float | None = 5000.0,
) -> str:
    elevation_xml = f"<Elevation>{elevation_ft}</Elevation>" if elevation_ft is not None else ""
    return (
        f"<Station><StationNumber>{number}</StationNumber>"
        f"<StationName>Station {number}</StationName>"
        f"<Latitude>{lat}</Latitude><Longitude>{lon}</Longitude>"
        f"{elevation_xml}"
        f"<StationStatus>{status}</StationStatus></Station>"
    )


def test_fetch_stations_parses_reporting_stations_only(
    mocked_api: respx.MockRouter, register_entries
):
    entry = register_entries["cocorahs"]
    # Only mock the states actually configured, keeping the fixture small --
    # patch the entry's state list down to one for this test.
    entry = entry.model_copy(
        update={"cocorahs": entry.cocorahs.model_copy(update={"states": ["CO"]})}
    )

    mocked_api.get("https://data.cocorahs.org/cocorahs/export/exportstations.aspx").mock(
        return_value=httpx.Response(
            200,
            text=_stations_xml(
                _station("CO-LR-1", status="Reporting"),
                _station("CO-LR-2", status="Closed"),
            ),
        )
    )

    frame = CocorahsAdapter(entry).fetch_stations(compartment="P")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "CO-LR-1"
    assert row["compartment"] == "P"
    assert row["source"] == "cocorahs"
    assert row["canonical_id"] == "cocorahs:CO-LR-1"
    assert row["elevation_m"] == 5000.0 * 0.3048


def test_fetch_stations_queries_every_configured_state(
    mocked_api: respx.MockRouter, register_entries
):
    entry = register_entries["cocorahs"]
    entry = entry.model_copy(
        update={"cocorahs": entry.cocorahs.model_copy(update={"states": ["CO", "WY"]})}
    )

    route = mocked_api.get("https://data.cocorahs.org/cocorahs/export/exportstations.aspx")
    route.side_effect = [
        httpx.Response(200, text=_stations_xml(_station("CO-1", lon=-105.0, lat=40.0))),
        httpx.Response(200, text=_stations_xml(_station("WY-1", lon=-107.0, lat=43.0))),
    ]

    frame = CocorahsAdapter(entry).fetch_stations(compartment="P")

    assert route.call_count == 2
    assert set(frame["source_id"]) == {"CO-1", "WY-1"}
    assert dict(route.calls[0].request.url.params)["state"] == "CO"
    assert dict(route.calls[1].request.url.params)["state"] == "WY"


def test_fetch_stations_filters_by_bbox_client_side(mocked_api: respx.MockRouter, register_entries):
    entry = register_entries["cocorahs"]
    entry = entry.model_copy(
        update={"cocorahs": entry.cocorahs.model_copy(update={"states": ["CO"]})}
    )

    mocked_api.get("https://data.cocorahs.org/cocorahs/export/exportstations.aspx").mock(
        return_value=httpx.Response(
            200,
            text=_stations_xml(
                _station("CO-1", lon=-105.0, lat=40.0),  # inside
                _station("CO-2", lon=-70.0, lat=45.0),  # outside
            ),
        )
    )

    frame = CocorahsAdapter(entry).fetch_stations(
        bbox=BBox(min_lon=-108.0, min_lat=38.0, max_lon=-104.0, max_lat=41.0), compartment="P"
    )

    assert len(frame) == 1
    assert frame.iloc[0]["source_id"] == "CO-1"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = CocorahsAdapter(register_entries["cocorahs"]).fetch_stations(compartment="Q")
    assert frame.empty
