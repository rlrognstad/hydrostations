import pytest

import hydrostations.core as core_module
from hydrostations.adapters.base import BBox, SourceAdapter
from hydrostations.exceptions import AdapterNotImplementedError
from hydrostations.schema import stations_frame_from_records


class _FakeAdapter(SourceAdapter):
    def __init__(self, source, compartments, record=None, not_implemented=False):
        self.source = source
        self.license = "Test license"
        self.redistribution_ok = True
        self.compartments = compartments
        self._record = record
        self._not_implemented = not_implemented
        self.calls = []

    def fetch_stations(self, *, bbox: BBox | None = None, compartment: str | None = None):
        self.calls.append((bbox, compartment))
        if self._not_implemented:
            raise AdapterNotImplementedError(f"{self.source} not implemented")
        if self._record is None:
            return stations_frame_from_records([])
        return stations_frame_from_records([{**self._record, "compartment": compartment}])


def _base_record(source):
    return {
        "source": source,
        "source_id": "1",
        "name": f"{source} station",
        "lon": 1.0,
        "lat": 2.0,
        "first_obs": None,
        "last_obs": None,
        "wsi": None,
        "license": "Test license",
        "redistribution_ok": True,
    }


def test_get_stations_concatenates_across_sources(monkeypatch):
    fake_a = _FakeAdapter("a", ("Q",), record=_base_record("a"))
    fake_b = _FakeAdapter("b", ("Q",), record=_base_record("b"))
    monkeypatch.setattr(
        core_module, "_default_registry", lambda: {"a": fake_a, "b": fake_b}
    )

    frame = core_module.get_stations(compartment="Q")

    assert len(frame) == 2
    assert set(frame["source"]) == {"a", "b"}


def test_get_stations_skips_unsupported_compartment(monkeypatch):
    fake_a = _FakeAdapter("a", ("GW",), record=_base_record("a"))
    monkeypatch.setattr(core_module, "_default_registry", lambda: {"a": fake_a})

    frame = core_module.get_stations(compartment="Q")

    assert frame.empty
    assert fake_a.calls == []


def test_get_stations_warns_and_skips_unimplemented_when_broad(monkeypatch):
    fake = _FakeAdapter("a", ("Q",), not_implemented=True)
    monkeypatch.setattr(core_module, "_default_registry", lambda: {"a": fake})

    with pytest.warns(UserWarning):
        frame = core_module.get_stations(compartment="Q")

    assert frame.empty


def test_get_stations_raises_when_explicit_source_unimplemented(monkeypatch):
    fake = _FakeAdapter("a", ("Q",), not_implemented=True)
    monkeypatch.setattr(core_module, "_default_registry", lambda: {"a": fake})

    with pytest.raises(AdapterNotImplementedError):
        core_module.get_stations(compartment="Q", source="a")


def test_get_stations_unknown_source_raises(monkeypatch):
    fake = _FakeAdapter("a", ("Q",), record=_base_record("a"))
    monkeypatch.setattr(core_module, "_default_registry", lambda: {"a": fake})

    with pytest.raises(ValueError, match="unknown source"):
        core_module.get_stations(source="nope")


def test_get_stations_invalid_compartment_raises():
    with pytest.raises(ValueError, match="compartment must be one of"):
        core_module.get_stations(compartment="bogus")


def test_get_stations_resolves_basin_to_bbox(monkeypatch):
    fake = _FakeAdapter("a", ("Q",), record=_base_record("a"))
    monkeypatch.setattr(core_module, "_default_registry", lambda: {"a": fake})

    core_module.get_stations(basin="niger", compartment="Q", source="a")

    assert len(fake.calls) == 1
    bbox, compartment = fake.calls[0]
    assert isinstance(bbox, BBox)
    assert compartment == "Q"
