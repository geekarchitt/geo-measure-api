from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Feature, FileStatus, UploadedFile
from ..schemas import (
    FeatureOut, FeaturesResponse, FileOut, MeasuredFeature, Measurement,
    MeasurementsResponse, MeasurementSummary, Page,
)
from ..services.errors import GeoServiceError, UnsupportedFileTypeError
from ..services.ingest import process_upload

router = APIRouter(prefix="/api/files", tags=["files"])


def _get_file(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return record


def _require_completed(record: UploadedFile) -> None:
    if record.status != FileStatus.COMPLETED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"File status is {record.status.value}" + (f": {record.error}" if record.error else ""),
        )


@router.post("/", response_model=FileOut, status_code=status.HTTP_201_CREATED)
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a `.zip` (containing a Shapefile) or a `.kml`; it is processed synchronously."""
    name = file.filename or ""
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    try:
        return process_upload(db, name, data)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc))
    except GeoServiceError as exc:
        raise HTTPException(
            422,
            {"message": str(exc), "id": exc.file_id, "status": "FAILED"},
        )


@router.get("/", response_model=list[FileOut])
def list_files(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db)):
    q = select(UploadedFile).order_by(UploadedFile.created_at.desc()).limit(limit).offset(offset)
    return db.scalars(q).all()


@router.get("/{file_id}/", response_model=FileOut)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_file(db, file_id)


@router.delete("/{file_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: str, db: Session = Depends(get_db)):
    db.delete(_get_file(db, file_id))
    db.commit()


@router.get("/{file_id}/features/", response_model=FeaturesResponse)
def get_features(file_id: str, limit: int = Query(100, ge=1, le=1000),
                 offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Extracted features: index, geometry type, GeoJSON geometry, CRS, properties."""
    record = _get_file(db, file_id)
    _require_completed(record)
    rows = db.scalars(
        select(Feature).where(Feature.file_id == file_id)
        .order_by(Feature.index).limit(limit).offset(offset)
    ).all()
    return FeaturesResponse(
        file_id=file_id,
        page=Page(total=record.feature_count, limit=limit, offset=offset),
        features=[FeatureOut.model_validate(r) for r in rows],
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementsResponse)
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    type: Literal["area", "length"] | None = Query(None, description="Filter by measurement type"),
    db: Session = Depends(get_db),
):
    record = _get_file(db, file_id)
    _require_completed(record)

    # Summary is computed over the whole file, independent of pagination.
    totals = dict(db.execute(
        select(Feature.measurement_type, func.coalesce(func.sum(Feature.measurement_value), 0.0))
        .where(Feature.file_id == file_id, Feature.measurement_status == "OK")
        .group_by(Feature.measurement_type)
    ).all())
    counts = dict(db.execute(
        select(Feature.measurement_status, func.count())
        .where(Feature.file_id == file_id).group_by(Feature.measurement_status)
    ).all())
    area, length = float(totals.get("area", 0.0)), float(totals.get("length", 0.0))

    where = [Feature.file_id == file_id]
    if type:
        where.append(Feature.measurement_type == type)
    total = db.scalar(select(func.count()).select_from(Feature).where(*where)) or 0
    rows = db.scalars(
        select(Feature).where(*where).order_by(Feature.index).limit(limit).offset(offset)
    ).all()

    items = [
        MeasuredFeature(
            index=r.index, layer=r.layer, geometry_type=r.geometry_type, properties=r.properties,
            status=r.measurement_status, message=r.message,
            measurement=Measurement(
                type=r.measurement_type, value=r.measurement_value,
                unit=r.measurement_unit, projected_crs=r.projected_crs,
            ) if r.measurement_status == "OK" else None,
        )
        for r in rows
    ]
    return MeasurementsResponse(
        file_id=file_id,
        summary=MeasurementSummary(
            total_area_m2=round(area, 4), total_area_ha=round(area / 10_000, 6),
            total_length_m=round(length, 4), total_length_km=round(length / 1000, 6),
            status_counts=counts,
        ),
        page=Page(total=total, limit=limit, offset=offset),
        features=items,
    )
