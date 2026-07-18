import httpx
import respx

from hydrocrosswalk.sources.geoboundaries import fetch_admin_boundaries

_META_RESPONSE = {
    "boundaryISO": "NER",
    "boundaryLicense": "Creative Commons Attribution-ShareAlike 2.0",
    "licenseSource": "mapcruzin.com/free-niger-country-city-place-gis-shapefiles.htm",
    "gjDownloadURL": "https://example.com/niger.geojson",
}

_GEOJSON_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"shapeName": "Niger", "shapeISO": "NER", "shapeGroup": "NER"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
            },
        }
    ],
}


def test_fetch_admin_boundaries_captures_per_record_license(mocked_api: respx.MockRouter):
    mocked_api.get("https://www.geoboundaries.org/api/current/gbOpen/NER/ADM0/").mock(
        return_value=httpx.Response(200, json=_META_RESPONSE)
    )
    mocked_api.get("https://example.com/niger.geojson").mock(
        return_value=httpx.Response(200, json=_GEOJSON_RESPONSE)
    )

    gdf = fetch_admin_boundaries(["NER"], adm_level="ADM0")

    assert len(gdf) == 1
    assert gdf.iloc[0]["shapeName"] == "Niger"
    assert gdf.iloc[0]["admin_license"] == "Creative Commons Attribution-ShareAlike 2.0"
