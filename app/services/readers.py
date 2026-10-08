"""Readers that turn an uploaded Shapefile (.zip) or KML into ParsedFeature objects."""
from __future__ import annotations

import datetime as dt
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

import numpy as np
import pyogrio
import pyogrio.raw
import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from ..config import settings
from .crs import parse_crs
from .errors import ProcessingError, UnsupportedFileTypeError

SHAPEFILE_PARTS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj"}


@dataclass
class ParsedFeature:
    layer: str
    geometry: BaseGeometry | None
    properties: dict
    crs: CRS


def detect_file_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".zip":
        return "shapefile"
    if suffix == ".kml":
        return "kml"
    raise UnsupportedFileTypeError(
        f"Unsupported file type '{suffix or filename}'. Upload a .zip (Shapefile) or .kml file."
    )


# --------------------------------------------------------------------------- helpers
def _jsonable(value):
    """Convert numpy / datetime values to plain JSON-serialisable Python."""
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and value != value:   # NaN
        return None
    return value


def _scrub(exc: Exception, path: Path) -> str:
    """Error text from GDAL with server-side temp paths removed."""
    return str(exc).replace(str(path), path.name).replace(str(path.parent), "").strip()


def _read_layer(path: Path, layer: str | None) -> Iterator[ParsedFeature]:
    try:
        meta, _fids, wkb, fields = pyogrio.raw.read(str(path), layer=layer)
    except Exception as exc:  # GDAL raises a variety of errors
        raise ProcessingError(f"Could not read '{path.name}': {_scrub(exc, path)}") from exc

    if not meta.get("crs"):
        raise ProcessingError(
            f"Layer '{layer or path.stem}' has no CRS (missing .prj for a Shapefile?). "
            "Cannot compute measurements without a coordinate reference system."
        )
    try:
        crs = parse_crs(meta["crs"])
    except Exception as exc:
        raise ProcessingError(f"Unrecognised CRS definition: {exc}") from exc

    names = list(meta["fields"])
    geoms = shapely.from_wkb(wkb) if len(wkb) else []
    columns = [np.asarray(col).tolist() if not isinstance(col, list) else col for col in fields]
    layer_name = layer or path.stem

    for i in range(len(wkb)):
        geom = geoms[i]
        if geom is not None:
            geom = shapely.force_2d(geom)
        props = {n: _jsonable(columns[j][i]) for j, n in enumerate(names)}
        yield ParsedFeature(layer_name, geom, props, crs)


# --------------------------------------------------------------------------- KML
def read_kml(path: Path) -> Iterator[ParsedFeature]:
    try:
        layers = [row[0] for row in pyogrio.list_layers(str(path))]
    except Exception as exc:
        raise ProcessingError(f"Invalid KML file: {_scrub(exc, path)}") from exc
    if not layers:
        raise ProcessingError("KML file contains no layers/placemarks")
    for layer in layers:
        yield from _read_layer(path, layer)


# --------------------------------------------------------------------------- Shapefile
def _safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Extract only Shapefile component files, guarding against zip-slip and zip bombs."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ProcessingError("Uploaded file is not a valid zip archive") from exc

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > settings.max_zip_members:
            raise ProcessingError("Zip archive contains too many files")
        if sum(i.file_size for i in infos) > settings.max_unzipped_bytes:
            raise ProcessingError("Zip archive is too large when uncompressed")

        extracted: list[Path] = []
        written_total = 0
        for info in infos:
            pure = PurePosixPath(info.filename.replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts:
                raise ProcessingError(f"Unsafe path in zip archive: {info.filename}")
            if "__MACOSX" in pure.parts or pure.name.startswith("._"):
                continue
            if pure.suffix.lower() not in SHAPEFILE_PARTS:
                continue
            # Flatten: sibling files must stay together, nested folders are irrelevant.
            target = dest / pure.name
            if target.exists():
                raise ProcessingError(
                    f"Archive contains more than one file named '{pure.name}'; "
                    "upload one Shapefile per folder level or flatten the archive"
                )
            # Enforce the size cap on bytes actually written: the sizes declared in
            # the zip header can be forged.
            with zf.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1024 * 1024):
                    written_total += len(chunk)
                    if written_total > settings.max_unzipped_bytes:
                        raise ProcessingError("Zip archive is too large when uncompressed")
                    out.write(chunk)
            extracted.append(target)
        return extracted


def read_shapefile_zip(zip_path: Path, workdir: Path) -> Iterator[ParsedFeature]:
    files = _safe_extract(zip_path, workdir)
    shps = sorted(p for p in files if p.suffix.lower() == ".shp")
    if not shps:
        raise ProcessingError("Zip archive does not contain a .shp file")
    for shp in shps:
        if not shp.with_suffix(".dbf").exists() and not any(
            f.suffix.lower() == ".dbf" and f.stem == shp.stem for f in files
        ):
            raise ProcessingError(f"Shapefile '{shp.name}' is missing its .dbf component")
        yield from _read_layer(shp, None)
