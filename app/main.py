import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from .api.files import router as files_router
from .db import Base, engine

logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(engine)

app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload a Shapefile (.zip) or KML and get per-feature area/length measurements.",
    version="1.0.0",
)
app.include_router(files_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")
