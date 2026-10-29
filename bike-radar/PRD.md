# PRD: Bike Radar Danger Map

## Problem
Cyclists with Garmin Varia radars collect thousands of vehicle passes but can't easily see *which road stretches* have cars passing at dangerous speeds relative to the posted limit.

## Users
- **P1 (now):** Jared, a single rider evaluating his own routes.
- **P2 (later):** other Varia + MyBikeTraffic riders picking safer routes.
- **P3 (later):** advocates presenting evidence to police, city, or DOT.

## Goals (MVP)
- Import per-ride CSV exports from MyBikeTraffic (one row per car pass, passes precomputed by MBT).
- Normalize speeds and ranges to SI, keeping every pass (including same-second platoon passes).
- Secondary (later): Garmin FIT import for rides not on MBT, and track data for exposure.
- Match passes to OSM road segments with posted speed limits.
- Rank segments by a transparent Danger Score. Show it on a map and in a table.

## Non-goals (MVP)
Multi-user accounts, a public map, a mobile app, lateral passing distance, our own pass detection (MBT already does it), scraping or automated MBT downloads without the maintainer's permission.

## Success metrics
- Import 100 ride CSVs in under 1 minute locally.
- ≥95% of passes matched to a road way with a limit (OSM, inferred, or manual).
- Top-10 list matches the rider's intuition (qualitative check).

## Constraints
Radar speeds are uncalibrated (relative speeds in 3 m/s buckets). CSV units are inferred, not documented. MBT CSV export is manual and one ride at a time. Speed-limit data is patchy. Privacy: the home location must never appear in exports.
