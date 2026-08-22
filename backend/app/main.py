"""FastAPI entrypoint.

Mounts the AHP engine (app/ahp/), the basins API (app/basins/) — an
alternative AOI-selection path alongside hand-drawn bboxes — and the
overlay engine (app/overlay/), which combines AHP weights with Phase 2
data regardless of which AOI-selection path produced the AOI. Shelter-
identification logic described in SPEC.md is still not implemented —
that's a later phase.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ahp import router as ahp_router
from app.basins import router as basins_router
from app.overlay import router as overlay_router

app = FastAPI(
    title="Flood Risk Mapping API — Kathmandu Valley",
    version="0.1.0",
)

# The frontend (Vite dev server) runs in the browser on a different origin
# (localhost:5173) than this API (localhost:8000), so every call it makes
# is cross-origin — without this, the browser blocks every fetch before
# it even reaches a route below. The two local dev origins
# docker-compose.yml actually exposes (both localhost and 127.0.0.1,
# since browsers treat them as distinct origins) are always allowed;
# CORS_EXTRA_ORIGINS (comma-separated) adds more without needing a code
# change — e.g. http://host.docker.internal:5173 when driving this app
# from a browser running in a sibling container rather than the host.
# Not a wildcard: this is a local-only dev stack (SPEC.md §4: "bound to
# 127.0.0.1 only"), so there's no real deployment origin to open up to.
_extra_origins = [o for o in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *_extra_origins,
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(ahp_router)
app.include_router(basins_router)
app.include_router(overlay_router)


@app.get("/")
def read_root() -> dict:
    return {"message": "Hello World", "service": "flood-risk-ktm-backend"}


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
