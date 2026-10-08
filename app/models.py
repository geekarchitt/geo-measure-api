import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FileStatus(str, enum.Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UploadedFile(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))          # "shapefile" | "kml"
    status: Mapped[FileStatus] = mapped_column(Enum(FileStatus), default=FileStatus.PROCESSING)
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    features: Mapped[list["Feature"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="Feature.index"
    )


class Feature(Base):
    __tablename__ = "features"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)                  # global 0-based index in file
    layer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # GeoJSON, source CRS
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)

    # measurement results
    measurement_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # area|length
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)    # m² or m
    measurement_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    projected_crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    measurement_status: Mapped[str] = mapped_column(String(16), default="OK")        # OK|UNSUPPORTED|SKIPPED|ERROR
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    file: Mapped[UploadedFile] = relationship(back_populates="features")
