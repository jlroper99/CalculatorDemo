"""HTTP API. Interactive docs at /docs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from geoalchemy2.functions import ST_X, ST_Y
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bikeradar.config import get_settings
from bikeradar.db import get_session
from bikeradar.ingest.service import ImportResult, ImportStatus, import_bytes
from bikeradar.models import Pass, Ride
from bikeradar.privacy import endpoint_mask

SessionDep = Annotated[Session, Depends(get_session)]

app = FastAPI(title="Bike Radar Danger Map API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class RideOut(BaseModel):
    id: int
    source: str
    source_format_version: str
    source_filename: str | None
    started_at: str
    ended_at: str
    n_passes: int
    has_track: bool
    notes: str | None


def _ride_out(r: Ride) -> RideOut:
    return RideOut(
        id=r.id,
        source=r.source.value,
        source_format_version=r.source_format_version,
        source_filename=r.source_filename,
        started_at=r.started_at.isoformat(),
        ended_at=r.ended_at.isoformat(),
        n_passes=r.n_passes,
        has_track=r.has_track,
        notes=r.notes,
    )


@app.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/rides/upload")
async def upload_rides(
    files: list[UploadFile],
    session: SessionDep,
    replace: Annotated[bool, Query()] = False,
) -> list[dict[str, Any]]:
    """Import one or more MBT per-ride CSV exports. Files are parsed in memory, never stored."""
    settings = get_settings()
    results: list[ImportResult] = []
    for f in files:
        name = f.filename or "upload.csv"
        data = await f.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            results.append(ImportResult(name, ImportStatus.FAILED, error="file too large"))
            continue
        results.append(
            import_bytes(
                session, data, name, replace=replace, thresholds=settings.quality_thresholds()
            )
        )
    return [r.as_dict() for r in results]


@app.get("/rides")
def list_rides(session: SessionDep) -> list[RideOut]:
    return [_ride_out(r) for r in session.scalars(select(Ride).order_by(Ride.started_at.desc()))]


@app.get("/rides/{ride_id}")
def get_ride(ride_id: int, session: SessionDep) -> RideOut:
    ride = session.get(Ride, ride_id)
    if ride is None:
        raise HTTPException(404, "ride not found")
    return _ride_out(ride)


PASS_PROPERTIES = (
    "car_no",
    "local_tz_abbr",
    "local_hour",
    "weekday",
    "avg_abs_mps",
    "max_abs_mps",
    "pass_abs_mps",
    "approach_abs_mps",
    "max_rel_mps",
    "approach_rel_mps",
    "pass_rel_mps",
    "slowdown_mps",
    "approach_range_m",
    "closest_range_m",
    "pass_radar_count",
    "approach_radar_count",
    "track_seconds",
    "rider_mps",
    "way_id",
    "match_distance_m",
    "quality_flags",
)


@app.get("/rides/{ride_id}/passes")
def ride_passes(ride_id: int, session: SessionDep) -> dict[str, Any]:
    """Passes as GeoJSON. Points near the ride's start/end have `geometry: null`."""
    if session.get(Ride, ride_id) is None:
        raise HTTPException(404, "ride not found")
    rows = session.execute(
        select(Pass, ST_Y(Pass.geom), ST_X(Pass.geom))
        .where(Pass.ride_id == ride_id)
        .order_by(Pass.ts_utc, Pass.car_no)
    ).all()
    points = [None if lat is None else (float(lat), float(lon)) for _, lat, lon in rows]
    masked = endpoint_mask(points, get_settings().privacy_endpoint_radius_m)
    features = []
    for (p, _, _), point, hide in zip(rows, points, masked, strict=True):
        props: dict[str, Any] = {k: getattr(p, k) for k in PASS_PROPERTIES}
        props["ts_utc"] = p.ts_utc.isoformat()
        props["location_masked"] = hide
        geometry = (
            None
            if hide or point is None
            else {"type": "Point", "coordinates": [point[1], point[0]]}
        )
        features.append({"type": "Feature", "id": p.id, "geometry": geometry, "properties": props})
    return {"type": "FeatureCollection", "features": features}
