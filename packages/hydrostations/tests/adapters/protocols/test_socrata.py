import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.protocols.socrata import SocrataAdapter

# Tested against the real IDEAM register entry -- our only current socrata
# instance -- which doubles as a regression check that the shipped YAML
# stays valid.

_URL = "https://www.datos.gov.co/resource/hp9r-jxuu.json"


def _row(codigo="0021137020", nombre="PURIFICACION 1", lat="3.86", lon="-74.95",
         categoria="Limnimétrica", altitud="299", instal="15/08/1968", susp=None):
    row = {
        "codigo": codigo,
        "nombre": nombre,
        "latitud": lat,
        "longitud": lon,
        "categoria": categoria,
        "altitud": altitud,
        "fecha_instalacion": instal,
    }
    if susp is not None:
        row["fecha_suspension"] = susp
    return row


def test_fetch_stations_parses_rows_and_maps_category(
    mocked_api: respx.MockRouter, register_entries
):
    route = mocked_api.get(_URL).mock(
        return_value=httpx.Response(200, json=[_row(susp="15/09/1981")])
    )

    frame = SocrataAdapter(register_entries["ideam"]).fetch_stations(compartment="Q")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source"] == "ideam"
    assert row["source_id"] == "0021137020"
    assert row["canonical_id"] == "ideam:0021137020"
    assert row["name"] == "PURIFICACION 1"
    assert row["compartment"] == "Q"
    assert row["variables"] == ["Limnimétrica"]
    assert row["elevation_m"] == 299.0
    assert str(row["first_obs"].date()) == "1968-08-15"
    assert str(row["last_obs"].date()) == "1981-09-15"
    assert frame.geometry.iloc[0].x == -74.95
    assert frame.geometry.iloc[0].y == 3.86

    params = route.calls.last.request.url.params
    assert "categoria in ('Limnimétrica', 'Limnigráfica')" in params["$where"]
    assert params["$order"] == "codigo"


def test_fetch_stations_adds_bbox_clause(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get(_URL).mock(return_value=httpx.Response(200, json=[]))

    SocrataAdapter(register_entries["ideam"]).fetch_stations(
        bbox=BBox(min_lon=-75.0, min_lat=3.0, max_lon=-74.0, max_lat=4.0),
        compartment="P",
    )

    where = route.calls.last.request.url.params["$where"]
    assert "latitud between 3.0 and 4.0" in where
    assert "longitud between -75.0 and -74.0" in where
    assert "categoria in ('Pluviométrica', 'Pluviográfica')" in where


def test_fetch_stations_paginates_until_short_page(
    mocked_api: respx.MockRouter, register_entries
):
    entry = register_entries["ideam"]
    page_size = entry.socrata.page_size
    full = [_row(codigo=f"{i:010d}") for i in range(page_size)]
    short = [_row(codigo="Z1"), _row(codigo="Z2")]
    route = mocked_api.get(_URL).mock(
        side_effect=[httpx.Response(200, json=full), httpx.Response(200, json=short)]
    )

    frame = SocrataAdapter(entry).fetch_stations(compartment="P")

    assert route.call_count == 2
    assert len(frame) == page_size + 2
    assert route.calls[0].request.url.params["$offset"] == "0"
    assert route.calls[1].request.url.params["$offset"] == str(page_size)


def test_fetch_stations_skips_rows_with_unparseable_coordinates(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                _row(codigo="OK", lat="3.5", lon="-74.5"),
                _row(codigo="BADLAT", lat=None, lon="-74.5"),
                _row(codigo="BADLON", lat="3.5", lon=""),
            ],
        )
    )

    frame = SocrataAdapter(register_entries["ideam"]).fetch_stations(compartment="Q")

    assert list(frame["source_id"]) == ["OK"]


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- respx raises on any unmatched call.
    frame = SocrataAdapter(register_entries["ideam"]).fetch_stations(compartment="GW")
    assert frame.empty
