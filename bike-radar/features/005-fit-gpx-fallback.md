---
id: 005
title: FIT/GPX track attach + FIT pass detector (fallback)
status: draft   # placeholder; do not build before M4
milestone: M4
depends_on: [001, 002]
---

# 005: FIT/GPX fallback

## Goal
(a) Attach a ride's FIT or GPX track to an MBT CSV ride for true time-on-segment exposure.
(b) Import rides that aren't on MBT by detecting passes from the MBT Connect IQ developer fields.

## Track attach
- Parse with `fitdecode` (FIT) or `gpxpy` (GPX) into `track_points(ride_id, ts, geom, rider_mps)`, and set `rides.has_track`.
- Auto-link to an existing CSV ride when the track covers `[started_at, ended_at]` and the pass points
  lie within 30 m of the track at their timestamps. Otherwise link manually.
- Exposure becomes `exposure_source = track`, with `seconds` = time on each matched way, so `rate` becomes passes per hour.

## FIT pass detector (`source = fit`)
- Developer fields (from the open-source MBT data field): `radar_ranges` (sint16×8), `radar_speeds` (uint8×8, relative),
  `radar_current` (uint16), `passing_speed` and `passing_speedabs` (uint8, device units `TODO(verify)`).
- MBT-style detection: a vehicle counts once the closest target is within 10 m, or when range < relative speed
  (about 1 s to pass), and is counted when the visible-target count drops. Output follows the same `passes`
  schema; fields that can't be derived are NULL.
- Validation: run on a FIT whose MBT CSV is also available, and require pass counts within ±5% `TODO(verify)`.
- Flag rides with all-zero speeds (a Rearvue 820 on an older device).

## Open questions
- Do native Garmin Varia FIT records carry radar data without the CIQ field? Inspect real files.
- Units of `radar_speeds` vs `passing_speed*`.
