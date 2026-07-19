import httpx
import respx

from hydrostations.adapters.base import BBox
from hydrostations.adapters.bulk.ghcnd import GhcndAdapter


def _station_line(station_id: str, lat: float, lon: float, elev: float, name: str) -> str:
    # Fixed-width per ghcnd-stations.txt: ID(1-11) LAT(13-20) LON(22-30)
    # ELEV(32-37) STATE(39-40) NAME(42-71) -- verified column-by-column
    # against a real line from the live file before trusting this fixture.
    return f"{station_id:<11} {lat:>8.4f} {lon:>9.4f} {elev:>6.1f} {'':<2} {name:<30}"


def _inventory_line(station_id: str, element: str, first_year: int, last_year: int) -> str:
    # Fixed-width per ghcnd-inventory.txt: ID(1-11) LAT LON ELEMENT(32-35)
    # FIRSTYEAR(37-40) LASTYEAR(42-45).
    return f"{station_id:<11}  17.1167  -61.7833 {element:<4} {first_year:>4} {last_year:>4}"


def test_fetch_stations_joins_stations_and_inventory(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get("https://noaa-ghcn-pds.s3.amazonaws.com/ghcnd-stations.txt").mock(
        return_value=httpx.Response(
            200,
            text=(
                _station_line("ACW00011604", 17.1167, -61.7833, 10.1, "ST JOHNS")
                + "\n"
                + _station_line("XX000000001", 40.0, -105.0, 3535.1, "NO PRCP HERE")
            ),
        )
    )
    mocked_api.get("https://noaa-ghcn-pds.s3.amazonaws.com/ghcnd-inventory.txt").mock(
        return_value=httpx.Response(
            200,
            text=(
                _inventory_line("ACW00011604", "TMAX", 1949, 1949)
                + "\n"
                + _inventory_line("ACW00011604", "PRCP", 1949, 2020)
                + "\n"
                + _inventory_line("XX000000001", "TMAX", 1990, 2000)
            ),
        )
    )

    frame = GhcndAdapter(register_entries["ghcnd"]).fetch_stations(compartment="P")

    # Only the station with a PRCP inventory row is included.
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["source_id"] == "ACW00011604"
    assert row["name"] == "ST JOHNS"
    assert row["compartment"] == "P"
    assert row["source"] == "ghcnd"
    assert str(row["first_obs"].date()) == "1949-01-01"
    assert str(row["last_obs"].date()) == "2020-12-31"


def test_fetch_stations_treats_elevation_sentinel_as_null(
    mocked_api: respx.MockRouter, register_entries
):
    mocked_api.get("https://noaa-ghcn-pds.s3.amazonaws.com/ghcnd-stations.txt").mock(
        return_value=httpx.Response(
            200, text=_station_line("ACW00011604", 17.1167, -61.7833, -999.9, "NO ELEV")
        )
    )
    mocked_api.get("https://noaa-ghcn-pds.s3.amazonaws.com/ghcnd-inventory.txt").mock(
        return_value=httpx.Response(
            200, text=_inventory_line("ACW00011604", "PRCP", 2000, 2020)
        )
    )

    frame = GhcndAdapter(register_entries["ghcnd"]).fetch_stations(compartment="P")

    assert frame.iloc[0]["elevation_m"] is None or str(frame.iloc[0]["elevation_m"]) == "<NA>"


def test_fetch_stations_filters_by_bbox_client_side(mocked_api: respx.MockRouter, register_entries):
    mocked_api.get("https://noaa-ghcn-pds.s3.amazonaws.com/ghcnd-stations.txt").mock(
        return_value=httpx.Response(
            200,
            text=(
                _station_line("IN000000001", 40.0, -105.0, 1000.0, "INSIDE")
                + "\n"
                + _station_line("OUT00000001", 10.0, 10.0, 0.0, "OUTSIDE")
            ),
        )
    )
    mocked_api.get("https://noaa-ghcn-pds.s3.amazonaws.com/ghcnd-inventory.txt").mock(
        return_value=httpx.Response(
            200,
            text=(
                _inventory_line("IN000000001", "PRCP", 2000, 2020)
                + "\n"
                + _inventory_line("OUT00000001", "PRCP", 2000, 2020)
            ),
        )
    )

    frame = GhcndAdapter(register_entries["ghcnd"]).fetch_stations(
        bbox=BBox(min_lon=-108.0, min_lat=38.0, max_lon=-102.0, max_lat=41.0), compartment="P"
    )

    assert len(frame) == 1
    assert frame.iloc[0]["source_id"] == "IN000000001"


def test_fetch_stations_unsupported_compartment_skips_request(
    mocked_api: respx.MockRouter, register_entries
):
    # No route registered -- if the adapter made a request anyway, respx
    # would raise for the unmatched call.
    frame = GhcndAdapter(register_entries["ghcnd"]).fetch_stations(compartment="Q")
    assert frame.empty
