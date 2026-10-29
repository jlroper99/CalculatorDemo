# Bike Radar Danger Map

Finds the road segments you ride where cars pass at dangerous speeds compared with the posted
limit, using Garmin Varia radar data recorded by the MyBikeTraffic (MBT) Connect IQ data field.

Start with [`AGENTS.md`](AGENTS.md), [`PRD.md`](PRD.md), [`ARCHITECTURE.md`](ARCHITECTURE.md),
[`ROADMAP.md`](ROADMAP.md), [`DECISIONS.md`](DECISIONS.md) and [`features/`](features/).

**Status:** M0 (scaffold) and M1 (MBT CSV ingest, [features/001](features/001-mbt-csv-ingest.md))
are done. Map matching, speed limits and scoring come in M2–M3.

## One-time setup (Windows 11)

Everything runs inside WSL2 (Ubuntu). Keep the clone in the Linux filesystem (`~/...`), not
under `/mnt/c`, because file access and watching are much faster there.

1. In an admin PowerShell: `wsl --install -d Ubuntu-24.04`, then reboot and create your Ubuntu user.
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and enable
   *Settings → Resources → WSL integration* for Ubuntu.
3. In Ubuntu:

   ```bash
   sudo apt update && sudo apt install -y make git
   curl -LsSf https://astral.sh/uv/install.sh | sh   # Python tooling (installs Python 3.12 on demand)
   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
   git clone https://github.com/jlroper99/CalculatorDemo.git && cd CalculatorDemo/bike-radar
   cp .env.example .env
   make setup
   ```

## Everyday use

| Command | What it does |
|---|---|
| `make dev` | Starts PostGIS, the API (http://localhost:8000/docs) and the web app (http://localhost:3000) |
| `make import PATH=~/rides/123456.csv` | Imports one MBT export, or every `*.csv` in a folder. Re-imports are no-ops |
| `make check` | ruff, mypy, pytest, eslint, tsc, vitest (integration tests need `make db-up` or `make dev`) |
| `make e2e` | Playwright smoke test |
| `make dev-routing` | Also starts Valhalla (M2). The first run builds Utah tiles |

You can also upload through the API: `POST /rides/upload` (see http://localhost:8000/docs).

### Getting a ride CSV from MyBikeTraffic
Log in at mybiketraffic.com → open a ride → **Export (CSV)**. Download it yourself. The app never
downloads from MBT for you (AGENTS.md).

## Privacy

- **Never commit real exports.** `.gitignore` blocks `*.csv`, `*.fit` and `*.gpx` outside the
  fixture folders. Tests use [`fixtures/mbt_export_synthetic.csv`](fixtures/mbt_export_synthetic.csv).
- The API never returns a pass location within 300 m of a ride's first or last pass (ADR-009).

## Layout

```
api/        Python package `bikeradar` (FastAPI, SQLAlchemy, Alembic) + tests
web/        Next.js + MapLibre UI + Vitest + Playwright
fixtures/   Synthetic MBT export used by tests
features/   Feature specs (001 done; 002-005 drafts)
docs/       Supporting material (MBT maintainer email draft)
```
