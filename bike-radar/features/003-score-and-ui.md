---
id: 003
title: Segment Danger Score + UI + privacy masking
status: draft   # drafted by the coding agent from the build prompt; outline only, refine before M3
milestone: M3
depends_on: [001, 002]
---

# 003: Danger Score and UI

## Goal
A ranked, transparent per-segment Danger Score, shown on a map and in a table, with the
rider's private locations never displayed.

## Scoring (per way; per hour-of-day bucket too)
The speed basis is `max_abs_mps` (`pass_abs_mps` is shown as secondary). For segments with `n_passes ≥ n_min` (10):

| Component | Definition |
|---|---|
| `rate` | passes per traversal km (passes per hour once track exposure exists, 005) |
| `p50/p85/max` | of `max_abs` |
| `overspeed_p85` | p85(max_abs) − limit |
| `pct_over` | share of passes with max_abs > limit |
| `pct_over10` | share of passes with max_abs > limit + 10 mph |
| `severity` | mean of logistic((v_kph − 50) / 8) |

1. Percentile-rank each of `rate`, `overspeed_p85`, `pct_over10` and `severity` across eligible segments (0–1).
2. `raw = 100 · (0.25·rate + 0.30·overspeed + 0.25·pct_over10 + 0.20·severity)`. Weights, `n_min`, `k` and the
   logistic constants live in `config/scoring.yaml`. A config hash is stored with each computation.
3. Bayesian shrinkage: `score = (n·raw + k·prior)/(n + k)` with `k = 20`, where `prior` is the
   mean `raw` of eligible segments. `TODO(decide)`: the mean or the median.
4. `n < 10` gives `insufficient_data` with no score, but the components are still shown.
5. Every component, rank, the raw and shrunk score, `n_passes`, `n_rides` and the config hash are stored.
   This needs a schema ADR, because ARCHITECTURE's `segment_stats` lists a subset.
6. Deterministic: the same inputs and config give byte-identical stats (reproducibility test).
   Recomputation happens only for the ways an import touches.

## UI (Next.js + MapLibre + Recharts)
- Map: segments colored by score (grey = insufficient data), plus a toggleable pass-point layer colored by overspeed.
- A "Most dangerous segments" table, sortable by every component.
- Segment card: a histogram of `max_abs` with a limit line and a limit+10 line, an hour-of-day heatmap, the limit source, and conflict flags.
- Ride detail: time vs passing speed with the limit as a step line.
- Import page: drag-drop of CSVs that calls `POST /rides/upload`, showing per-file results.
- Privacy-zone editor (draw or delete polygons).
- mph / km/h toggle (stored in SI, converted only in the UI).
- Footer and reports carry the disclaimer: radar is uncalibrated, and UDOT data is informational.

## Privacy
- The API never returns pass points or traversal geometry inside a `privacy_zones` polygon or within
  300 m of a ride's first or last pass. Masking happens server-side, in the API layer and exports, not only in the UI.
- Masked passes still count toward segment stats, but their points are never emitted.

## Acceptance criteria
- [ ] Score reproducibility test on a fixed synthetic dataset.
- [ ] Privacy masking tests: in-zone, the 300 m start/end buffer, and the export path.
- [ ] Playwright smoke test: the map loads and the table renders.
