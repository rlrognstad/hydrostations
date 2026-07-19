import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bespoke.hubeau import HubeauAdapter


def _q_row(code_station: str, lon: float = 2.0, lat: float = 46.0) -> dict:
    return {
        "code_station": code_station,
        "libelle_station": f"La Seine a {code_station}",
        "longitude_station": lon,
        "latitude_station": lat,
        "date_ouverture_station": "2020-01-01T00:00:00Z",
        "date_fermeture_station": None,
    }


def _gw_row(code_bss: str, lon: float = 2.5, lat: float = 48.7) -> dict:
    return {
        "code_bss": code_bss,
        "nom_commune": "Servon",
        "x": lon,
        "y": lat,
        "date_debut_mesure": "1971-09-22",
        "date_fin_mesure": "1971-09-22",
    }


def test_fetch_stations_parses_q_single_page(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(
        "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations"
    ).mock(return_value=httpx.Response(200, json={"data": [_q_row("F243000101")], "next": None}))

    frame = HubeauAdapter(register_entries["hubeau"]).fetch_stations(compartment="Q")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "F243000101"
    assert row["name"] == "La Seine a F243000101"
    assert row["compartment"] == "Q"
    assert row["source"] == "hubeau"
    assert row["source_class"] == "agency"
    assert row["canonical_id"] == "hubeau:F243000101"
    assert row["raw"]["code_station"] == "F243000101"
    assert frame.geometry.iloc[0].x == 2.0
    assert frame.geometry.iloc[0].y == 46.0


def test_fetch_stations_parses_gw_single_page(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/stations").mock(
        return_value=httpx.Response(200, json={"data": [_gw_row("02201X0105")], "next": None})
    )

    frame = HubeauAdapter(register_entries["hubeau"]).fetch_stations(compartment="GW")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "02201X0105"
    assert row["name"] == "Servon"
    assert row["compartment"] == "GW"
    assert frame.geometry.iloc[0].x == 2.5
    assert frame.geometry.iloc[0].y == 48.7


def test_fetch_stations_follows_next_link(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get("https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "data": [_q_row("A001")],
                "next": "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?page=2",
            },
        ),
        httpx.Response(200, json={"data": [_q_row("A002")], "next": None}),
    ]

    frame = HubeauAdapter(register_entries["hubeau"]).fetch_stations(compartment="Q")

    assert len(frame) == 2
    assert route.call_count == 2
    assert set(frame["source_id"]) == {"A001", "A002"}


def test_fetch_stations_includes_bbox_param(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get(
        "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations"
    ).mock(return_value=httpx.Response(200, json={"data": [], "next": None}))

    HubeauAdapter(register_entries["hubeau"]).fetch_stations(
        bbox=BBox(min_lon=2.0, min_lat=48.0, max_lon=3.0, max_lat=49.0), compartment="Q"
    )

    params = dict(route.calls[0].request.url.params)
    assert params["bbox"] == "2.0,48.0,3.0,49.0"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = HubeauAdapter(register_entries["hubeau"]).fetch_stations(compartment="P")
    assert frame.empty
