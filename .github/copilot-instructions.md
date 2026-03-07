# Copilot Instructions for LibrariArr

Use the wrapper scripts for all development operations in this repository.

## Required workflow

- Linux/macOS: use `./run.sh <command>`
- Windows: use `run.bat <command>`
- Prefer wrapper commands for setup, build, run, logs, one-shot sync, dev mode, and tests.
- After bigger code changes, automatically run `test` and `quality` wrappers before finishing.
- Always provide a commit message proposal in final responses after code changes.
- Never create README files unless the user explicitly requests README changes.

## Do not run directly (unless user explicitly asks)

- `python ...`
- `pip ...`
- `pytest ...`
- `docker compose ...`
- `docker build ...`
- `docker run ...`

## Approved commands

- `setup`
- `install`
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
