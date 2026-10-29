---
id: 004
title: Bulk import (watched folder; official MBT export only with permission)
status: draft   # placeholder; do not build before M5
milestone: M5
depends_on: [001]
---

# 004: Bulk import

## Goal
Importing many rides takes no per-file clicks.

## Scope
- **In:** `bikeradar watch DIR` polls or uses filesystem events, imports new `*.csv`/`*.fit` through the
  001/005 importers, and moves each file to `imported/` or `failed/`.
  Works on a folder the rider fills by hand, for example a browser download folder.
- **Conditional:** an official MBT bulk export or API, **only** if the maintainer (Dr. Brian Toone) offers or
  approves one. Its format would get its own `source_format_version`.
- **Out:** scraping, headless-browser automation, or reusing session cookies against
  mybiketraffic.com. Not without the maintainer's written permission (AGENTS.md hard rule).

## Open questions
- The maintainer's answer to the ROADMAP M1 email.
- Garmin Connect bulk export (a zip of FIT files) as an alternative path via 005.
