import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point, Polygon

from app.services.crs import utm_epsg_for
from .conftest import KML, make_shapefile_zip

GEOD = Geod(ellps="WGS84")


def upload(client, name, data):
    return client.post("/api/files/", files={"file": (name, data)})


def by_name(items):
    return {f["properties"].get("Name") or f["properties"].get("name"): f for f in items}


# ---------------------------------------------------------------- KML
def test_kml_upload_and_measurements(client):
    r = upload(client, "survey.kml", KML.encode())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "COMPLETED" and body["crs"] == "EPSG:4326"
    assert body["feature_count"] == 5

    assert client.get(f"/api/files/{body['id']}/").json()["filename"] == "survey.kml"

    m = client.get(f"/api/files/{body['id']}/measurements/").json()
    feats = by_name(m["features"])

    square = Polygon([(77.40, 23.25), (77.41, 23.25), (77.41, 23.26), (77.40, 23.26)])
    geodesic_area = abs(GEOD.geometry_area_perimeter(square)[0])
    sq = feats["square"]["measurement"]
    assert sq["type"] == "area" and sq["unit"] == "m2" and sq["projected_crs"] == "EPSG:32643"
    assert sq["value"] == pytest.approx(geodesic_area, rel=1e-3)   # UTM vs ellipsoid

    geodesic_len = GEOD.geometry_length(LineString([(77.40, 23.25), (77.42, 23.25)]))
    rd = feats["road"]["measurement"]
    assert rd["type"] == "length" and rd["value"] == pytest.approx(geodesic_len, rel=1e-3)

    assert feats["pin"]["status"] == "NOT_APPLICABLE" and feats["pin"]["measurement"] is None
    assert feats["nogeom"]["status"] == "SKIPPED"
    assert feats["mixed"]["status"] == "UNSUPPORTED"          # GeometryCollection: graceful
    assert m["summary"]["status_counts"]["OK"] == 2
    assert m["summary"]["total_area_m2"] == pytest.approx(sq["value"])


def test_features_endpoint_returns_geometry_crs_properties(client):
    fid = upload(client, "s.kml", KML.encode()).json()["id"]
    feats = client.get(f"/api/files/{fid}/features/").json()["features"]
    assert [f["index"] for f in feats] == [0, 1, 2, 3, 4]
    assert feats[0]["geometry_type"] == "Polygon" and feats[0]["crs"] == "EPSG:4326"
    assert feats[0]["geometry"]["type"] == "Polygon"
    assert feats[3]["geometry"] is None


def test_measurement_filter_and_pagination(client):
    fid = upload(client, "s.kml", KML.encode()).json()["id"]
    m = client.get(f"/api/files/{fid}/measurements/?type=area").json()
    assert m["page"]["total"] == 1
    m = client.get(f"/api/files/{fid}/measurements/?limit=2&offset=1").json()
    assert [f["index"] for f in m["features"]] == [1, 2]


# ---------------------------------------------------------------- Shapefile
def test_shapefile_wgs84(client):
    poly = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])
    r = upload(client, "p.zip", make_shapefile_zip([poly]))
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    m = client.get(f"/api/files/{fid}/measurements/").json()
    v = m["features"][0]["measurement"]["value"]
    # Feature sits ~3 degrees from its UTM zone's central meridian, where UTM's
    # scale distortion is largest (~0.2% in area), hence the looser tolerance.
    assert v == pytest.approx(abs(GEOD.geometry_area_perimeter(poly)[0]), rel=5e-3)


def test_shapefile_projected_crs_is_handled(client):
    # 100m x 200m rectangle in UTM 43N (EPSG:32643)
    poly = Polygon([(500000, 2570000), (500100, 2570000), (500100, 2570200), (500000, 2570200)])
    r = upload(client, "utm.zip", make_shapefile_zip([poly], crs="EPSG:32643"))
    assert r.json()["crs"] == "EPSG:32643"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    assert m["features"][0]["measurement"]["value"] == pytest.approx(20000, rel=1e-4)


def test_shapefile_lines_and_points(client):
    line = LineString([(77.0, 23.0), (77.1, 23.0)])
    r = upload(client, "l.zip", make_shapefile_zip([line], geometry_type="LineString"))
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    assert m["features"][0]["measurement"]["type"] == "length"

    r = upload(client, "pt.zip", make_shapefile_zip([Point(77, 23)], geometry_type="Point"))
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    assert m["features"][0]["status"] == "NOT_APPLICABLE"


def test_shapefile_without_crs_fails_gracefully(client):
    poly = Polygon([(0, 0), (1, 0), (1, 1)])
    r = upload(client, "nocrs.zip", make_shapefile_zip([poly], with_prj=False))
    assert r.status_code == 422
    fid = r.json()["detail"]["id"]
    info = client.get(f"/api/files/{fid}/").json()
    assert info["status"] == "FAILED" and "CRS" in info["error"]
    assert client.get(f"/api/files/{fid}/measurements/").status_code == 409


# ---------------------------------------------------------------- errors
def test_bad_inputs(client):
    assert upload(client, "a.txt", b"x").status_code == 415
    assert client.post("/api/files/", files={"file": ("e.kml", b"")}).status_code == 400
    assert upload(client, "bad.zip", b"not a zip").status_code == 422
    assert upload(client, "bad.kml", b"<kml>garbage").status_code == 422
    assert client.get("/api/files/nope/").status_code == 404


def test_zip_slip_rejected(client):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.shp", b"x")
    assert upload(client, "evil.zip", buf.getvalue()).status_code == 422


# ---------------------------------------------------------------- unit
def test_utm_zone_selection():
    assert utm_epsg_for(77.4, 23.2) == 32643
    assert utm_epsg_for(-74.0, 40.7) == 32618
    assert utm_epsg_for(151.2, -33.9) == 32756
    assert utm_epsg_for(180.0, 0) == 32601        # antimeridian wraps
    assert utm_epsg_for(0, 88) == 32661           # polar cap


# ---------------------------------------------------------------- extra API coverage
def test_kml_with_folders_reads_all_layers(client):
    kml = """<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
    <Folder><name>Parcels</name><Placemark><name>a</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
    77.40,23.25 77.41,23.25 77.41,23.26 77.40,23.25</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Folder>
    <Folder><name>Roads</name><Placemark><name>b</name><LineString><coordinates>77.4,23.2 77.5,23.2</coordinates></LineString></Placemark></Folder>
    </Document></kml>"""
    r = upload(client, "folders.kml", kml.encode())
    assert r.status_code == 201 and r.json()["feature_count"] == 2
    feats = client.get(f"/api/files/{r.json()['id']}/features/").json()["features"]
    assert {f["layer"] for f in feats} == {"Parcels", "Roads"}
    assert [f["index"] for f in feats] == [0, 1]


def test_zip_with_nested_folder_and_macosx_junk(client):
    import io, zipfile
    poly = Polygon([(77.40, 23.25), (77.41, 23.25), (77.41, 23.26), (77.40, 23.26)])
    inner = zipfile.ZipFile(io.BytesIO(make_shapefile_zip([poly])))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in inner.namelist():
            zf.writestr(f"data/{n}", inner.read(n))
        zf.writestr("__MACOSX/data/._layer.shp", b"junk")
    r = upload(client, "nested.zip", buf.getvalue())
    assert r.status_code == 201 and r.json()["feature_count"] == 1


def test_zip_without_shp_rejected(client):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", b"hello")
    r = upload(client, "empty.zip", buf.getvalue())
    assert r.status_code == 422 and ".shp" in r.json()["detail"]["message"]


def test_zip_duplicate_filenames_rejected(client):
    import io, zipfile
    poly = Polygon([(77.40, 23.25), (77.41, 23.25), (77.41, 23.26)])
    inner = zipfile.ZipFile(io.BytesIO(make_shapefile_zip([poly])))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in inner.namelist():
            zf.writestr(f"a/{n}", inner.read(n))
            zf.writestr(f"b/{n}", inner.read(n))
    assert upload(client, "dup.zip", buf.getvalue()).status_code == 422


def test_list_and_delete(client):
    fid = upload(client, "s.kml", KML.encode()).json()["id"]
    assert any(f["id"] == fid for f in client.get("/api/files/").json())
    assert client.delete(f"/api/files/{fid}/").status_code == 204
    assert client.get(f"/api/files/{fid}/").status_code == 404
    assert client.get(f"/api/files/{fid}/measurements/").status_code == 404


def test_file_info_matches_spec_shape(client):
    info = upload(client, "survey.kml", KML.encode()).json()
    for key in ("id", "filename", "feature_count", "crs", "status"):
        assert key in info
    assert info == client.get(f"/api/files/{info['id']}/").json()


def test_root_redirects_to_docs_and_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/", follow_redirects=False).status_code in (302, 307)


def test_error_messages_do_not_leak_server_paths(client):
    r = upload(client, "bad.kml", b"<kml>garbage")
    assert r.status_code == 422
    msg = r.json()["detail"]["message"]
    assert "/tmp" not in msg and "geo_" not in msg and "\\Temp" not in msg
