"""FastAPI application factory for the Sentinel gateway (Section 6.3)."""
from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel API", version="2.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    from api.routes import auth, events, grid_cells, hotspots, sources, stream
    app.include_router(auth.router)
    app.include_router(hotspots.router)
    app.include_router(grid_cells.router)
    app.include_router(events.router)
    app.include_router(sources.router)
    app.include_router(stream.router)

    from fastapi import Response

    from api.metrics import render_prometheus

    @app.get("/metrics")
    def metrics():
        return Response(render_prometheus(), media_type="text/plain")

    return app


app = create_app()
