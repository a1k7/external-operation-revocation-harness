"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import APP_TITLE, APP_VERSION, BASE_DIR
from app.database import init_db
from app.routes import router as api_router

STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

@app.on_event("startup")
def _startup() -> None:
    init_db()

# THIS IS THE CRITICAL LINE THAT FIXES THE 404
app.include_router(api_router) 

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")