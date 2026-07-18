import pytest

from hydrostations.adapters.base import BBox
from hydrostations.basins import resolve_basin_bbox


def test_resolve_basin_bbox_known():
    bbox = resolve_basin_bbox("Niger")
    assert isinstance(bbox, BBox)
    assert bbox.min_lon < bbox.max_lon
    assert bbox.min_lat < bbox.max_lat


def test_resolve_basin_bbox_unknown():
    with pytest.raises(ValueError, match="unknown basin"):
        resolve_basin_bbox("not-a-real-basin")
