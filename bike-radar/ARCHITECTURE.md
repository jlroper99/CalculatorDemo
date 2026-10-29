# Architecture

```
MBT per-ride CSV (primary) ─┐
                            ├─▶ ingest ─▶ passes ─▶ map matcher (Valhalla) ─▶ speed-limit enricher
FIT/GPX (secondary) ────────┘   (FIT: own pass detector + track)                    │
                                                                                    ▼
                    UI (Next.js + MapLibre) ◀── FastAPI ◀── PostGIS ◀── segment aggregator / scorer
```

## Stack
- **Backend:** Python 3.12, FastAPI, pandas (CSV), `fitdecode` (FIT fallback), SQLAlchemy + Alembic, Shapely/GeoPandas
- **DB:** PostgreSQL 16 + PostGIS (SQLite + SpatiaLite acceptable for a pure-local MVP)
- **Map matching:** self-hosted Valhalla `trace_attributes` (OSM way IDs + `speed_limit`). Fallback: nearest-way snap in PostGIS.
- **Speed limits (ADR-004):** manual > state DOT (Utah: UDOT `Statewide_Speed_Limit` FeatureServer) > OSM `maxspeed` (Geofabrik extract) > inferred (highway class + state default). UDOT speed-limit signs are used for validation. All source values are stored in `segment_limits`.
- **Frontend:** Next.js (TypeScript), MapLibre GL, Recharts
- **Infra:** docker-compose (db, valhalla, api, web), Makefile, GitHub Actions, pytest + Vitest + Playwright

## Data model (core)
- `rides(id, source ENUM(mbt_csv,fit), source_format_version, source_file_hash UNIQUE, started_at, ended_at, n_passes, has_track bool, notes)`
- `passes(id, ride_id, car_no, ts_utc, local_tz_abbr, local_hour, weekday, geom POINT, avg_abs_mps, max_abs_mps, pass_abs_mps, approach_abs_mps, max_rel_mps, approach_rel_mps, pass_rel_mps, slowdown_mps, approach_range_m, closest_range_m, pass_radar_count, approach_radar_count, track_seconds, rider_mps, way_id, match_distance_m, quality_flags text[], UNIQUE(ride_id, car_no))`
- `track_points(ride_id, ts, geom, rider_mps)`: only when a FIT/GPX track is attached
- `road_segments(way_id PK, name, highway, geom LINESTRING, lanes, shoulder, maxspeed_kph, limit_source ENUM(manual,dot,osm,ugrc,inferred))`
- `segment_limits(way_id, source ENUM(manual,dot,osm,ugrc,inferred), mph, source_ref, fetched_at)`; the chosen value is denormalized onto `road_segments`
- `segment_exposure(way_id, ride_id, seconds, meters, exposure_source ENUM(track,traversal))`
- `segment_stats(way_id, bucket, n_passes, n_rides, passes_per_hour, p50_max_abs, p85_max_abs, pct_over, pct_over10, danger_score, computed_at)`
- `privacy_zones(id, geom POLYGON)`

## Key algorithms
1. **CSV ingest (primary):** validate the `mbt_csv_v1` header and map columns to SI (see features/001). Passes are taken as-is from MBT. Key on (ride, car_no), never on timestamp.
2. **FIT ingest (secondary, features/005):** the developer fields feed our MBT-style detector and produce the same `passes` schema. The track is also used for exposure.
3. **Map matching:** pass points (plus the track if present) go to Valhalla. Store `way_id` and the match distance.
4. **Scoring:** features/003. Speed basis is `max_abs_mps`. All components are stored.
5. **Idempotency:** a file hash makes a re-import a no-op. Stats are recomputed for the affected ways.

## Units (from the 2026-10-28 sample; TODO(verify) with the MBT maintainer)
Absolute and relative speeds are in m/s. Relative speeds come in 3 m/s Varia buckets. Ranges are in meters (longitudinal). `passlength` is in seconds. Timestamps are in epoch seconds UTC.
