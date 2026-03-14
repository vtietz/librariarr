# Copilot Instructions for LibrariArr

Use the wrapper scripts for all development operations in this repository.

## Required workflow

- Linux/macOS: use `./run.sh <command>`
- Windows: use `run.bat <command>`
- Prefer wrapper commands for setup, build, run, logs, one-shot sync, dev mode, and tests.
- After bigger code changes, automatically run `test` and `quality` wrappers before finishing.
- When running `quality`, avoid redirecting output to custom files; prefer terminal output directly (or bounded output like `... | tail -n 200`) to avoid file-write approval prompts.
- Always provide a commit message proposal in final responses after code changes.
- Never create README files unless the user explicitly requests README changes.

## Do not run directly (unless user explicitly asks)

- `python ...`
- `pip ...`
- `pytest ...`
- `npm ...`
- `npx ...`
- `docker compose ...`
- `docker build ...`
- `docker run ...`

All frontend/package-manager operations must be routed through `./run.sh <command>` / `run.bat <command>`.
Direct `npm`/`npx` usage is forbidden in commands you run manually; usage inside wrapper scripts is allowed.

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
- `dev-bootstrap`
- `dev-seed`
- `dev-down`
- `dev-logs`
- `dev-shell`

If a needed operation is missing, update the wrapper script first, then use that wrapper command.
