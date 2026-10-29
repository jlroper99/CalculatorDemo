# Roadmap

## M0: Scaffold
- [x] Repo, docker-compose (postgis, valhalla, api, web), Makefile, CI, `make check`
- [x] ADR-002 stack confirmed; ADR-003 (MBT CSV primary) in place

## M1: MBT CSV ingest (features/001)
- [x] `mbt_csv_v1` parser + header validation + SI normalization
- [x] CLI `bikeradar import <path|dir>` + upload endpoint, dedupe by hash and (ride, car_no)
- [x] Synthetic fixture tests (same-second passes kept)
- [ ] Email the MBT maintainer to confirm units and ask about bulk export/API (draft: `docs/mbt-maintainer-email.md`; Jared sends)

### Follow-ups from M0/M1
- [ ] `bikeradar verify-export <file>`: print the unit and identity checks from features/001 for a new export without importing it
- [ ] Decide the overspeed tolerance band for 3 m/s speed buckets (features/003, before M3)
- [ ] Pin the Valhalla env options when M2 starts (ADR-008)

## M2: Roads & limits (features/002)
- [ ] Valhalla matching of pass points
- [ ] Speed limit enrichment (manual > dot > osm > inferred) + override endpoint
- [ ] Traversal-based exposure

## M3: Score & UI (features/003)
- [ ] Segment aggregation + Danger Score
- [ ] Map + ranked table + ride detail; privacy zones masked

## M4: Analytics + FIT fallback (features/005)
- [ ] FIT/GPX track attach for true exposure; FIT pass detector for non-MBT rides
- [ ] Time-of-day heatmaps, confidence intervals, trends, route comparison, Strava overlay

## M5: Multi-user + bulk import (features/004)
- [ ] Watched-folder bulk import; official MBT bulk export if the maintainer offers one (no scraping without permission)
- [ ] Auth, per-user isolation, k-anonymous public map

## M6: Advocacy
- [ ] Corridor report PDF with methodology + caveats
