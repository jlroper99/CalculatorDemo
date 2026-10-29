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
- **Status:** proposed
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
