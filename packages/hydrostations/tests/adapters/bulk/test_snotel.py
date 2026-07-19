import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.snotel import SnotelAdapter


def _row(
    triplet: str,
    lon: float = -106.0,
    lat: float = 39.5,
    elevation_ft: float = 10000.0,
    end_date: str | None = "2100-01-01 00:00",
) -> dict:
    return {
        "stationTriplet": triplet,
        "stationId": triplet.split(":")[0],
        "stateCode": triplet.split(":")[1],
        "networkCode": triplet.split(":")[2],
        "name": f"Station {triplet}",
        "elevation": elevation_ft,
        "latitude": lat,
        "longitude": lon,
        "beginDate": "1980-10-01 00:00",
        "endDate": end_date,
    }


def test_fetch_stations_parses_snow_compartment(mocked_api: respx.MockRouter, register_entries):
    route = mocked_api.get("https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations").mock(
        return_value=httpx.Response(200, json=[_row("301:CO:SNTL")])
    )

    frame = SnotelAdapter(register_entries["snotel"]).fetch_stations(compartment="SNOW")

    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "301:CO:SNTL"
    assert row["compartment"] == "SNOW"
    assert row["source"] == "snotel"
    assert row["canonical_id"] == "snotel:301:CO:SNTL"
    # 10,000 ft -> ~3,048 m
    assert row["elevation_m"] == 3048.0
    # sentinel endDate -> no last_obs
    assert row["last_obs"] is None or str(row["last_obs"]) == "NaT"
    assert str(row["first_obs"].date()) == "1980-10-01"
    assert route.calls[0].request.url.params["stationTriplets"] == "*:*:SNTL"


def test_fetch_stations_parses_sm_compartment_with_real_end_date(
    mocked_api: respx.MockRouter, register_entries
):
    route = mocked_api.get("https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations").mock(
        return_value=httpx.Response(
            200, json=[_row("2057:AL:SCAN", end_date="2015-06-01 00:00")]
        )
    )

    frame = SnotelAdapter(register_entries["snotel"]).fetch_stations(compartment="SM")

    assert len(frame) == 1
    assert frame.iloc[0]["compartment"] == "SM"
    assert str(frame.iloc[0]["last_obs"].date()) == "2015-06-01"
    assert route.calls[0].request.url.params["stationTriplets"] == "*:*:SCAN"


def test_fetch_stations_filters_by_bbox_client_side(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations").mock(
        return_value=httpx.Response(
            200,
            json=[
                _row("301:CO:SNTL", lon=-106.0, lat=39.5),  # inside bbox
                _row("999:ME:SNTL", lon=-70.0, lat=45.0),  # outside
            ],
        )
    )

    frame = SnotelAdapter(register_entries["snotel"]).fetch_stations(
        bbox=BBox(min_lon=-108.0, min_lat=38.0, max_lon=-105.0, max_lat=41.0),
        compartment="SNOW",
    )

    assert len(frame) == 1
    assert frame.iloc[0]["source_id"] == "301:CO:SNTL"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = SnotelAdapter(register_entries["snotel"]).fetch_stations(compartment="Q")
    assert frame.empty
