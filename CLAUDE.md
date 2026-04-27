# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

LibrariArr is a media library synchronization service that bridges nested filesystem structures with flat Radarr/Sonarr library requirements using hardlink projection. It continuously reconciles managed media folders into curated library roots.

## Development Commands

All operations go through `./run.sh <command>`. Never run `python`, `pip`, `pytest`, `npm`, `docker compose`, etc. directly.

```bash
./run.sh install          # Build dev Docker image
./run.sh test             # Unit tests (excludes e2e markers)
./run.sh quality          # Ruff lint/format + frontend ESLint checks
./run.sh quality-autofix  # Auto-fix then re-check
./run.sh e2e              # Integration tests against live Radarr/Sonarr containers
./run.sh fs-e2e           # Filesystem-focused e2e tests
./run.sh dev-up           # Start dev stack with demo data (API, Vite UI, Radarr, Sonarr)
./run.sh dev-down         # Stop dev stack
./run.sh dev-reset        # Full reset: wipe all data + Arr state, rebuild from scratch
./run.sh dev-shell        # Shell into dev container
```

To run a single test file or specific test, use `LIBRARIARR_PYTEST_ARGS`:
```bash
LIBRARIARR_PYTEST_ARGS="tests/unit/sync/test_naming.py -v" ./run.sh test
LIBRARIARR_PYTEST_ARGS="tests/unit/sync/test_naming.py::test_specific -v" ./run.sh test
```

**After every code change** (no matter how small), run `./run.sh quality-autofix` then `./run.sh test` before responding. Do not skip this step.

## Code Style

- Python 3.12, Ruff with line-length 100, max McCabe complexity 12
- Lint rules: E, F, I (isort), UP (pyupgrade), B (bugbear), C90 (complexity)
- Frontend: React/TypeScript with Vite, ESLint

## Architecture

### Entry Point

`librariarr/main.py` — CLI with `--web` (FastAPI server + background sync), `--once` (single reconcile), `--web-no-runtime` (API only, no sync loop).

### Service Layer (mixin-based)

`librariarr/service/__init__.py` defines `LibrariArrService` composed of three mixins:
- `ServiceBootstrapMixin` (`bootstrap.py`) — initializes Radarr/Sonarr clients, sync helpers, projection orchestrators
- `ServicePreflightMixin` (`preflight.py`) — API error handling and config hints
- `ServiceReconcileMixin` (`reconcile.py`) — core reconcile loop: consume webhook queues → auto-add unmatched → projection → discovery

### Projection System (`librariarr/projection/`)

The core mechanism: reads Arr inventories, builds projection plans, executes hardlinks idempotently.
- `orchestrator.py` / `sonarr_orchestrator.py` — top-level reconcile coordinators per Arr service
- `planner.py` / `sonarr_planner.py` — build projection plans from Arr state
- `executor.py` — applies hardlinks, handles relink-on-replace
- `provenance.py` — SQLite state DB (`ProjectionStateStore`) for tracking hardlink provenance
- `webhook_queue.py` — global queues for scoped incremental reconciles

### Sync Helpers (`librariarr/sync/`)

- `radarr_helper.py` / `sonarr_helper.py` — cache Arr profiles, map quality rules, handle auto-add logic
- `discovery.py` — filesystem scanning for unmatched movie/series folders
- `naming.py` — canonical name parsing from folder names

### Clients (`librariarr/clients/`)

HTTP wrappers for Radarr (`radarr.py`) and Sonarr (`sonarr.py`) APIs.

### Config (`librariarr/config/`)

- `models.py` — dataclasses: `AppConfig`, `PathsConfig`, `RadarrConfig`, `SonarrConfig`, `RuntimeConfig`, `CleanupConfig`
- `loader.py` — YAML parsing with env var overrides (`LIBRARIARR_RADARR_URL`, etc.)

### Runtime (`librariarr/runtime/`)

- `loop.py` — `RuntimeSyncLoop` with watchdog filesystem monitoring, debounce, and maintenance scheduling
- `status.py` — phase tracking for the UI dashboard

### Web Layer (`librariarr/web/`)

FastAPI app with React frontend:
- `app.py` — app factory, `WebState` dataclass, config persistence
- `jobs.py` — `JobManager` async job queue with persistence
- `routers/` — API endpoints (hooks, config, diagnostics, dry-run, fs, jobs, runtime, logs, etc.)
- `hooks_router.py` — webhook ingestion from Radarr/Sonarr → queues scoped reconcile
- `runtime_task_wiring.py` — wires reconcile triggers to job manager

### Frontend (`ui/`)

React/TypeScript SPA built with Vite, served as static files in production.

### Reconcile Flow

1. Webhook or filesystem event triggers reconcile (or scheduled maintenance)
2. Consume webhook queues to scope affected movie/series IDs
3. Auto-add unmatched media discovered on filesystem
4. Run projection: fetch Arr inventory → plan → execute hardlinks
5. Run discovery for any remaining unmatched folders

## Test Structure

- `tests/unit/` — pure unit tests, no Docker/network deps
- `tests/service/` — service integration tests using test helpers (`tests/service/helpers.py`)
- `tests/e2e/` — live Arr integration tests (marker: `e2e`) and filesystem tests (marker: `fs_e2e`)

## Refactoring Guidance

- Extract cohesive modules by responsibility rather than just splitting long files
- Keep domain logic, I/O, mapping, and validation separated
- Preserve behavior and verify with `./run.sh test` and `./run.sh quality`

## Agent Team Workflow

For non-trivial feature requests, use the agent team in order:
1. **Analyst** — scope requirements, identify edge cases, structure the spec (for complex/ambiguous features)
2. **Architect** — design the technical solution, identify affected files, produce implementation plan
3. **Coder** — implement the plan (can be parallelized for independent modules)
4. **Reviewer** — run quality gate, review code, write missing tests
5. **E2E Tester** — write/run Playwright tests for user-facing features

For simple bug fixes or small changes, skip directly to implementation. Use judgment about when the full pipeline is needed.
