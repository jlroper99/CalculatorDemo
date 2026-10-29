---
id: 001
title: MBT per-ride CSV ingest (mbt_csv_v1)
status: draft   # drafted by the coding agent from the build prompt; set to `ready` once approved
milestone: M1
depends_on: []
---

# 001: MBT per-ride CSV ingest

## Goal
Import the per-ride CSV that the rider downloads from MyBikeTraffic (logged in → ride → Export) into
`rides` + `passes`, normalized to SI, with every pass kept and re-imports being no-ops.

## Scope
- **In:** header validation, column mapping to SI, local time derivation, quality flags, file and
  content dedupe, CLI `bikeradar import <file|dir>`, `POST /rides/upload`, `GET /rides`, `GET /rides/{id}/passes`.
- **Out:** pass detection (MBT already did it, ADR-003), map matching (002), speed limits (002),
  scoring (003), FIT/GPX (005), any automated download from MBT (004; never without the maintainer's permission).

## Input format `mbt_csv_v1`
One file = one ride. One row = one car pass, already detected by MBT. The exact header, in order:

```
"car #","utc timestamp","utc excel native","local excel utc native","local time of day",lat,long,avgspdabs,maxspdabs,pass_spdabs,maxspdrel,approachspdrel,passspdrel,slowdown,pass_radarcnt,approach_spdabs,approach_range,closest_range,approach_radarcnt,passlength,avgriderspd
```

## Column mapping

Units were inferred from two real rides near Provo UT on 2026-10-28 (122 and 66 passes); see
"Verified on real exports" below. The account is set to **imperial**, yet the CSV is in m/s and m, so the
display setting does not change export units. Still `TODO(verify)` with the MBT maintainer for metric accounts.

| CSV column | `passes` column | Type | Unit in CSV | Conversion | Notes |
|---|---|---|---|---|---|
| `car #` | `car_no` | int | — | none | Pass key within a ride. Must be unique per file |
| `utc timestamp` | `ts_utc` | timestamptz | epoch seconds, UTC | `to_datetime(unit="s", utc=True)` | **Not unique**: platoons share a second |
| `utc excel native` | — | — | Excel serial days | ignored | Redundant with `utc timestamp` |
| `local excel utc native` | — | — | Excel serial days, **local** time despite the name | ignored | Used only in the `tz_offset_mismatch` check |
| `local time of day` | `local_tz_abbr`, `local_hour`, `weekday` | text | quoted `"YYYY-MM-DD HH:MM:SS TZ"`, e.g. `"2026-10-28 13:16:56 MDT"` | parse wall time + abbreviation | Verified format. Parse failure = file fails |
| `lat` | `geom` (Y) | POINT 4326 | degrees | none | |
| `long` | `geom` (X) | POINT 4326 | degrees | none | |
| `avgspdabs` | `avg_abs_mps` | float | m/s | none | Absolute car speed, averaged over the track |
| `maxspdabs` | `max_abs_mps` | float | m/s | none | **Primary danger speed**. ≈ `maxspdrel + rider speed`, so it is not always ≥ `avgspdabs`/`pass_spdabs` |
| `pass_spdabs` | `pass_abs_mps` | float | m/s | none | Secondary danger speed. ≈ `passspdrel + rider speed` |
| `maxspdrel` | `max_rel_mps` | float | m/s | none | 3 m/s Varia buckets |
| `approachspdrel` | `approach_rel_mps` | float | m/s | none | 3 m/s buckets |
| `passspdrel` | `pass_rel_mps` | float | m/s | none | 3 m/s buckets |
| `slowdown` | `slowdown_mps` | float | m/s | none | Verified: `approachspdrel − passspdrel`. Can be negative |
| `pass_radarcnt` | `pass_radar_count` | int | count | none | |
| `approach_spdabs` | `approach_abs_mps` | float | m/s | none | `approach_spdabs − avgriderspd ≈ approachspdrel` |
| `approach_range` | `approach_range_m` | float | m, longitudinal | none | Varia max ≈ 140 m |
| `closest_range` | `closest_range_m` | float | m, longitudinal | none | 3 m buckets; 0 is common and normal. **Not** lateral passing distance |
| `approach_radarcnt` | `approach_radar_count` | int | count | none | |
| `passlength` | `track_seconds` | float | s | none | How long the radar tracked the car |
| `avgriderspd` | `rider_mps` | float | m/s | none | |

Today every conversion is the identity, because the CSV is already SI. The mapping still goes through
one `UNIT_SCALE` table in the code, so that if the maintainer confirms different units (or an imperial
variant turns up) only that table changes, plus a new `source_format_version`.

### Derived fields
- `local_hour` (0–23), `weekday` (0 = Monday … 6 = Sunday) and `local_tz_abbr`: parsed from the
  wall-clock time in `local time of day`. No timezone lookup and no new dependency. Both Excel columns are
  ignored except in the `tz_offset_mismatch` cross-check.
- Ride level: `started_at = min(ts_utc)`, `ended_at = max(ts_utc)`, `n_passes`,
  `source = mbt_csv`, `source_format_version = mbt_csv_v1`, `source_file_hash = sha256(file bytes)`,
  `has_track = false`.

## Rules
1. **Header validation:** strip a UTF-8 BOM and parse the first row with the `csv` module. The column list
   must equal the `mbt_csv_v1` list exactly (names and order). On any drift, raise `HeaderDriftError`
   with a readable diff (missing / unexpected / reordered) and write nothing. Never guess columns.
2. **Row validation:** every required value parses as its type. A row that fails parsing makes the
   whole file fail, naming its line number. A partial import never happens.
3. **Duplicate `car #` within one file:** this is a hard error, since the key would be ambiguous.
4. **Same-second passes are kept.** Key on `(ride_id, car_no)`, never on the timestamp.
5. **File dedupe:** if `source_file_hash` already exists, the import is a no-op that returns
   `status: duplicate` and the existing `ride_id`.
6. **Content dedupe:** a different file whose `(started_at, ended_at, n_passes)` matches an existing
   `mbt_csv` ride is skipped as `possible_duplicate` (for example the same ride re-exported after MBT
   reprocessing). `--replace` (CLI) or `?replace=true` (API) deletes the old ride and imports the new one.
   Deleting data needs the explicit flag (AGENTS.md).
7. **Transactions:** one ride is written in one transaction. In a directory import each file stands alone,
   and one bad file doesn't stop the rest. The summary lists imported / duplicate / possible_duplicate / failed.
8. **Quality flags** (`passes.quality_flags text[]`) are informational. A flagged pass is still stored:

   | Flag | Condition |
   |---|---|
   | `zero_rel_speed` | `max_rel_mps == 0` or `approach_rel_mps == 0` (for example a Rearvue 820 reporting 0) |
   | `zero_range` | `approach_range_m == 0`. A `closest_range` of 0 is normal (3 m buckets, 26% of real passes) and is **not** flagged |
   | `implausible_speed` | `max_abs_mps > 45` (≈ 100 mph) or any absolute speed < 0. Threshold in config |
   | `rel_not_bucketed` | a relative speed that isn't a multiple of 3 m/s |
   | `slowdown_mismatch` | `abs(slowdown − (approachspdrel − passspdrel)) > 0.01` |
   | `approach_identity_off` | `abs((approach_spdabs − avgriderspd) − approachspdrel) > 3` (one bucket) |
   | `range_exceeds_radar` | a range over 150 m |
   | `bad_coords` | lat/long missing, `0,0`, or out of range |
   | `tz_offset_mismatch` | `local time of day` − `ts_utc` differs from `(local excel − utc excel)·24` by more than 0.25 h |

   A ride where every pass has `zero_rel_speed` is also flagged on `rides.notes`.
9. **Privacy:** real exports are never committed. `.gitignore` blocks `*.csv` and `*.fit` outside
   `fixtures/` and `tests/fixtures/`. Imports read from wherever the user points; uploaded files are
   parsed in memory and not kept on disk.

## Verified on real exports (2026-10-29, 66-pass ride, imperial account)
- The header matches `mbt_csv_v1` exactly. LF line endings, no BOM.
- `slowdown = approachspdrel − passspdrel` on 66/66 rows. It is negative on 6 rows.
- `approach_spdabs − avgriderspd − approachspdrel`: mean −0.03, max |0.65| m/s.
  The same holds for `maxspdabs`/`maxspdrel` and `pass_spdabs`/`passspdrel` (sd ≈ 0.2).
  **So absolute speeds are a 3 m/s relative bucket plus rider speed, with ±1.5 m/s (±3.4 mph) resolution.**
- All relative speeds and `closest_range` are multiples of 3. `approach_range` is an integer in m, with max 140 (the Varia limit).
- `passlength` is an integer in s (2–26). Rider speed median 8.0 m/s (18 mph), which is plausible, so speeds are m/s and not mph.
- `utc excel native` matches the epoch to under 1 ms. `utc − local excel` = 6.0 h (MDT).
- This ride has no same-second passes (the 2026-10-28 ride had 13), so the fixture keeps that case.

## Interfaces
- **CLI:** `bikeradar import PATH [--replace] [--json]`. A directory means a non-recursive import of every `*.csv`.
  The exit code is non-zero if any file failed.
  `make import PATH=...` wraps it.
- **API:** `POST /rides/upload` (multipart, one or more files) returns one result per file:
  `{filename, status, ride_id, n_passes, flags_summary, error}`.
  `GET /rides`, `GET /rides/{id}`, `GET /rides/{id}/passes` (GeoJSON).
- **Library:** `bikeradar.ingest.mbt_csv.parse(bytes) -> ParsedRide` is pure, with no DB access, and is unit-tested.

## Acceptance criteria
- [ ] `fixtures/mbt_export_synthetic.csv` imports as 1 ride with 4 passes.
- [ ] Cars 2 and 3 share `utc timestamp` 1793193397 and both are stored.
- [ ] Re-importing the same file is a no-op (ride and pass counts unchanged; returns `duplicate`).
- [ ] Renaming, dropping, adding or reordering any header column is rejected with `HeaderDriftError`, and nothing is written.
- [ ] Unit mapping: car 1 has `max_abs_mps == 18.1`, `ts_utc == 2026-10-28T13:15:02Z`, `local_hour == 7`,
      `local_tz_abbr == "MDT"`, `weekday == 2` (Wednesday), `closest_range_m == 3`, `track_seconds == 7`.
- [ ] No fixture pass has a quality flag. Car 3's `closest_range == 0` is not flagged.
      Each flag is tested with a small inline CSV.
- [ ] CLI directory import and the upload endpoint return the per-file summary described above.
- [ ] An API integration test against PostGIS passes in CI.

## Tests
- `tests/unit/test_mbt_csv_parse.py`: header (exact, BOM, each kind of drift), types, duplicate `car #`,
  the conversions above, local hour and weekday, and each quality flag (small inline CSVs built from the fixture).
- `tests/integration/test_import.py` (PostGIS): import, re-import no-op, content dedupe and `--replace`,
  same-second passes, and the upload endpoint.

## Open questions
1. Units: confirm with the MBT maintainer (ROADMAP M1 email), especially for metric accounts. `TODO(verify)`
2. Does MBT ever renumber `car #` when a ride is reprocessed? This affects rule 6. `TODO(verify)`
3. Is `local time of day` ever in a format other than `YYYY-MM-DD HH:MM:SS TZ`, for example for rides outside the US? `TODO(verify)`

## ADRs
- ADR-005: local time comes from `local time of day`, not the Excel columns and not a timezone lookup.
- ADR-006: scaffold and tooling choices (made at M0).
