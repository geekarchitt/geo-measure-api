from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from .models import FileStatus


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: str | None
    status: FileStatus
    error: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _as_utc(cls, v: datetime) -> datetime:
        # SQLite drops tzinfo; timestamps are always stored in UTC.
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)


class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    layer: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    crs: str | None
    properties: dict[str, Any]


class Measurement(BaseModel):
    type: Literal["area", "length"]
    value: float
    unit: Literal["m2", "m"]
    projected_crs: str


class MeasuredFeature(BaseModel):
    index: int
    layer: str | None
    geometry_type: str | None
    properties: dict[str, Any]
    measurement: Measurement | None
    status: str
    message: str | None = None


class MeasurementSummary(BaseModel):
    total_area_m2: float
    total_area_ha: float
    total_length_m: float
    total_length_km: float
    status_counts: dict[str, int]


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class MeasurementsResponse(BaseModel):
    file_id: str
    summary: MeasurementSummary
    page: Page
    features: list[MeasuredFeature]


class FeaturesResponse(BaseModel):
    file_id: str
    page: Page
    features: list[FeatureOut]
