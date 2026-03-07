# Agent Instructions for LibrariArr

Use the wrapper scripts for all development operations in this repository.

## Required workflow

- Linux/macOS: use `./run.sh <command>`
- Windows: use `run.bat <command>`
- Prefer wrapper commands for setup, build, run, logs, one-shot sync, tests, quality checks, and dev mode.

## Do not run directly (unless user explicitly asks)

- `python ...`
- `pip ...`
- `pytest ...`
- `docker compose ...`
- `docker build ...`
- `docker run ...`

## Approved commands

- `setup`
- `build`
- `up`
- `down`
- `restart`
- `logs`
- `once`
- `test`
- `quality`
- `quality-autofix`
- `dev-up`
- `dev-down`
- `dev-logs`
- `dev-shell`

If a needed operation is missing, update the wrapper script first, then use that wrapper command.
