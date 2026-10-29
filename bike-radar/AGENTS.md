# AGENTS.md: Rules for coding agents

## Read first, every session
1. `PRD.md` (what & why), `ARCHITECTURE.md` (how), `ROADMAP.md` (what's next), `DECISIONS.md` (why things are the way they are)
2. The active spec in `features/` (status: `in-progress` or the next `ready`)

## Workflow
- Work on **one feature spec at a time**. If there's no spec, write one from `features/TEMPLATE.md` and stop for review.
- Plan → implement smallest vertical slice → tests → update docs → commit.
- Tick the box in `ROADMAP.md` and set spec `status: done` only after its acceptance criteria pass.
- Any architectural choice (new dependency, schema change, external API) gets an ADR entry in `DECISIONS.md`.
- Keep commits small, using Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`).

## Hard rules
- **Never invent external API endpoints.** MyBikeTraffic has no documented API. Primary ingest is the user-downloaded per-ride CSV export (`mbt_csv_v1`). FIT is secondary. Never scrape or automate MBT without permission. Mark unverified assumptions `TODO(verify)`.
- Never commit real ride exports. Use `fixtures/mbt_export_synthetic.csv`.
- No secrets in code. Use `.env` + `.env.example`.
- Every new parser or metric needs unit tests with fixtures in `tests/fixtures/`.
- Don't commit real ride FIT files with home locations. Use synthetic or trimmed fixtures.
- Keep units explicit in names (`speed_mps`, `limit_kph`). Store SI, convert at the UI.
- Lint/format/test must pass: `make check`.
- Ask before deleting data, rewriting migrations, or adding a paid service.

## Done means
Tests green, docs updated, the feature demoable with `make dev`, and a short summary of what changed plus any follow-ups added to ROADMAP.
