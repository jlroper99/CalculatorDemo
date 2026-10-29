from __future__ import annotations

import pytest

from bikeradar.privacy import endpoint_mask, haversine_m

# One degree of latitude is about 111.2 km.
LAT_M = 111_195.0


def north(meters: float) -> tuple[float, float]:
    return (40.0 + meters / LAT_M, -111.7)


def test_haversine_one_degree_latitude() -> None:
    assert haversine_m((40.0, -111.7), (41.0, -111.7)) == pytest.approx(LAT_M, rel=1e-3)


def test_points_within_radius_of_start_or_end_are_masked() -> None:
    points = [north(0), north(250), north(1000), north(5000), north(5299), north(5400)]
    assert endpoint_mask(points, 300) == [True, True, False, False, True, True]


def test_loop_ride_masks_both_ends_around_home() -> None:
    points = [north(0), north(2000), north(100)]
    assert endpoint_mask(points, 300) == [True, False, True]


def test_points_without_coordinates_are_skipped_as_anchors() -> None:
    points = [None, north(0), north(1000), north(2000), None]
    assert endpoint_mask(points, 300) == [False, True, False, True, False]


def test_no_located_points() -> None:
    assert endpoint_mask([None, None], 300) == [False, False]
    assert endpoint_mask([], 300) == []
