import pytest
from pydantic import ValidationError

from hydrostations.adapters.base import BBox
from hydrostations.register.models import ArcGisEntry, KiwisEntry, SourceEntryAdapter


def _base(**overrides):
    entry = {
        "source_id": "test",
        "name": "Test Source",
        "operator": "Test Operator",
        "endpoint": "https://example.com",
        "compartments": ["Q"],
        "license": "Public domain",
        "coverage": [[0.0, 0.0, 1.0, 1.0]],
        "protocol": "bulk_kml",
    }
    entry.update(overrides)
    return entry


def test_bulk_entry_validates_and_defaults_live_false():
    entry = SourceEntryAdapter.validate_python(_base())
    assert entry.protocol == "bulk_kml"
    assert entry.live is False
    assert entry.redistribution_ok is True  # base default


def test_kiwis_entry_requires_protocol_config():
    payload = _base(
        protocol="kiwis",
        kiwis={
            "id_field": "station_no",
            "name_field": "station_name",
            "lat_field": "lat",
            "lon_field": "lon",
            "return_fields": ["station_no"],
            "parameter_type_by_compartment": {"Q": "Water Course Discharge"},
        },
    )
    entry = SourceEntryAdapter.validate_python(payload)
    assert isinstance(entry, KiwisEntry)
    assert entry.kiwis.parameter_type_by_compartment["Q"] == "Water Course Discharge"


def test_kiwis_entry_missing_config_block_fails():
    with pytest.raises(ValidationError):
        SourceEntryAdapter.validate_python(_base(protocol="kiwis"))


def test_arcgis_entry_discriminates_correctly():
    payload = _base(
        protocol="arcgis_feature_server",
        arcgis={
            "id_field": "Codigo",
            "name_field": "Nome",
            "out_fields": ["Codigo", "Nome"],
            "where_by_compartment": {"Q": "TipoEstacao='Fluviométrica'"},
        },
    )
    entry = SourceEntryAdapter.validate_python(payload)
    assert isinstance(entry, ArcGisEntry)
    assert entry.arcgis.page_size == 1000  # default


def test_unknown_compartment_rejected():
    with pytest.raises(ValidationError, match="unknown compartment"):
        SourceEntryAdapter.validate_python(_base(compartments=["NOTREAL"]))


def test_unknown_protocol_rejected():
    with pytest.raises(ValidationError):
        SourceEntryAdapter.validate_python(_base(protocol="not_a_real_protocol"))


def test_coverage_bboxes_returns_bbox_tuple():
    entry = SourceEntryAdapter.validate_python(
        _base(coverage=[[0.0, 1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0]])
    )
    boxes = entry.coverage_bboxes()
    assert boxes == (
        BBox(min_lon=0.0, min_lat=1.0, max_lon=2.0, max_lat=3.0),
        BBox(min_lon=4.0, min_lat=5.0, max_lon=6.0, max_lat=7.0),
    )
