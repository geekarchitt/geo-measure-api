import io
import os
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest
import pyogrio.raw
import shapely
from shapely.geometry import LineString, Point, Polygon

_tmp = tempfile.mkdtemp()
os.environ["GEO_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def make_shapefile_zip(geoms, crs="EPSG:4326", geometry_type="Polygon", with_prj=True) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "layer.shp"
        names = np.array([f"f{i}" for i in range(len(geoms))], dtype=object)
        pyogrio.raw.write(
            str(path),
            geometry=shapely.to_wkb(np.array(geoms, dtype=object)),
            field_data=[names],
            fields=["name"],
            crs=crs,
            geometry_type=geometry_type,
            driver="ESRI Shapefile",
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for p in Path(d).iterdir():
                if p.suffix == ".prj" and not with_prj:
                    continue
                zf.write(p, p.name)
        return buf.getvalue()


KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>square</name><description>1km-ish square near Bhopal</description>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
77.40,23.25,0 77.41,23.25,0 77.41,23.26,0 77.40,23.26,0 77.40,23.25,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>road</name><LineString><coordinates>
77.40,23.25,0 77.42,23.25,0
</coordinates></LineString></Placemark>
<Placemark><name>pin</name><Point><coordinates>77.40,23.25,0</coordinates></Point></Placemark>
<Placemark><name>nogeom</name></Placemark>
<Placemark><name>mixed</name><MultiGeometry>
<Point><coordinates>77.4,23.2,0</coordinates></Point>
<LineString><coordinates>77.4,23.2,0 77.5,23.2,0</coordinates></LineString>
</MultiGeometry></Placemark>
</Document></kml>
"""
