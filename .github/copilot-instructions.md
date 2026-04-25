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

## Refactoring guidance

- When code becomes too long or hard to follow, prefer extracting cohesive modules/functions by responsibility instead of only splitting lines.
- Apply clean-code boundaries: one reason to change per module, clear naming, and thin orchestration layers.
- Keep domain logic, I/O, mapping, and validation concerns separated where practical.
- Avoid cosmetic slicing that preserves complexity; refactor toward simpler control flow and clearer ownership.
- Preserve behavior while refactoring and verify with `./run.sh test` and `./run.sh quality` when changes are substantial.

## Agent-team default policy

- Default to the agent-team workflow for all non-trivial work: **Analyst -> Architect -> Coder -> Reviewer -> Tester**.
- Treat bug investigations, production/runtime diagnostics, multi-file changes, behavior changes, and ambiguous requests as non-trivial.
- Only skip the full agent-team flow for clearly small changes (for example: tiny copy/text edits, single-file cosmetic adjustments, or narrowly scoped one-function fixes with obvious impact).
- If a task starts small but reveals broader impact, switch to agent-team workflow immediately.
- In final responses, summarize which agent stages were used (or explicitly state why a small change skipped them).

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
