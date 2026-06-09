"""FastAPI application factory for the Sentinel gateway (Section 6.3)."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="Sentinel API", version="2.0")

    # The Next.js frontend is served from a different origin (default :3000),
    # so the browser issues cross-origin requests to this API. Allow the
    # configured frontend origins; override via SENTINEL_CORS_ORIGINS (CSV).
    origins = [
        o.strip()
        for o in os.getenv(
            "SENTINEL_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
