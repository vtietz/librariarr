# Agent Instructions for LibrariArr

Use the wrapper scripts for all development operations in this repository.

## Required workflow

- Linux/macOS: use `./run.sh <command>`
- Windows: use `run.bat <command>`
- Prefer wrapper commands for setup, build, run, logs, one-shot sync, tests, quality checks, and dev mode.
- **After every code change** (no matter how small), run `./run.sh quality-autofix` then `./run.sh test` before responding. Do not skip this step.
- When running `quality`, avoid redirecting output to custom files; prefer terminal output directly (or bounded output like `... | tail -n 200`) to avoid file-write approval prompts.
- Always provide a commit message proposal in final responses after code changes.
- Never create README files unless the user explicitly requests README changes.

## Refactoring guidance

- When code becomes too long or hard to follow, prefer extracting cohesive modules/functions by responsibility instead of only splitting lines.
- Apply clean-code boundaries: one reason to change per module, clear naming, and thin orchestration layers.
- Keep domain logic, I/O, mapping, and validation concerns separated where practical.
- Avoid cosmetic slicing that preserves complexity; refactor toward simpler control flow and clearer ownership.
- Preserve behavior while refactoring and verify with `./run.sh test` and `./run.sh quality` when changes are substantial.

## Canonical behavior sources (authoritative)

Always treat these documents as the single source of truth for runtime behavior and scenarios:

- `docs/reconciliation_scenarios.md` (canonical scenario matrix and expected outcomes)
- `docs/workflows.md` (runtime/reconcile flow overview)
- `docs/radarr_projection_implementation_spec.md` (architecture and invariants)

Required policy:

- Do not implement behavior based on ad-hoc assumptions, memory, or inferred intent if it conflicts with these docs.
- If behavior is unclear, first align with the canonical docs and then implement.
- If the user explicitly requests behavior that differs from the canonical docs, update the relevant canonical docs in the same change before or alongside code changes.
- Keep other docs lightweight and link to canonical docs instead of duplicating scenario semantics.

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
- `dev-reset`
- `dev-down`
- `dev-logs`
- `dev-shell`

If a needed operation is missing, update the wrapper script first, then use that wrapper command.
