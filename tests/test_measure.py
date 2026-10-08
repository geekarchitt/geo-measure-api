"""Unit tests for the measurement + CRS logic (no HTTP)."""
import pytest
from pyproj import CRS, Geod
from shapely.geometry import GeometryCollection, LinearRing, LineString, MultiPoint, MultiPolygon, Point, Polygon

from app.services.measure import measure

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps="WGS84")


def geodesic_area(poly):
    return abs(GEOD.geometry_area_perimeter(poly)[0])


def test_polygon_area_matches_geodesic():
    poly = Polygon([(77.40, 23.25), (77.41, 23.25), (77.41, 23.26), (77.40, 23.26)])
    r = measure(poly, WGS84)
    assert r.status == "OK" and r.type == "area" and r.unit == "m2"
    assert r.projected_crs == "EPSG:32643"
    assert r.value == pytest.approx(geodesic_area(poly), rel=1e-3)


def test_degrees_are_never_used():
    # A 0.01 x 0.01 degree square is ~1.2 km², not 0.0001.
    poly = Polygon([(77.40, 23.25), (77.41, 23.25), (77.41, 23.26), (77.40, 23.26)])
    assert measure(poly, WGS84).value > 1e6


def test_polygon_with_hole():
    outer = [(77.40, 23.25), (77.42, 23.25), (77.42, 23.27), (77.40, 23.27)]
    hole = [(77.405, 23.255), (77.415, 23.255), (77.415, 23.265), (77.405, 23.265)]
    full = measure(Polygon(outer), WGS84).value
    holed = measure(Polygon(outer, [hole]), WGS84).value
    assert holed < full


def test_multipolygon_is_summed():
    a = Polygon([(77.40, 23.25), (77.41, 23.25), (77.41, 23.26), (77.40, 23.26)])
    b = Polygon([(77.50, 23.25), (77.51, 23.25), (77.51, 23.26), (77.50, 23.26)])
    total = measure(MultiPolygon([a, b]), WGS84).value
    assert total == pytest.approx(measure(a, WGS84).value + measure(b, WGS84).value, rel=1e-9)


def test_invalid_polygon_is_repaired_and_flagged():
    bowtie = Polygon([(77.40, 23.25), (77.41, 23.26), (77.41, 23.25), (77.40, 23.26)])
    assert not bowtie.is_valid
    r = measure(bowtie, WGS84)
    assert r.status == "OK" and r.value > 0 and "repaired" in r.message


def test_line_length_matches_geodesic():
    line = LineString([(77.40, 23.25), (77.45, 23.30), (77.50, 23.30)])
    r = measure(line, WGS84)
    assert r.type == "length" and r.unit == "m"
    assert r.value == pytest.approx(GEOD.geometry_length(line), rel=1e-3)


def test_southern_hemisphere_and_antimeridian():
    sydney = Polygon([(151.20, -33.90), (151.21, -33.90), (151.21, -33.89), (151.20, -33.89)])
    assert measure(sydney, WGS84).projected_crs == "EPSG:32756"
    fiji = LineString([(179.99, -17.0), (179.995, -17.0)])
    assert measure(fiji, WGS84).projected_crs == "EPSG:32760"  # lat -17 -> southern zone 60


def test_web_mercator_input_is_not_trusted_for_area():
    """EPSG:3857 is in metres but inflates area ~1/cos²(lat). We must still project to UTM."""
    from pyproj import Transformer
    lonlat = Polygon([(10.0, 60.0), (10.01, 60.0), (10.01, 60.01), (10.0, 60.01)])
    t = Transformer.from_crs(4326, 3857, always_xy=True)
    merc = Polygon([t.transform(x, y) for x, y in lonlat.exterior.coords])
    r = measure(merc, CRS.from_epsg(3857))
    assert r.value == pytest.approx(geodesic_area(lonlat), rel=2e-3)
    assert merc.area > 3 * r.value        # naive Mercator area would be ~4x too large


def test_points_and_unsupported_and_empty_do_not_crash():
    assert measure(Point(77, 23), WGS84).status == "NOT_APPLICABLE"
    assert measure(MultiPoint([(77, 23), (78, 23)]), WGS84).status == "NOT_APPLICABLE"
    gc = GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])])
    assert measure(gc, WGS84).status == "UNSUPPORTED"
    assert measure(None, WGS84).status == "SKIPPED"
    assert measure(Polygon(), WGS84).status == "SKIPPED"


def test_z_coordinates_ignored():
    p3d = Polygon([(77.40, 23.25, 500), (77.41, 23.25, 500), (77.41, 23.26, 500), (77.40, 23.26, 500)])
    p2d = Polygon([(77.40, 23.25), (77.41, 23.25), (77.41, 23.26), (77.40, 23.26)])
    assert measure(p3d, WGS84).value == pytest.approx(measure(p2d, WGS84).value)


def test_bad_coordinates_reported_as_error_not_exception():
    r = measure(LineString([(float("inf"), 0), (1, 1)]), WGS84)
    assert r.status == "ERROR"
