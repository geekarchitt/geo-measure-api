# Geospatial File Measurement API

A FastAPI backend that accepts a **Shapefile (`.zip`)** or a **KML (`.kml`)**, extracts every feature
(index, geometry type, GeoJSON geometry, CRS, attributes) and returns **area** (polygons) and **length** (lines)
in metres. Geometries are always reprojected into a suitable *projected* CRS before measuring, never measured in degrees.

* Framework: FastAPI + Pydantic + SQLAlchemy (SQLite by default)
* Geospatial stack: `pyogrio` (GDAL) · `shapely` · `pyproj`
* 29 automated tests, GitHub Actions CI, Dockerfile

---

## Setup

Requires **Python 3.10+** (developed and tested on 3.12; CI runs 3.11, 3.12, 3.13).
`shapely`, `pyproj` and `pyogrio` ship binary wheels that bundle GDAL/PROJ, so no system GDAL install is needed.

### Linux / macOS
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

### Windows (cmd)
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```
(PowerShell: activate with `.venv\Scripts\Activate.ps1`.)

The API is now at **http://localhost:8000** and interactive Swagger docs at **http://localhost:8000/docs**.

### Run the tests
```bash
python -m pytest
```

### Docker
```bash
docker build -t geo-measure .
docker run -p 8000:8000 -v geo-data:/data geo-measure
```

### Try it with the bundled samples
```bash
curl -F "file=@samples/survey.kml"        http://localhost:8000/api/files/
curl -F "file=@samples/parcels_wgs84.zip" http://localhost:8000/api/files/
curl -F "file=@samples/roads_wgs84.zip"   http://localhost:8000/api/files/
```
On Windows use `curl.exe` (plain `curl` is a PowerShell alias), or use the "Try it out" buttons at `/docs`.

> **Note:** some locked-down Windows machines (Smart App Control / Application Control policies) block the compiled
> GDAL extension in `pyogrio`. If you see *"An Application Control policy has blocked this file"*, run the project in
> Docker, WSL or GitHub Codespaces instead.

### Configuration
Environment variables (or a `.env` file, see `.env.example`), all optional:

| Variable | Default | Meaning |
|---|---|---|
| `GEO_DATABASE_URL` | `sqlite:///./geo.db` | SQLAlchemy database URL |
| `GEO_MAX_UPLOAD_BYTES` | 52428800 (50 MB) | Max upload size |
| `GEO_MAX_UNZIPPED_BYTES` | 209715200 (200 MB) | Max total size of extracted Shapefile parts (zip-bomb guard) |
| `GEO_MAX_ZIP_MEMBERS` | 200 | Max files in a zip |
| `GEO_MAX_FEATURES` | 100000 | Max features per file |

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/files/` | Upload & process a `.zip` (Shapefile) or `.kml` (multipart field `file`) |
| `GET` | `/api/files/` | List uploaded files (`limit`, `offset`) |
| `GET` | `/api/files/{id}/` | File information |
| `GET` | `/api/files/{id}/features/` | Extracted features: index, geometry type, GeoJSON geometry, CRS, properties (`limit`, `offset`) |
| `GET` | `/api/files/{id}/measurements/` | Per-feature measurements + file totals (`limit`, `offset`, `type=area\|length`) |
| `DELETE` | `/api/files/{id}/` | Delete a file and its features |
| `GET` | `/health` | Liveness probe |

### Upload: `POST /api/files/`
```bash
curl -F "file=@samples/survey.kml" http://localhost:8000/api/files/
```
`201 Created`
```json
{
  "id": "539aa8032bc74c9bb51bc5e9a982dbc1",
  "filename": "survey.kml",
  "file_type": "kml",
  "feature_count": 5,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null,
  "created_at": "2026-10-07T14:18:04.510440Z"
}
```
`crs` is the file's CRS, or `"MIXED"` if layers differ. `status` is `COMPLETED` or `FAILED`.

### File info: `GET /api/files/{id}/`
Returns the same object as above.

### Features: `GET /api/files/{id}/features/?limit=1`
```json
{
  "file_id": "539aa8032bc74c9bb51bc5e9a982dbc1",
  "page": { "total": 5, "limit": 1, "offset": 0 },
  "features": [
    {
      "index": 0,
      "layer": "survey",
      "geometry_type": "Polygon",
      "geometry": { "type": "Polygon", "coordinates": [[[77.4,23.25],[77.41,23.25],[77.41,23.26],[77.4,23.26],[77.4,23.25]]] },
      "crs": "EPSG:4326",
      "properties": { "Name": "square", "description": "1km-ish square near Bhopal" }
    }
  ]
}
```
(`properties` abbreviated here; KML files also carry GDAL's standard KML fields such as `timestamp`, `altitudeMode`.)

### Measurements: `GET /api/files/{id}/measurements/`
Real output for `samples/survey.kml` (abbreviated properties):
```json
{
  "file_id": "539aa8032bc74c9bb51bc5e9a982dbc1",
  "summary": {
    "total_area_m2": 1134057.1446,
    "total_area_ha": 113.405714,
    "total_length_m": 2047.3738,
    "total_length_km": 2.047374,
    "status_counts": { "OK": 2, "NOT_APPLICABLE": 1, "SKIPPED": 1, "UNSUPPORTED": 1 }
  },
  "page": { "total": 5, "limit": 100, "offset": 0 },
  "features": [
    { "index": 0, "layer": "survey", "geometry_type": "Polygon", "properties": { "Name": "square" },
      "measurement": { "type": "area", "value": 1134057.1446, "unit": "m2", "projected_crs": "EPSG:32643" },
      "status": "OK", "message": null },
    { "index": 1, "layer": "survey", "geometry_type": "LineString", "properties": { "Name": "road" },
      "measurement": { "type": "length", "value": 2047.3738, "unit": "m", "projected_crs": "EPSG:32643" },
      "status": "OK", "message": null },
    { "index": 2, "layer": "survey", "geometry_type": "Point", "properties": { "Name": "pin" },
      "measurement": null, "status": "NOT_APPLICABLE", "message": "No measurement defined for points" },
    { "index": 3, "layer": "survey", "geometry_type": null, "properties": { "Name": "nogeom" },
      "measurement": null, "status": "SKIPPED", "message": "Feature has no geometry" },
    { "index": 4, "layer": "survey", "geometry_type": "GeometryCollection", "properties": { "Name": "mixed" },
      "measurement": null, "status": "UNSUPPORTED",
      "message": "Measurement not supported for geometry type 'GeometryCollection'" }
  ]
}
```
Summary totals cover the **whole file**, regardless of pagination or the `type` filter.

Per-feature `status`:

| Status | Meaning |
|---|---|
| `OK` | Measured (`area` in m² for polygons, `length` in m for lines) |
| `NOT_APPLICABLE` | Points: no measurement required |
| `UNSUPPORTED` | Geometry type with no measurement (e.g. `GeometryCollection`) |
| `SKIPPED` | Feature has no/empty geometry |
| `ERROR` | Measurement failed for this feature (e.g. non-finite coordinates) |

A problematic feature never fails the whole file.

### Errors

| Code | When |
|---|---|
| 400 | Empty upload |
| 404 | Unknown file id |
| 409 | `features` / `measurements` requested for a file that is not `COMPLETED` |
| 413 | Upload larger than `GEO_MAX_UPLOAD_BYTES` |
| 415 | Extension is not `.zip` or `.kml` |
| 422 | File unreadable: corrupt zip/KML, no `.shp` in the zip, **no CRS** (missing `.prj`), unsafe or duplicate zip entries, too many features |

A 422 still stores the upload with `status: "FAILED"` so it can be inspected via `GET /api/files/{id}/`:
```json
{ "detail": { "message": "Shapefile ... has no CRS (missing .prj ...)", "id": "55ce...", "status": "FAILED" } }
```

---

## Architecture

### Application structure
```
app/
  main.py             FastAPI app, router wiring, /health
  config.py           environment-driven settings
  db.py, models.py    SQLAlchemy engine/session; UploadedFile 1──* Feature
  schemas.py          Pydantic response models
  api/files.py        HTTP layer only: validation, status codes, pagination
  services/
    readers.py        Shapefile-zip / KML  ->  ParsedFeature (shapely geometry, properties, CRS)
    crs.py            CRS parsing + labelling, UTM selection, reprojection
    measure.py        geometry -> MeasureResult (never raises)
    ingest.py         orchestration: read -> measure -> persist, failure handling
    errors.py         expected, user-facing exceptions
tests/                API + unit tests using generated Shapefile/KML fixtures
samples/              ready-to-upload example files
```
The API layer contains no geospatial logic; services have no HTTP knowledge, so they can be tested and reused independently.

### File-processing flow
1. Validate size and extension (415 / 413 / 400 before anything is stored). Create an `UploadedFile` row.
2. Write the bytes to a temporary directory. For zips, extract **only** Shapefile component files
   (`.shp .shx .dbf .prj .cpg .qpj`), guarding against path traversal (zip-slip), too many members, duplicate names and
   zip bombs (size is enforced on bytes actually written, not on the header).
3. Read each layer with `pyogrio` (GDAL) into WKB, then shapely geometries. KML Folders/Documents become layers and all are read.
   `index` is a global 0-based feature index; `layer` records where it came from. Z values are dropped (planar 2-D).
4. Each feature is measured and stored (GeoJSON geometry in its **original** CRS, properties, measurement) in batches.
5. File is marked `COMPLETED`, or `FAILED` with an error message if anything unrecoverable happened.

### Measurement-calculation flow (`measure.py`)
| Geometry | Result |
|---|---|
| Polygon / MultiPolygon | area (m²), multi-part geometries are summed, holes subtracted |
| LineString / MultiLineString / LinearRing | length (m) |
| Point / MultiPoint | `NOT_APPLICABLE` |
| anything else (e.g. GeometryCollection) | `UNSUPPORTED` |
| missing / empty geometry | `SKIPPED` |

Invalid polygons (e.g. self-intersecting "bow-ties") are repaired with `make_valid` before measuring and flagged in `message`.
The whole function is wrapped so that any unexpected error becomes `status: "ERROR"` for that feature only.

### CRS handling (`crs.py`)
* The source CRS comes from the Shapefile's `.prj`, or WGS 84 for KML. A Shapefile **without** a CRS is rejected with a
  clear error rather than silently assuming one.
* **Degrees are never measured.** For every feature a representative point is converted to lon/lat and the **local WGS 84
  UTM zone** is chosen (EPSG:326xx north / 327xx south; polar stereographic EPSG:32661/32761 beyond 84°N / 80°S; the
  antimeridian wraps correctly). The geometry is transformed with `pyproj` and measured with planar area/length.
* This also applies to files that are *already projected*. A CRS being in metres does not make it suitable for measuring:
  Web Mercator (EPSG:3857) inflates areas by 1/cos²(latitude), about 4× at 60°N. There is a test for exactly this.
* The projected CRS used is returned with every measurement (`projected_crs`).
* **Accuracy:** UTM scale distortion is below ~0.04 % in length (~0.1 % in area) near a zone's central meridian and grows
  towards zone edges (a test feature ~3° off-centre shows ~0.2 % area difference). Tests compare against ellipsoidal
  (`pyproj.Geod`) results as an independent check.

---

## Design decisions

| Decision | Rationale / alternatives considered |
|---|---|
| **FastAPI** over Django + DRF | Small API-only service; typed Pydantic schemas, automatic OpenAPI docs, no ORM/admin overhead needed. |
| **`pyogrio` + shapely + pyproj** over GeoPandas/Fiona | Much lighter install, wheels bundle GDAL, no pandas needed. Reading raw WKB keeps memory and dependencies small. Pure-Python parsers (`pyshp`, hand-rolled KML) were rejected: they miss many real-world KML/Shapefile quirks that GDAL handles. |
| **Local UTM zone per feature** | Keeps every measurement local and accurate even if one file spans several zones. Alternatives: one CRS per file from the centroid (simple, poor for large files); equal-area projection (exact areas but distorted lengths and no EPSG code to report); geodesic maths via `pyproj.Geod` (most accurate, but the brief asks for projection, so it is used only as a test oracle). |
| **Synchronous processing** | Correct and simple within the 50 MB cap. The `status` field and `PROCESSING` state already exist, so moving to a background worker later is non-breaking. |
| **Features stored in the DB (JSON geometry, original CRS)** | Pagination and re-querying without re-parsing; the original file is not retained. |
| **Layered failure model** | Bad upload → 4xx, nothing stored. Unreadable file → stored as `FAILED` (inspectable). Bad feature → per-feature status, file still `COMPLETED`. |
| **No guessing of missing CRS** | A wrong assumed CRS gives confidently wrong numbers; failing loudly is safer. |
| **SQLite default** | Zero-setup for reviewers; `GEO_DATABASE_URL` switches to PostgreSQL without code changes. |
| **Security hardening** | Zip-slip/zip-bomb/duplicate-member guards, upload size cap, sanitised filenames, error messages scrubbed of server paths, non-root Docker user. |

---

## Testing
`python -m pytest` runs 29 tests: API behaviour (KML/Shapefile upload, projected CRS input, multi-layer KML, nested/
malicious/corrupt zips, missing CRS, pagination, filters, list/delete, error codes) and unit tests for the measurement
logic (holes, multipolygons, invalid polygons, southern hemisphere, antimeridian, Web Mercator, unsupported/empty
geometries, bad coordinates). Measurements are validated against `pyproj.Geod` ellipsoidal results.

## Learnings
* GDAL's KML driver surfaces Placemarks with no geometry and `MultiGeometry` with mixed types as `GeometryCollection`;
  handling these explicitly motivated the per-feature status model instead of "measure or crash".
* Choosing a CRS by *units* is a trap: Web Mercator is in metres but badly distorts area. Choosing by *location* is right.
* UTM is accurate but not uniform; comparing against `pyproj.Geod` made the real error visible and set honest test tolerances.
* SQLite silently drops timezone info; a test comparing the upload response with a later `GET` exposed inconsistent
  timestamps, fixed by normalising to UTC in the schema.
* Zip uploads are an attack surface: header-declared sizes can be forged, so limits must be enforced on bytes actually written.
* GDAL error messages can embed server temp paths; they must be scrubbed before being returned to clients.

## Future scope
* Background processing (Celery/RQ) with polling or webhooks for large files; streaming uploads.
* Selectable measurement mode via query parameter: geodesic (`pyproj.Geod`) or equal-area, plus UTM exceptions
  (Norway/Svalbard) and splitting features that straddle several zones.
* More formats: KMZ, GeoJSON, GeoPackage; Shapefiles without `.prj` via a user-supplied `crs` parameter.
* More measurements: perimeter, centroid, bounding box; unit conversion (`?units=ha,km,acres`).
* PostgreSQL/PostGIS storage with spatial indexes and spatial queries, Alembic migrations.
* Authentication, per-user files, rate limiting, structured logging/metrics, retention/cleanup of old files.

## License
MIT
