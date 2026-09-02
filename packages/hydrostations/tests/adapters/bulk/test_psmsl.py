import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.psmsl import PsmslAdapter

_ENDPOINT = "https://psmsl.org/data/obtaining/met.monthly.data/filelist.txt"

# Real filelist shape: id; lat; lon; name (space-padded); coastline; station; QC flag
_FILELIST = (
    "    1;  48.382850;   -4.494838; BREST                                   ; 190; 091; N\n"
    "    7;  40.466667;  -74.016667; SANDY HOOK                              ; 960; 001; N\n"
    "  999; -77.850100;  166.666700; SOME SOUTHERN GAUGE                     ; XXX; XXX; Y\n"
    "\n"  # blank line, ignored
)


def test_fetch_stations_parses_filelist(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get(_ENDPOINT).mock(return_value=httpx.Response(200, text=_FILELIST))

    frame = PsmslAdapter(register_entries["psmsl"]).fetch_stations(compartment="SW")

    assert len(frame) == 3
    row = frame[frame["source_id"] == "1"].iloc[0]
    assert row["source"] == "psmsl"
    assert row["canonical_id"] == "psmsl:1"
    assert row["name"] == "BREST"
    assert row["compartment"] == "SW"
    assert row["variables"] == []
    assert str(row["first_obs"]) == "NaT"
    assert bool(row["redistribution_ok"]) is True
    assert row["raw"]["qc_flag"] == "N"
    assert frame.geometry[frame["source_id"] == "1"].iloc[0].x == -4.494838
    assert frame.geometry[frame["source_id"] == "1"].iloc[0].y == 48.38285


def test_fetch_stations_filters_by_bbox_client_side(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_ENDPOINT).mock(return_value=httpx.Response(200, text=_FILELIST))

    frame = PsmslAdapter(register_entries["psmsl"]).fetch_stations(
        bbox=BBox(min_lon=-80.0, min_lat=35.0, max_lon=-70.0, max_lat=45.0)
    )

    assert list(frame["source_id"]) == ["7"]
    assert frame.iloc[0]["name"] == "SANDY HOOK"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- respx would raise on any unmatched call.
    frame = PsmslAdapter(register_entries["psmsl"]).fetch_stations(compartment="Q")
    assert frame.empty


def test_fetch_stations_empty_filelist_returns_empty_frame(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get(_ENDPOINT).mock(return_value=httpx.Response(200, text="\n\n"))

    frame = PsmslAdapter(register_entries["psmsl"]).fetch_stations()
    assert frame.empty
