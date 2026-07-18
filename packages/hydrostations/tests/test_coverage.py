from shapely.geometry import box

import hydrostations.coverage as coverage_module
from hydrostations.adapters.base import BBox, StationAdapter


class _FakeAdapter(StationAdapter):
    def __init__(self, network, compartments, coverage):
        self.network = network
        self.license = "Test license"
        self.redistribution_ok = True
        self.compartments = compartments
        self.coverage = coverage

    def fetch_stations(self, *, bbox=None, compartment=None):
        raise NotImplementedError


def test_lookup_coverage_matches_intersecting_networks(monkeypatch):
    us_like = _FakeAdapter(
        "US_LIKE", ("Q", "GW"), (BBox(min_lon=-125, min_lat=24, max_lon=-66, max_lat=50),)
    )
    au_like = _FakeAdapter(
        "AU_LIKE", ("Q",), (BBox(min_lon=112, min_lat=-44, max_lon=154, max_lat=-10),)
    )
    monkeypatch.setattr(
        coverage_module, "_default_registry", lambda: {"us": us_like, "au": au_like}
    )

    # a point clearly inside the US-like bbox only
    result = coverage_module.lookup_coverage(box(-100, 30, -99, 31))

    assert result == {"US_LIKE": ["Q", "GW"]}


def test_lookup_coverage_multiple_matches(monkeypatch):
    a = _FakeAdapter("A", ("Q",), (BBox(min_lon=0, min_lat=0, max_lon=10, max_lat=10),))
    b = _FakeAdapter("B", ("P",), (BBox(min_lon=5, min_lat=5, max_lon=15, max_lat=15),))
    monkeypatch.setattr(coverage_module, "_default_registry", lambda: {"a": a, "b": b})

    # overlaps both bboxes
    result = coverage_module.lookup_coverage(box(4, 4, 6, 6))

    assert result == {"A": ["Q"], "B": ["P"]}


def test_lookup_coverage_no_matches(monkeypatch):
    a = _FakeAdapter("A", ("Q",), (BBox(min_lon=0, min_lat=0, max_lon=10, max_lat=10),))
    monkeypatch.setattr(coverage_module, "_default_registry", lambda: {"a": a})

    result = coverage_module.lookup_coverage(box(50, 50, 51, 51))

    assert result == {}


def test_lookup_coverage_multi_bbox_adapter_matches_either(monkeypatch):
    a = _FakeAdapter(
        "A",
        ("Q",),
        (
            BBox(min_lon=0, min_lat=0, max_lon=1, max_lat=1),
            BBox(min_lon=100, min_lat=100, max_lon=101, max_lat=101),
        ),
    )
    monkeypatch.setattr(coverage_module, "_default_registry", lambda: {"a": a})

    assert coverage_module.lookup_coverage(box(100.2, 100.2, 100.4, 100.4)) == {"A": ["Q"]}
    assert coverage_module.lookup_coverage(box(50, 50, 51, 51)) == {}
