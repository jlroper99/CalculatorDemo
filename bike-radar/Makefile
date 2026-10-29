# Bike Radar Danger Map. Run from WSL2 (Ubuntu) with Docker Desktop; see README.md.
#
# `make import PATH=<file|dir>` is the documented interface. PATH given on the command line
# replaces make's own PATH, so recipes that need it call tools by absolute path.

SHELL := /bin/bash
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VENV_BIN := $(ROOT)/api/.venv/bin

ifeq ($(origin PATH),command line)
IMPORT_TARGET := $(PATH)
endif
IMPORT_TARGET ?= $(FILE)

-include $(ROOT)/.env
ifneq ($(BIKERADAR_DATABASE_URL),)
export BIKERADAR_DATABASE_URL
endif
ifneq ($(BIKERADAR_TEST_DATABASE_URL),)
export BIKERADAR_TEST_DATABASE_URL
endif

.PHONY: help setup dev dev-routing down db-up migrate import check check-api check-web e2e fmt

help:
	@echo "make setup            install Python (uv) and web (npm) dependencies"
	@echo "make dev              start db + api + web (http://localhost:3000, API http://localhost:8000/docs)"
	@echo "make dev-routing      same, plus Valhalla (M2; first run builds Utah tiles)"
	@echo "make down             stop the stack"
	@echo "make db-up            start only the database"
	@echo "make migrate          apply database migrations"
	@echo "make import PATH=...  import an MBT CSV export or a folder of them"
	@echo "make check            lint, format check, types and tests (api + web)"
	@echo "make e2e              Playwright smoke test (builds the web app)"
	@echo "make fmt              auto-format and fix lint"

setup:
	cd api && uv sync
	cd web && npm ci

dev:
	docker compose up --build

dev-routing:
	docker compose --profile routing up --build

down:
	docker compose --profile routing down

db-up:
	docker compose up -d --wait db

migrate:
	cd api && uv run alembic upgrade head

import:
	@if [ -z "$(IMPORT_TARGET)" ]; then echo "usage: make import PATH=<file-or-directory>"; exit 2; fi
	@if [ ! -x "$(VENV_BIN)/bikeradar" ]; then echo "run 'make setup' first"; exit 2; fi
	cd "$(ROOT)/api" && "$(VENV_BIN)/alembic" upgrade head && "$(VENV_BIN)/bikeradar" import "$(abspath $(IMPORT_TARGET))"

check: check-api check-web

check-api:
	cd api && uv run ruff check .
	cd api && uv run ruff format --check .
	cd api && uv run mypy
	cd api && uv run pytest

check-web:
	cd web && npm run lint
	cd web && npm run typecheck
	cd web && npm test

e2e:
	cd web && npm run build && npx playwright test

fmt:
	cd api && uv run ruff check --fix . && uv run ruff format .
