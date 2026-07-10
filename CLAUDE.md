# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

LibrariArr is a media library synchronization service. The user's nested, curated tree (managed root) is authoritative; Radarr/Sonarr work against flat roots (library/shadow roots) kept in sync via hardlinks. Identity is the **inode**: the managed file and the Arr-side file are the same inode, so renames/moves in the managed tree never break anything, Arr paths are never rewritten, and no provenance database exists.

## Development Commands

All operations go through `./run.sh <command>`. Never run `python`, `pip`, `pytest`, `npm`, `docker compose`, etc. directly.

```bash
./run.sh install          # Build dev Docker image
./run.sh test             # Unit tests (excludes e2e markers)
./run.sh quality          # Ruff lint/format + frontend ESLint checks
./run.sh quality-autofix  # Auto-fix then re-check
./run.sh fs-e2e           # Filesystem scenario e2e (fake Arr, real filesystem)
./run.sh e2e              # Live Radarr/Sonarr smoke tests
./run.sh dev-up           # Start dev stack (API, Vite UI, Radarr, Sonarr)
./run.sh dev-down         # Stop dev stack
./run.sh dev-shell        # Shell into dev container
```

To run a single test file or specific test, use `LIBRARIARR_PYTEST_ARGS`:
```bash
LIBRARIARR_PYTEST_ARGS="tests/unit/core/test_movies_reconcile.py -v" ./run.sh test
```

**After every code change** (no matter how small), run `./run.sh quality-autofix` then `./run.sh test` before responding. Do not skip this step.

## Code Style

- Python 3.12, Ruff with line-length 100, max McCabe complexity 12
- Lint rules: E, F, I (isort), UP (pyupgrade), B (bugbear), C90 (complexity)
- Frontend: React/TypeScript with Vite + Mantine, ESLint

## Architecture

### Core (`librariarr/core/`) — the whole product

- `engine.py` — `ReconcileEngine`: two scopes. `consistency` (no tree walk; per-item stat/inode verification, webhook-triggered) and `full` (one managed-tree walk building the `InodeIndex`, plus discovery/auto-add and stale prune).
- `movies.py` — `MovieReconciler`: per-movie decision tree (identity holds → project; library inode unknown + managed folder known → mtime tie-break between Arr upgrade (ingest) and user replacement (relink); no managed folder → ingest new import).
- `series.py` — `SeriesReconciler`: same model per episode file; supersession only within the same SxxEyy key; user-added episodes are projected + rescanned so Sonarr imports them.
- `discovery.py` — unmatched managed folders: adopt file-less Arr entries (exact title+year), conservative auto-add (single exact lookup match), otherwise report with reason. Name parsing happens only here, at first contact.
- `index.py` — `InodeIndex` (rebuilt per full pass) and `AdvisoryCache` (id → managed folder JSON; advisory only, always stat-verified).
- `fsops.py` — hardlink/trash/prune primitives, exclusion pattern matching. Ingest = hardlink (data never moves). Trash = `<managed_root>/.deletedByLibrariarr/`.
- `model.py` / `status.py` — `ReconcileReport`/`Action`/`UnmatchedFolder` and the thread-safe status snapshot.

### Shell around the core

- `service.py` — thin facade (config + engine + status), serializes reconciles.
- `runtime/loop.py` — interval scheduler + debounced webhook triggers. No filesystem watchers.
- `web/app.py` — slim FastAPI: `/api/status`, `/api/reconcile`, `/api/unmatched`, `/api/config` (raw YAML + validation), `/api/logs`, `/api/hooks/{radarr,sonarr}`, static UI.
- `clients/` — Radarr/Sonarr HTTP wrappers (retries, circuit breaker).
- `config/` — dataclasses (`models.py`) + YAML loader (`loader.py`); env overrides `LIBRARIARR_RADARR_URL` etc.
- `sync/naming.py` — `Title (Year)` parsing (first-contact only).
- `main.py` — CLI: `--web`, `--once` (+ `--dry-run`), `--web-no-runtime`.

### Frontend (`ui/`)

Small React/TypeScript SPA (Mantine): Status, Unmatched, Config (raw YAML), Logs.

### Safety invariants (do not violate)

- Managed files are never deleted; the only destructive path is upgrade supersession → quarantine (or `hard` delete if configured).
- Library/shadow roots are machine-only; cleanup only removes files whose inode is in the managed tree or with nlink > 1; sole-copy videos are warned and left.
- Arr paths/filenames are never rewritten; the Arr API is only used to read, add, and rescan.
- Everything idempotent; every mutating helper honors `dry_run`.

## Test Structure

- `tests/unit/core/` — engine/flow tests with fake Arr clients on tmp filesystems (the bulk of coverage)
- `tests/unit/` — runtime loop + web app tests
- `tests/e2e/filesystem/` — the scenario matrix as executable tests (marker: `fs_e2e`)
- `tests/e2e/{radarr,sonarr}/` — live Arr smoke tests (marker: `e2e`)

## Canonical Behavior Sources (Authoritative)

- `docs/reconciliation_scenarios.md` (canonical scenario matrix)
- `docs/architecture.md` (invariants and design)
- `docs/workflows.md` (runtime flow)

Required policy:

- Do not implement behavior based on ad-hoc assumptions if it conflicts with these docs.
- If the user explicitly requests behavior that differs from the canonical docs, update the docs in the same change.
- Keep other docs lightweight and link to canonical docs instead of duplicating semantics.

## Agent Team Workflow

For non-trivial feature requests, use the agent team in order:
1. **Analyst** — scope requirements, identify edge cases (for complex/ambiguous features)
2. **Architect** — design the technical solution, produce implementation plan
3. **Coder** — implement the plan
4. **Reviewer** — run quality gate, review code, write missing tests
5. **E2E Tester** — write/run tests for user-facing features

For simple bug fixes or small changes, skip directly to implementation.
