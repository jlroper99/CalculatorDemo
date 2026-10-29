# Roadmap

## M0: Scaffold
- [ ] Repo, docker-compose (postgis, valhalla, api, web), Makefile, CI, `make check`
- [ ] ADR-002 stack confirmed; ADR-003 (MBT CSV primary) in place

## M1: MBT CSV ingest (features/001)
- [ ] `mbt_csv_v1` parser + header validation + SI normalization
- [ ] CLI `bikeradar import <path|dir>` + upload endpoint, dedupe by hash and (ride, car_no)
- [ ] Synthetic fixture tests (same-second passes kept)
- [ ] Email the MBT maintainer to confirm units and ask about bulk export/API

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
