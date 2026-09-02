import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.sierem import SieremAdapter

_BASE = "http://www.hydrosciences.fr/sierem"
_INDEX = f"{_BASE}/SieremGoogleBassin.kml"
_HYDRO = f"{_BASE}/kmz_files/TESTHYDRO.kml"
_PLUVI = f"{_BASE}/kmz_files/TESTPLUVI.kml"
_PLGRA = f"{_BASE}/kmz_files/TESTPLGRA.kml"
_SYNOP = f"{_BASE}/kmz_files/TESTSYNOP.kml"
_OUTLINE = f"{_BASE}/kmz_files/Basins/TESTB.kml"

_INDEX_KML = f"""<?xml version='1.0' encoding='iso-8859-1'?>
<kml><Document>
<NetworkLink><name>Bassin hydrographique</name><Url><href>{_OUTLINE}</href></Url></NetworkLink>
<NetworkLink><name>Station hydrometrique</name><Url><href>{_HYDRO}</href></Url></NetworkLink>
<NetworkLink><name>Station pluviometrique</name><Url><href>{_PLUVI}</href></Url></NetworkLink>
<NetworkLink><name>Station pluviographique</name><Url><href>{_PLGRA}</href></Url></NetworkLink>
<NetworkLink><name>Station synoptique</name><Url><href>{_SYNOP}</href></Url></NetworkLink>
</Document></kml>"""


def _placemark(station_id, name, lon, lat, country="COTE D IVOIRE", altitude="null", dates=""):
    return f"""<Placemark><name> {name} </name>
<Point><coordinates>{lon},{lat},0</coordinates></Point>
<description><![CDATA[
<font size="6"><b>{station_id} - {name}</b></font><br/>
<b>{country}</b><br/>
<b>Altitude  :</b> {altitude} m<br/>
{dates}
]]></description>
</Placemark>"""


def _kml(*placemarks):
    return (
        "<?xml version='1.0' encoding='iso-8859-1'?>\n<kml><Document>\n"
        + "\n".join(placemarks)
        + "\n</Document></kml>"
    )


def test_fetch_stations_parses_index_and_station_files(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_INDEX).mock(return_value=httpx.Response(200, text=_INDEX_KML))
    hydro = mocked_api.get(_HYDRO).mock(
        return_value=httpx.Response(
            200,
            text=_kml(
                _placemark(
                    "1093501003", "ABIATE", -4.3257, 5.3873,
                    altitude="null",
                    dates="Debit journalier a ABIATE du 1-5-1962 au 31-1-1996 en m3/s",
                )
            ),
        )
    )
    pluvi = mocked_api.get(_PLUVI).mock(
        return_value=httpx.Response(
            200,
            text=_kml(_placemark("1090000800", "ABIDJAN COCODY", -4.0, 5.3167, altitude="20")),
        )
    )
    plgra = mocked_api.get(_PLGRA).mock(return_value=httpx.Response(200, text=_kml()))
    outline = mocked_api.get(_OUTLINE).mock(return_value=httpx.Response(200, text="<kml/>"))
    synop = mocked_api.get(_SYNOP).mock(return_value=httpx.Response(200, text=_kml()))

    frame = SieremAdapter(register_entries["sierem"]).fetch_stations()

    # basin outline and unmapped synoptic files are never requested
    assert outline.call_count == 0
    assert synop.call_count == 0
    assert hydro.called and pluvi.called and plgra.called

    assert sorted(frame["compartment"]) == ["P", "Q"]
    q = frame[frame["compartment"] == "Q"].iloc[0]
    assert q["source"] == "sierem"
    assert q["source_id"] == "1093501003"
    assert q["canonical_id"] == "sierem:1093501003"
    assert q["name"] == "ABIATE"
    assert q["elevation_m"] is None or str(q["elevation_m"]) == "<NA>"
    assert str(q["first_obs"].date()) == "1962-05-01"
    assert str(q["last_obs"].date()) == "1996-01-31"
    assert q["raw"]["country"] == "COTE D IVOIRE"
    assert frame.geometry[frame["compartment"] == "Q"].iloc[0].x == -4.3257

    p = frame[frame["compartment"] == "P"].iloc[0]
    assert p["source_id"] == "1090000800"
    assert p["elevation_m"] == 20.0
    assert str(p["first_obs"]) == "NaT"


def test_compartment_filter_only_fetches_matching_type_files(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_INDEX).mock(return_value=httpx.Response(200, text=_INDEX_KML))
    hydro = mocked_api.get(_HYDRO).mock(return_value=httpx.Response(200, text=_kml()))
    pluvi = mocked_api.get(_PLUVI).mock(
        return_value=httpx.Response(
            200, text=_kml(_placemark("100042", "SOMEWHERE", 10.0, 12.0))
        )
    )
    plgra = mocked_api.get(_PLGRA).mock(return_value=httpx.Response(200, text=_kml()))

    frame = SieremAdapter(register_entries["sierem"]).fetch_stations(compartment="P")

    assert hydro.call_count == 0
    assert pluvi.called and plgra.called
    assert list(frame["compartment"]) == ["P"]


def test_fetch_stations_dedups_station_ids_within_compartment(
    mocked_api: respx.MockRouter, register_entries
):
    index = _INDEX_KML.replace(
        f"<href>{_HYDRO}</href>",
        f"<href>{_HYDRO}</href></Url></NetworkLink>\n"
        f"<NetworkLink><name>Station hydrometrique</name><Url>"
        f"<href>{_BASE}/kmz_files/OTHERHYDRO.kml</href>",
    )
    mocked_api.get(_INDEX).mock(return_value=httpx.Response(200, text=index))
    body = _kml(_placemark("100777", "DUP", 1.0, 2.0))
    mocked_api.get(_HYDRO).mock(return_value=httpx.Response(200, text=body))
    mocked_api.get(f"{_BASE}/kmz_files/OTHERHYDRO.kml").mock(
        return_value=httpx.Response(200, text=body)
    )
    mocked_api.get(_PLUVI).mock(return_value=httpx.Response(200, text=_kml()))
    mocked_api.get(_PLGRA).mock(return_value=httpx.Response(200, text=_kml()))

    frame = SieremAdapter(register_entries["sierem"]).fetch_stations(compartment="Q")
    assert list(frame["source_id"]) == ["100777"]


def test_fetch_stations_skips_files_that_error(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_INDEX).mock(return_value=httpx.Response(200, text=_INDEX_KML))
    mocked_api.get(_HYDRO).mock(return_value=httpx.Response(500))
    mocked_api.get(_PLUVI).mock(
        return_value=httpx.Response(200, text=_kml(_placemark("100009", "OK", 3.0, 4.0)))
    )
    mocked_api.get(_PLGRA).mock(return_value=httpx.Response(200, text=_kml()))

    frame = SieremAdapter(register_entries["sierem"]).fetch_stations()
    assert list(frame["source_id"]) == ["100009"]


def test_fetch_stations_filters_by_bbox_client_side(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_INDEX).mock(return_value=httpx.Response(200, text=_INDEX_KML))
    mocked_api.get(_HYDRO).mock(
        return_value=httpx.Response(
            200,
            text=_kml(
                _placemark("100001", "IN", 10.0, 10.0),
                _placemark("100002", "OUT", -50.0, -50.0),
            ),
        )
    )
    mocked_api.get(_PLUVI).mock(return_value=httpx.Response(200, text=_kml()))
    mocked_api.get(_PLGRA).mock(return_value=httpx.Response(200, text=_kml()))

    frame = SieremAdapter(register_entries["sierem"]).fetch_stations(
        bbox=BBox(min_lon=0.0, min_lat=0.0, max_lon=20.0, max_lat=20.0)
    )
    assert list(frame["source_id"]) == ["100001"]


def test_fetch_stations_unsupported_compartment_skips_index(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- respx would raise on any unmatched call.
    frame = SieremAdapter(register_entries["sierem"]).fetch_stations(compartment="GW")
    assert frame.empty
