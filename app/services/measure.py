"""Measurement calculation for individual geometries."""
from __future__ import annotations

import math
from dataclasses import dataclass

import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from .crs import project_geometry, select_projected_crs

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}
POINT_TYPES = {"Point", "MultiPoint"}


@dataclass
class MeasureResult:
    status: str                       # OK | NOT_APPLICABLE | UNSUPPORTED | SKIPPED | ERROR
    type: str | None = None           # "area" | "length"
    value: float | None = None        # m² for area, m for length
    unit: str | None = None           # "m2" | "m"
    projected_crs: str | None = None
    message: str | None = None


def _polygonal_parts(geom: BaseGeometry) -> BaseGeometry:
    """After make_valid() the result may be a GeometryCollection; keep polygons only."""
    if geom.geom_type in AREA_TYPES:
        return geom
    polys = [g for g in shapely.get_parts(geom) if g.geom_type in AREA_TYPES]
    return shapely.union_all(polys) if polys else shapely.Polygon()


def measure(geom: BaseGeometry | None, source: CRS) -> MeasureResult:
    """Never raises: any problem is reported through ``MeasureResult.status``."""
    try:
        if geom is None or geom.is_empty:
            return MeasureResult("SKIPPED", message="Feature has no geometry")

        gtype = geom.geom_type
        if gtype in POINT_TYPES:
            return MeasureResult("NOT_APPLICABLE", message="No measurement defined for points")
        if gtype not in AREA_TYPES | LENGTH_TYPES:
            return MeasureResult(
                "UNSUPPORTED", message=f"Measurement not supported for geometry type '{gtype}'"
            )

        geom = shapely.force_2d(geom)
        note = None
        if gtype in AREA_TYPES and not geom.is_valid:
            geom = _polygonal_parts(shapely.make_valid(geom))
            note = "Invalid polygon geometry was repaired before measuring"

        epsg = select_projected_crs(geom, source)
        projected = project_geometry(geom, source, epsg)

        if gtype in AREA_TYPES:
            kind, value, unit = "area", float(projected.area), "m2"
        else:
            kind, value, unit = "length", float(projected.length), "m"

        if not math.isfinite(value):
            return MeasureResult("ERROR", message="Measurement produced a non-finite value")
        return MeasureResult("OK", kind, round(value, 4), unit, f"EPSG:{epsg}", note)
    except Exception as exc:  # noqa: BLE001 - one bad feature must not fail the whole file
        return MeasureResult("ERROR", message=f"Measurement failed: {exc}")
