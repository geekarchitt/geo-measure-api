"""CRS helpers.

Strategy: measurements are never taken in degrees. For every feature we pick a
*local* projected CRS (UTM zone of the feature's centre, or polar stereographic
near the poles) and transform the geometry into it before measuring.
"""
from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
import numpy as np
import shapely

WGS84 = CRS.from_epsg(4326)
UPS_NORTH = 32661  # WGS84 / UPS North (lat >= 84)
UPS_SOUTH = 32761  # WGS84 / UPS South (lat <= -80)


def parse_crs(value) -> CRS:
    return CRS.from_user_input(value)


def crs_label(crs: CRS) -> str:
    """'EPSG:4326' when an authority code can be found, otherwise the CRS name."""
    epsg = crs.to_epsg()
    if epsg:
        return f"EPSG:{epsg}"
    auth = crs.to_authority()
    if auth:
        return f"{auth[0]}:{auth[1]}"
    return crs.name or "UNKNOWN"


def utm_epsg_for(lon: float, lat: float) -> int:
    """EPSG code of the WGS84 UTM zone (or UPS cap) containing lon/lat."""
    if lat >= 84:
        return UPS_NORTH
    if lat <= -80:
        return UPS_SOUTH
    lon = ((lon + 180) % 360) - 180                 # normalise to [-180, 180)
    zone = min(int(math.floor((lon + 180) / 6)) + 1, 60)
    return (32600 if lat >= 0 else 32700) + zone


@lru_cache(maxsize=256)
def _transformer(src_wkt: str, dst_epsg: int) -> Transformer:
    return Transformer.from_crs(CRS.from_wkt(src_wkt), CRS.from_epsg(dst_epsg), always_xy=True)


@lru_cache(maxsize=16)
def _to_wgs84(src_wkt: str) -> Transformer:
    return Transformer.from_crs(CRS.from_wkt(src_wkt), WGS84, always_xy=True)


def select_projected_crs(geom: BaseGeometry, source: CRS) -> int:
    """Pick the local UTM/UPS EPSG code for ``geom`` (expressed in ``source``)."""
    x, y = geom.representative_point().coords[0][:2]
    if source.is_geographic and source.to_epsg() == 4326:
        lon, lat = x, y
    else:
        lon, lat = _to_wgs84(source.to_wkt()).transform(x, y)
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise ValueError("geometry location could not be resolved to lon/lat")
    return utm_epsg_for(lon, lat)


def project_geometry(geom: BaseGeometry, source: CRS, dst_epsg: int) -> BaseGeometry:
    t = _transformer(source.to_wkt(), dst_epsg)

    def _apply(coords: np.ndarray) -> np.ndarray:
        x, y = t.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, _apply)
