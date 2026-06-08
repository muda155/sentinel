"""FastAPI application factory for the Sentinel gateway (Section 6.3)."""
from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel API", version="2.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    from api.routes import events, hotspots, stream
    app.include_router(hotspots.router)
    app.include_router(events.router)
    app.include_router(stream.router)
    return app


app = create_app()
