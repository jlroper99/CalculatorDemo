# Decision Log (ADRs)

Copy the template for each decision. Never edit an accepted ADR. Supersede it instead.

## Template
### ADR-NNN: Title
- **Date:** YYYY-MM-DD
- **Status:** proposed | accepted | superseded by ADR-XXX
- **Context:** what forces are at play
- **Decision:** what we chose
- **Alternatives:** what we rejected and why
- **Consequences:** trade-offs, follow-ups

---

### ADR-001: Ingest original Garmin FIT files, not MyBikeTraffic pages
- **Date:** 2026-10-28
- **Status:** superseded by ADR-003
- **Context:** MBT has no documented API. Its raw CSV export is disabled. The MBT Connect IQ data field writes radar developer fields (`radar_ranges`, `radar_speeds`, `passing_speed`, `passing_speedabs`, `radar_current`) into the FIT file.
- **Decision:** Parse FIT files directly. Use MBT only for manual cross-checks.
- **Alternatives:** Scraping MBT (fragile, ToS risk). Waiting for MBT exports.
- **Consequences:** Users must export FIT files (or we integrate Garmin later). Reach out to MBT for partnership before going public.

### ADR-002: Valhalla for map matching + OSM speed limits (limit precedence superseded by ADR-004)
- **Date:** 2026-10-28
- **Status:** accepted (confirmed 2026-10-29 at M0; compose service details in ADR-008)
- **Context:** Need way IDs + maxspeed per point, free, self-hostable.
- **Decision:** Valhalla `trace_attributes` in Docker with a state OSM extract.
- **Alternatives:** OSRM match (no maxspeed attrs by default), Mapbox/HERE/TomTom (cost, storage terms).
- **Consequences:** Extra container. OSM limits are patchy, so we need inference + manual override.

### ADR-003: MyBikeTraffic per-ride CSV export is the primary ingest; FIT is secondary
- **Date:** 2026-10-28
- **Status:** accepted (supersedes ADR-001)
- **Context:** When logged in, MyBikeTraffic offers a per-ride **Export (CSV)**: one row per detected car pass with precomputed abs/rel speeds, ranges, rider speed, lat/long, and timestamps. ADR-001 assumed no export existed. MBT's pass detection is already tuned (thresholds, false-negative handling, disabled-radar handling).
- **Decision:** Ingest MBT per-ride CSVs as the primary path and trust MBT's pass list. No pass detection in the CSV path. FIT ingest (developer fields + our own detector) becomes a secondary/fallback path for rides not on MBT. It is optional, M4+.
- **Alternatives:** FIT-only (duplicates MBT's work, and units are unverified). Scraping MBT (ToS risk, not allowed without permission).
- **Consequences:** The column mapping must be versioned (`mbt_csv_v1`), and unknown/missing columns fail loudly. Units are inferred from data and marked `TODO(verify)` until the maintainer confirms. Download is user-driven, one ride at a time, until bulk automation (feature 004) is approved by the MBT maintainer. The CSV has no per-second track, so exposure (time on segment) needs the ride GPX/FIT or a Strava stream. In MVP, use traversal-based exposure (see feature 002).

### ADR-004: Speed-limit source precedence is manual > state DOT > OSM > inferred
- **Date:** 2026-10-28
- **Status:** accepted
- **Context:** Tested on a real 122-pass Provo ride.
  - **OSM** (API v0.6 bbox): `maxspeed` coverage is 100% on motorway/trunk, 96% primary, 71% secondary, 38% tertiary, 29% residential, 11% unclassified. 64% of passes (78) got an OSM limit.
  - **UDOT** `Statewide_Speed_Limit` covers state routes only (US-89, SR-189, SR-265, SR-114, I-15). 33% of passes (40) got a UDOT limit, all of which also had OSM. There were 0 conflicts once matches were restricted to the same route.
  - A naive nearest-feature match produced false UDOT hits at cross streets and overpasses, e.g. a 70 mph I-15 limit applied to 500 West.
  - Total: 78 of 122 passes have a limit; 44 sit on untagged local roads.
- **Decision:**
  - Precedence: `manual > dot (UDOT Statewide_Speed_Limit; other states' DOT layers via config) > osm maxspeed > inferred`.
  - A DOT value applies only when the matched OSM way's `ref` includes the DOT route number, the match is within 25 m, and (optionally) the milepost falls inside Beg/End_MP.
  - Motorways are excluded as candidate ways for bikes.
  - Store every source's value per segment, flag disagreements over 5 mph for review, and record `limit_source`.
- **Alternatives:**
  - OSM only: weaker for reports.
  - UGRC Utah Roads `SPEED_LMT`: in the test bbox 91% of features read 25 mph, which looks defaulted. Keep it as an optional, low-priority source labelled `ugrc` that ranks below OSM.
  - USGS NTD: no speed-limit attribute found in the `Trans_RoadSegment` data dictionary.
  - HERE/TomTom: free tiers exist, but their caching and storage terms (HERE ≤30 days without cache headers; TomTom no derivative databases, delete within 90 days) conflict with storing limits per segment.
  - INRIX: enterprise license only.
- **Consequences:**
  - UDOT data carries a "for informational purposes, must be field verified, no warranty" disclaimer that reports must repeat.
  - Local streets need OSM edits (MapComplete maxspeed) or manual overrides. Jared can contribute missing tags back to OSM, which is ODbL-compatible.
  - UDOT sign points (`Signs/FeatureServer/3`, `LEGEND` = posted value) can be used to validate segment limits.

### ADR-005: Local hour and weekday come from the `local time of day` column
- **Date:** 2026-10-29
- **Status:** accepted
- **Context:** Scoring buckets need local hour and weekday. The export has three local-ish columns. Both Excel columns are serial-day floats, and the one named "local excel utc native" is really local time. A real export (2026-10-29) showed `local time of day` is `"YYYY-MM-DD HH:MM:SS TZ"`, e.g. `"2026-10-28 13:16:56 MDT"`.
- **Decision:** Parse the wall-clock time and abbreviation from `local time of day` for `local_hour`, `weekday` and `local_tz_abbr`. Ignore both Excel columns except for a cross-check (`tz_offset_mismatch` flag). A row with any other format fails the file.
- **Alternatives:** A timezone lookup from lat/long (`timezonefinder`): it adds a dependency and duplicates what MBT already computed. The Excel local column: misnamed and float-rounded. A configured fixed zone: wrong for rides in other states.
- **Consequences:** We trust MBT's timezone assignment. If MBT changes the format, imports fail loudly and the parser needs a new `source_format_version`.

### ADR-006: Project layout and tooling
- **Date:** 2026-10-29
- **Status:** accepted
- **Context:** The project lives in the `bike-radar/` folder of an unrelated repo (`jlroper99/CalculatorDemo`). The developer uses Windows 11 with WSL2 and Docker Desktop.
- **Decision:**
  - `bike-radar/api`: a Python 3.12 package `bikeradar` managed by `uv` with a committed `uv.lock`. Uses FastAPI, SQLAlchemy 2, GeoAlchemy2, psycopg 3, Alembic and pandas. Lint and types via ruff and mypy `--strict`; tests via pytest. The CLI uses argparse (no extra dependency).
  - `bike-radar/web`: Next.js 16, React 19, TypeScript 5.9, MapLibre GL 6, ESLint 9 (`eslint-config-next`'s plugins don't support ESLint 10 yet), Vitest 3, Playwright 1.63. Exact versions are pinned.
  - Development runs inside WSL2. `make` targets wrap uv, npm and docker compose. CI is GitHub Actions (`.github/workflows/bike-radar.yml`) with jobs api (PostGIS service), web (lint, types, unit, build, Playwright) and compose (build the images and upload the fixture through the API).
  - Integration tests use a separate `bikeradar_test` database. They skip without a database locally and are required in CI (`BIKERADAR_REQUIRE_DB=1`).
- **Alternatives:** Poetry or pip-tools (slower, more moving parts). Native Windows tooling (no `make`, and Valhalla has no Windows build). SQLite/SpatiaLite (ARCHITECTURE allows it, but it would mean two backends to maintain).
- **Consequences:** Contributors need WSL2, Docker Desktop, uv and Node 22. `make import PATH=...` overrides make's `PATH`, so that recipe calls the venv binaries by absolute path.

### ADR-007: Ingest semantics and schema additions (features/001)
- **Date:** 2026-10-29
- **Status:** accepted
- **Context:** Re-imports must be no-ops. Bad files must not leave half a ride. MBT may let the same ride be exported twice with different bytes.
- **Decision:**
  - One file is one transaction: any row error rejects the whole file.
  - Dedupe on the SHA-256 of the file bytes (no-op), then on `(started_at, ended_at, n_passes)` (reported as `possible_duplicate`). Replacing an existing ride needs an explicit `--replace` / `?replace=true`.
  - Quality flags are informational. Flagged passes are stored.
  - Schema additions to ARCHITECTURE's model: `rides.source_filename`, `rides.imported_at`, and an index on the content-dedupe columns. `passes.geom` is nullable (`bad_coords`).
- **Alternatives:** Skipping bad rows (silently loses data). Upserting on `(ride, car_no)` across files (MBT `car #` stability is unverified).
- **Consequences:** If MBT renumbers cars on reprocessing, `--replace` handles it. Content dedupe could, rarely, treat two distinct rides with identical bounds as twins; the message says how to override.

### ADR-008: Valhalla runs behind a compose profile until M2
- **Date:** 2026-10-29
- **Status:** accepted
- **Context:** Valhalla isn't needed until M2. Its first start downloads the Geofabrik Utah extract (~300 MB) and builds tiles (minutes, ~4 GB RAM). The developer wants all of Utah, not one county.
- **Decision:** `ghcr.io/valhalla/valhalla-scripted:3.9.1` under the `routing` compose profile (`make dev-routing`), with tiles in `./data/valhalla` (gitignored) built from `utah-latest.osm.pbf`. `make dev` starts only db, api and web.
- **Alternatives:** Always start it (slow first run for M0/M1). `gis-ops/docker-valhalla` (superseded by the official image).
- **Consequences:** The env options are `TODO(verify)` when M2 starts. CI doesn't build Valhalla tiles.

### ADR-009: Endpoint privacy masking is enforced server-side from M1
- **Date:** 2026-10-29
- **Status:** accepted
- **Context:** M1 already exposes pass locations (`GET /rides/{id}/passes`). Rides start and end near home or work. The privacy-zone editor comes in M3.
- **Decision:** The API withholds geometry (`geometry: null`, `location_masked: true`) for any pass within 300 m (`BIKERADAR_PRIVACY_ENDPOINT_RADIUS_M`) of the ride's first or last located pass. The stored data stays unmasked so stats remain correct. M3 adds privacy-zone polygons to the same server-side filter.
- **Alternatives:** Masking in the UI only (leaks through the API and exports). Deleting the points at import (biases segment stats).
- **Consequences:** Every endpoint or export that emits locations must go through `bikeradar.privacy`. M3 adds a test that covers every geometry-emitting route.

