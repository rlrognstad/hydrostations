from shapely.geometry import box

from hydrocrosswalk.h3grid import cell_to_point, cell_to_polygon, cells_for_geometry


def test_cells_for_geometry_covers_box():
    geometry = box(2.0, 12.0, 4.0, 14.0)
    cells = cells_for_geometry(geometry, resolution=4)
    assert len(cells) > 0
    assert all(isinstance(c, str) for c in cells)


def test_cell_to_point_is_within_original_geometry():
    geometry = box(2.0, 12.0, 4.0, 14.0)
    cells = cells_for_geometry(geometry, resolution=4)
    cell = next(iter(cells))
    point = cell_to_point(cell)
    assert geometry.buffer(0.5).contains(point)


def test_cell_to_polygon_is_a_valid_hexagon_ish_shape():
    geometry = box(2.0, 12.0, 4.0, 14.0)
    cell = next(iter(cells_for_geometry(geometry, resolution=4)))
    polygon = cell_to_polygon(cell)
    assert polygon.is_valid
    assert len(polygon.exterior.coords) >= 6
