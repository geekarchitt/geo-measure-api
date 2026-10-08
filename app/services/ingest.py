"""Orchestrates: save upload -> read features -> measure -> persist."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from shapely.geometry import mapping
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Feature, FileStatus, UploadedFile
from .crs import crs_label
from .errors import GeoServiceError, ProcessingError
from .measure import measure
from .readers import detect_file_type, read_kml, read_shapefile_zip

log = logging.getLogger(__name__)
BATCH = 1000


def process_upload(db: Session, filename: str, data: bytes) -> UploadedFile:
    """Persist an UploadedFile record and process it synchronously.

    Raises UnsupportedFileTypeError *before* anything is stored. Any processing
    failure is stored on the record (status=FAILED, error=...) and re-raised so
    the API layer can return a 422 that still references the stored record.
    """
    file_type = detect_file_type(filename)
    record = UploadedFile(filename=Path(filename).name[:255], file_type=file_type)
    db.add(record)
    db.commit()

    try:
        _ingest(db, record, data)
        record.status = FileStatus.COMPLETED
    except GeoServiceError as exc:
        db.rollback()
        _mark_failed(db, record, str(exc))
        exc.file_id = record.id
        raise
    except Exception as exc:  # unexpected - don't leak internals
        log.exception("Unexpected failure processing %s", record.id)
        db.rollback()
        _mark_failed(db, record, "Unexpected error while processing file")
        err = ProcessingError("Unexpected error while processing file")
        err.file_id = record.id
        raise err from exc
    db.commit()
    return record


def _mark_failed(db: Session, record: UploadedFile, message: str) -> None:
    db.query(Feature).filter(Feature.file_id == record.id).delete()
    record.status = FileStatus.FAILED
    record.error = message
    record.feature_count = 0
    db.commit()


def _ingest(db: Session, record: UploadedFile, data: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="geo_") as tmp:
        tmp_dir = Path(tmp)
        if record.file_type == "kml":
            stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(record.filename).stem) or "upload"
            src = tmp_dir / f"{stem}.kml"
            src.write_bytes(data)
            features = read_kml(src)
        else:
            src = tmp_dir / "upload.zip"
            src.write_bytes(data)
            work = tmp_dir / "extracted"
            work.mkdir()
            features = read_shapefile_zip(src, work)

        crs_labels: set[str] = set()
        batch: list[Feature] = []
        count = 0
        for pf in features:                       # generator: readers run lazily inside tmp dir
            if count >= settings.max_features:
                raise ProcessingError(f"File exceeds the {settings.max_features} feature limit")
            label = crs_label(pf.crs)
            crs_labels.add(label)
            result = measure(pf.geometry, pf.crs)
            batch.append(
                Feature(
                    file_id=record.id,
                    index=count,
                    layer=pf.layer,
                    geometry_type=pf.geometry.geom_type if pf.geometry is not None else None,
                    geometry=mapping(pf.geometry) if pf.geometry is not None and not pf.geometry.is_empty else None,
                    crs=label,
                    properties=pf.properties,
                    measurement_type=result.type,
                    measurement_value=result.value,
                    measurement_unit=result.unit,
                    projected_crs=result.projected_crs,
                    measurement_status=result.status,
                    message=result.message,
                )
            )
            count += 1
            if len(batch) >= BATCH:
                db.add_all(batch)
                db.flush()
                batch.clear()
        db.add_all(batch)

        record.feature_count = count
        record.crs = None if not crs_labels else (next(iter(crs_labels)) if len(crs_labels) == 1 else "MIXED")
