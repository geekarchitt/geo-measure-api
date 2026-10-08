class GeoServiceError(Exception):
    """Base class for expected, user-facing processing errors."""

    file_id: str | None = None  # id of the stored (FAILED) record, if any


class UnsupportedFileTypeError(GeoServiceError):
    """Uploaded file is not a .zip (Shapefile) or .kml."""


class ProcessingError(GeoServiceError):
    """File is of a supported type but could not be read/processed."""
