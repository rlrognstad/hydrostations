import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.ameriflux import AmerifluxAdapter

_SITES_URL = "https://amfcdn.lbl.gov/api/v1/site_display/AmeriFlux"
_CCBY4_URL = "https://amfcdn.lbl.gov/api/v1/site_availability/AmeriFlux/BIF/CCBY4.0"


def _site(site_id="US-Ha1", name="Harvard Forest", lat="42.5378", lon="-72.1715", elev="340",
          tower_began="1991", tower_end=None):
    site = {
        "SITE_ID": site_id,
        "SITE_NAME": name,
        "COUNTRY": "USA",
        "GRP_LOCATION": {
            "LOCATION_LAT": lat,
            "LOCATION_LONG": lon,
            "LOCATION_ELEV": elev,
        },
        "TOWER_BEGAN": tower_began,
    }
    if tower_end is not None:
        site["TOWER_END"] = tower_end
    return site


def test_fetch_stations_sets_ccby4_license_per_record(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_SITES_URL).mock(
        return_value=httpx.Response(200, json=[_site(site_id="US-Ha1"), _site(site_id="US-Leg")])
    )
    mocked_api.get(_CCBY4_URL).mock(
        return_value=httpx.Response(200, json=[["US-Ha1", "Harvard Forest"]])
    )

    frame = AmerifluxAdapter(register_entries["ameriflux"]).fetch_stations()

    assert len(frame) == 2
    open_row = frame[frame["source_id"] == "US-Ha1"].iloc[0]
    legacy_row = frame[frame["source_id"] == "US-Leg"].iloc[0]
    assert open_row["license"] == "CC BY 4.0"
    assert bool(open_row["redistribution_ok"]) is True
    assert legacy_row["license"] == "AmeriFlux Legacy Data Policy (PI approval / citation required)"
    assert bool(legacy_row["redistribution_ok"]) is False
    assert (frame["compartment"] == "ET").all()


def test_fetch_stations_parses_dates_and_elevation(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_SITES_URL).mock(
        return_value=httpx.Response(
            200, json=[_site(tower_began="1991", tower_end="2020", elev="340")]
        )
    )
    mocked_api.get(_CCBY4_URL).mock(return_value=httpx.Response(200, json=[]))

    frame = AmerifluxAdapter(register_entries["ameriflux"]).fetch_stations()

    row = frame.iloc[0]
    assert str(row["first_obs"].date()) == "1991-01-01"
    assert str(row["last_obs"].date()) == "2020-12-31"
    assert row["elevation_m"] == 340.0


def test_fetch_stations_active_site_has_no_last_obs(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_SITES_URL).mock(return_value=httpx.Response(200, json=[_site(tower_end=None)]))
    mocked_api.get(_CCBY4_URL).mock(return_value=httpx.Response(200, json=[]))

    frame = AmerifluxAdapter(register_entries["ameriflux"]).fetch_stations()

    assert frame.iloc[0]["last_obs"] is None or str(frame.iloc[0]["last_obs"]) == "NaT"


def test_fetch_stations_filters_by_bbox_client_side(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_SITES_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                _site(site_id="IN", lat="40.0", lon="-105.0"),
                _site(site_id="OUT", lat="10.0", lon="10.0"),
            ],
        )
    )
    mocked_api.get(_CCBY4_URL).mock(return_value=httpx.Response(200, json=[]))

    frame = AmerifluxAdapter(register_entries["ameriflux"]).fetch_stations(
        bbox=BBox(min_lon=-108.0, min_lat=38.0, max_lon=-102.0, max_lat=41.0)
    )

    assert len(frame) == 1
    assert frame.iloc[0]["source_id"] == "IN"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = AmerifluxAdapter(register_entries["ameriflux"]).fetch_stations(compartment="Q")
    assert frame.empty
