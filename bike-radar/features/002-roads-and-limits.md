---
id: 002
title: Map matching, speed limits, traversal exposure
status: draft   # drafted by the coding agent from the build prompt; outline only, refine before M2
milestone: M2
depends_on: [001]
---

# 002: Roads, limits and exposure

## Goal
Every pass gets an OSM `way_id` and a posted limit, with a recorded source, and every way a ride
traversed gets exposure (traversal count and km).

## Scope
- **In:** Valhalla `trace_attributes` matching, a nearest-way fallback, `road_segments`,
  `segment_limits` (all sources), precedence resolution, DOT sources configurable per state,
  a manual override endpoint, flags for source disagreement, traversal exposure.
- **Out:** scoring (003), track-based exposure (005), HERE/TomTom (their storage terms forbid it, ADR-004).

## Map matching
1. Self-hosted Valhalla (docker-compose) with tiles built from Geofabrik `utah-latest.osm.pbf`.
   The extract URL is in config, so other states only change config.
2. For each ride, send the pass points in time order to `trace_attributes` with `shape_match=map_snap`,
   requesting `edge.way_id`, `edge.speed_limit`, `edge.road_class`, `edge.names`,
   `matched_point.edge_index` and `matched_point.distance_from_trace_point`. `TODO(verify)` the attribute
   filter names against the Valhalla version we pin.
3. Store `passes.way_id` and `passes.match_distance_m`. A match farther than 30 m (in config) is flagged
   `match_far`. Motorway ways are never candidates (bikes are prohibited).
4. Fallback when Valhalla fails or a match is unmatched: snap to the nearest PostGIS way within 30 m whose
   bearing is within 30° of the bearing between neighbouring passes. Fallback matches are flagged `match_fallback`.
5. Pass points are sparse (often minutes apart), so the edges between matched points come from Valhalla's
   inferred path. A gap of more than 2 km or 5 min between passes is matched as a separate trace and
   counts as a traversal with `low_confidence`.

## Speed limits (ADR-004)
Every source's value goes in `segment_limits(way_id, source, mph, source_ref, fetched_at)`.
The chosen value is denormalized onto `road_segments` (`maxspeed_kph`, `limit_source`).

| Rank | Source | How |
|---|---|---|
| 1 | `manual` | `PUT /segments/{way_id}/limit {mph, note}`; `DELETE` reverts |
| 2 | `dot` | `config/dot_sources.yaml`. Utah: UDOT `Statewide_Speed_Limit` FeatureServer/0 (`Route`, `Name`, `Direction`, `Beg_MP`, `End_MP`, `Speed_Limit` mph), envelope query with `f=geojson`, cached locally. Applied only if the OSM way `ref` contains the route number, the match is ≤ 25 m, and the way is not a motorway (optional milepost check) |
| 3 | `osm` | `maxspeed` from the extract. `"35 mph"` → 35 mph; a bare number is km/h; `none`, `signals`, `walk` and other non-numeric values → no value (logged) |
| 4 | `ugrc` | Optional, off by default (values look defaulted to 25) |
| 5 | `inferred` | `config/speed_defaults.yaml`: highway class → mph per state, e.g. UT residential 25 |

- Disagreement: when any two non-inferred sources differ by more than 5 mph, set `limit_conflict = true` and list the way in `GET /segments/limit-conflicts`.
- Validation: the UDOT Signs FeatureServer/3 (`LEGEND` = mph) feeds a report of DOT/OSM limits that disagree with a sign within 50 m on the same route.
- Utah defaults are `TODO(verify)` against Utah Code 41-6a-601.

## Exposure (MVP: traversal)
`segment_exposure(way_id, ride_id, seconds = NULL, meters, exposure_source = traversal)`: one row
per way a ride's matched path covers, with `meters` = the length of the way covered. Feature 005 adds
`exposure_source = track`, using time on segment.

## Acceptance criteria
- [ ] The synthetic fixture matches to University Ave (US-189) ways in a test tile set, or to mocked Valhalla responses in unit tests.
- [ ] `maxspeed` parsing: `"35 mph"`→35, `"50"`→31.07 mph (km/h), `"none"`→null, `"25 mph;35 mph"`→null + logged.
- [ ] DOT applies only with a route-ref match. A cross street within 25 m of I-15 does not get 70 mph.
- [ ] Precedence and the manual override work round-trip, and the conflict flag sets at > 5 mph.
- [ ] Exposure rows exist for every traversed way.

## Open questions
- Segment unit: OSM way, or way split at intersections (BRAINSTORM Q6)? Proposal: OSM way for MVP.
