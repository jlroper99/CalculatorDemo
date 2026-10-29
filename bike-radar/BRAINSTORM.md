# Bike Radar Danger Map: Brainstorm

## What we know about the data (verified 2026-10-28)
- **MyBikeTraffic (MBT)** is a free, donation-funded hobby project (Dr. Brian Toone, Samford University). It runs as a Garmin Connect IQ **data field** that writes radar data into the ride's FIT file. Rides get to MBT through a manual FIT upload or Garmin Connect auto-sync. It can also post summaries to Strava. The Cadence app (iOS/Android) is supported too.
- **MBT has no documented public API or OAuth.** The public /data page says the site-wide raw-pass CSV export is disabled. **However, logged-in users can export each ride as a CSV** (see below).
- **The FIT file is the secondary source.** The open-source data field (github.com/kartoone/mybiketraffic, `MyBikeTrafficFitContributions.mc`) writes these Connect IQ developer fields:
  - `radar_ranges` (record, sint16 x8): ranges to up to 8 tracked vehicles
  - `radar_speeds` (record, uint8 x8): speeds of those targets (Varia speeds are **relative** to the rider)
  - `radar_current` (record, uint16): running vehicle count
  - `radar_total` (session) / `radar_lap` (lap): counts
  - `passing_speed` (record, uint8): relative speed of the closest car, in device units
  - `passing_speedabs` (record, uint8): relative speed + rider speed = absolute speed, in device units
- MBT's pass-detection method is public: a vehicle counts once the closest target is within 10 m, or when range < relative speed (about 1 s to pass). Count it when the visible-target count drops. Treat speeds as coarse "buckets", not calibrated measurements.
- Garmin's native Varia FIT records may also contain radar data without the CIQ field. **Unverified.** Inspect real files.
- The Rearvue 820 reports speed 0 on older devices and must be paired over ANT+. Flag rides with all-zero speeds.

**Bottom line (updated 2026-10-28):** MBT has a **logged-in, per-ride Export (CSV)**, confirmed by Jared. It isn't in the public docs. Each row is one detected car pass, already reconstructed by MBT. It includes:
- abs speeds (avg/max/pass/approach)
- rel speeds (max/approach/pass)
- slowdown
- radar counts
- approach/closest range
- pass length
- rider speed
- lat/long
- timestamps

That makes it the **primary ingest path**, with no pass detection needed. FIT files are a secondary path for non-MBT rides and for a per-second track (exposure).

Findings from one sample ride (122 passes over 64 min, Provo UT area):
- Units are inferred: abs and rel speeds in **m/s**. Evidence: `approach_spdabs − avgriderspd ≈ approachspdrel`, r = 0.98, residual ≈ 0. Rel speeds come in 3 m/s Varia buckets (3–21).
- Ranges are in meters (max 143 ≈ Varia's 140 m), longitudinal only. `passlength` is in seconds.
- 13 timestamps are shared by 2–3 cars (e.g. cars 10/11): real platoons, so key on car #.
- The column named "local excel utc native" is actually local time.

Bulk download is a later feature (features/004): user-driven or watched folder, or an official export if the maintainer agrees. No scraping without permission.

## Speed-limit test (sample ride, 2026-10-28)
122 passes near Provo, UT:
- OSM gave a limit for 78 passes (64%). UDOT gave one for 40 (33%, all also in OSM) with 0 conflicts after route-ref matching. 44 passes were on untagged local roads (920 South, Canyon Road, Freedom Blvd, …).
- 34 of the 78 limited passes peaked above the limit, and 2 exceeded it by more than 10 mph.
- Top roads by passes over the limit: University Ave (US-189, 35–40 mph) 11/27; 500 West (25–30 per OSM) 7/16; Campus Drive (25) 7/11; West Campus Drive (15) 5/5. Lakeview Parkway peaked at 54 mph (limit 45) but had only 1 over.
- Lesson: naive nearest-feature matching produced false DOT limits on cross streets and overpasses. Require a route-ref match.

## Data sources
| Need | Source | Notes |
|---|---|---|
| Car passes | **MBT per-ride CSV export** (logged in) | **Primary**: precomputed passes |
| Radar + GPS track | Garmin FIT (fitdecode / Garmin FIT SDK) | Secondary: non-MBT rides, exposure track |
| Bulk rides | Garmin Connect bulk export, Garmin Health/Activity API (needs a partner application) | Later |
| Segments | Strava API v3 (`/segments/{id}`, `/segments/explore`, activity `segment_efforts`) | OAuth. Default limits are about 200 req/15 min and 2,000/day. Terms bar most redistribution and AI training use, so keep Strava data per-user and don't publish it |
| Own segments | OSM ways split at intersections | Recommended canonical unit |
| Speed limits | OSM `maxspeed` via a Geofabrik extract / Overpass / MapComplete | Free (ODbL). Tested near Provo: 100% trunk, 96% primary, 71% secondary, 38% tertiary, 29% residential tagged |
| Speed limits (paid) | HERE Maps (speed limits in routing/map attributes), TomTom (Snap to Roads / speed-limit data), Mapbox map matching `maxspeed` annotation | Check license terms for storing results |
| Authoritative (UT) | UDOT `Statewide_Speed_Limit` FeatureServer: https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/Statewide_Speed_Limit/FeatureServer/0 ; speed-limit signs: https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/Signs/FeatureServer/3 | State routes only. Verified working 2026-10-28. UDOT disclaimer: informational, field-verify |
| Other states | State DOT ArcGIS/HPMS layers (also AADT: `https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/AADT2024_Unrounded/FeatureServer`) | Config-driven |
| Weak | UGRC Utah Roads `SPEED_LMT` (looks defaulted to 25); USGS NTD (no speed field found) | Low priority |
| Commercial | HERE (free tier 1,000 req/day, cache ≤30 days), TomTom (2,500/day; no derivative DBs, delete within 90 days), INRIX (enterprise) | Storage terms conflict with a segment DB |
| Crashes | State DOT crash data, NHTSA FARS | Context layer |
| Map matching | Valhalla `trace_attributes` (self-host, returns OSM way IDs + speed limits), OSRM `match`, Mapbox, Barefoot | Valhalla recommended |

## Features by phase
### Phase 1: MVP (personal)
- Import MBT per-ride CSV exports (drag-drop or watch a folder). Passes are precomputed
- Optional FIT/GPX for the ride track (exposure) and for rides not on MBT
- Map-match to OSM ways. Attach maxspeed (source: osm / inferred / dot / manual)
- Per-segment stats and a danger score. Ranked table plus a color-coded map
- Ride detail: a timeline of passes and a speed-vs-limit chart
- Manual speed-limit override per way

### Phase 2: Enhanced analytics
- Time-of-day / day-of-week heatmaps, weekday vs weekend
- Confidence intervals per segment (sample size, Bayesian shrinkage)
- Trend over time (did a road get worse after a change?)
- Route comparison: "this alternate route has 60% fewer 50+ mph passes"
- Strava segment overlay. Garmin Connect auto-import
- Weather and daylight context (sunrise/sunset)
- Platoon detection (bursts of cars), counts of trucks vs cars (not possible: radar has no vehicle class)

### Phase 3: Multi-user / public
- Accounts, per-user data isolation, privacy zones
- Aggregated public map (k-anonymity: show a segment only with ≥N riders and ≥M passes)
- Safer-route suggestions (export a GPX, or a routing cost layer for BRouter/GraphHopper)
- Integrations: Strava OAuth, Garmin partner API, an MBT partnership (if offered)

### Phase 4: Advocacy reports
- PDF/HTML report per road or corridor: map, pass counts, % over limit, 85th-percentile speed, time-of-day peaks, sample size, methodology, and caveats
- Exhibits for city council / police traffic units / DOT (with a "radar is uncalibrated" disclaimer)
- A CSV appendix with fuzzed timestamps and locations
- Before/after comparisons for enforcement or road diets

## Danger metrics (per segment, per time bucket)
- **Passes per hour** of riding on the segment (exposure-normalized)
- **Absolute passing speed**: median, p85, max
- **Speed over limit**: mean(abs − limit), **% passes over limit**, **% over limit +10 mph**
- **Speed differential vs rider** (relative speed): kinetic-energy proxy ∝ v_rel²
- **Close-pass proxy:** the Varia measures *longitudinal* range only, not lateral distance. Proxies: high-speed passes during platoons, or passes on roads with no shoulder (OSM/DOT). Real lateral distance needs other hardware (MBT/Ploughshare work in progress)
- **Severity-weighted score** (pedestrian fatality risk rises steeply above about 30–40 mph):
  `risk = Σ w(v_abs) · (1 + max(0, v_abs − limit)/10)` per km ridden, where `w` is a logistic impact-severity curve
- **Composite Danger Score (0–100):** percentile-ranked blend of exposure, p85 overspeed, %>limit+10, and road context (lanes, shoulder, AADT), weighted down when the sample size is small
- Time-of-day risk: the same metrics bucketed by hour

## Visualization ideas
- Map with segments colored by score, line width by traffic volume, click for a stats card
- Point cloud of individual passes colored by overspeed
- Ride "strip chart": distance vs pass speed with the speed limit as a step line
- Hour × weekday heatmap for a segment
- Top-10 dangerous segments leaderboard. "Roads to avoid" vs "hidden gems"
- Histogram of passing speeds vs the limit for a report

## Privacy & legal
- Fuzz start/end points: drop the first and last 200–500 m and honor privacy zones (home/work). Snap to a coarse grid for public views
- Don't publish timestamps finer than hour + weekday on public layers
- Respect the terms of service: MBT (no documented API, so don't scrape without permission), Strava API Agreement (no redistribution of other users' data, display/attribution rules), Garmin developer terms, OSM ODbL (attribution, share-alike for derived databases), and HERE/TomTom storage restrictions
- Radar speeds are uncalibrated estimates. Reports must say so and must not identify individual drivers
- Multi-user: GDPR/CCPA (consent, export, delete), encryption at rest, and data minimization
- Liability: route suggestions are advisory only

## Open questions
1. Confirm CSV units with the MBT maintainer. Does an imperial account setting change them? Is there a bulk export?
1b. Does every rider's FIT include the MBT developer fields, or only CIQ users? How does native Varia data appear in FIT?
2. Units of `radar_speeds` (m/s?) vs `passing_speed*` (device units: km/h or mph?). Check against real files and the MBT site
3. Would the MBT maintainer offer an export or API, or partner with us?
4. Which state DOT? (Speed-limit layer availability varies)
5. Minimum sample size for a "reliable" segment?
6. Segment unit: OSM way vs fixed 200 m bins vs Strava segments?
7. Hosting / monetization for the public version (donation-funded like MBT?)
