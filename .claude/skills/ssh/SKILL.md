---
name: ssh
description: SSH into a remote host for diagnostics, log inspection, or maintenance — then optionally translate findings into local code fixes. Use when the user asks to investigate production issues, check server state, or debug remote environments. Trigger phrases: "ssh into", "check the server", "look at production logs", "diagnose on host".
argument-hint: "[user@host] [task description]"
context: fork
allowed-tools: Bash(ssh *) Bash(echo *) Read Glob Grep Edit Write
---

SSH into `$ARGUMENTS` and follow the two-phase playbook below.

## Core Operating Model

- Maintain two explicit shell contexts whenever possible:
	- `LOCAL` shell: project workspace commands (tests, edits, git, wrappers).
	- `REMOTE` shell: SSH host diagnostics and host-side actions.
- Project wrapper CLI commands (`./run.sh ...`) are `LOCAL`-only.
	- Do not run project test/quality/e2e commands on the remote host (especially DiskStation).
	- If a remote incident needs a code fix, apply the fix locally, then run validation locally.
- Reuse the same `REMOTE` terminal once authenticated; do not create multiple parallel SSH shells unless the user asks.
- Never run `ssh ...` from inside an already remote prompt unless the user explicitly requests host hopping.
- Never attempt to read remote command results from local temporary files or editor artifact paths.
	- Read output from the live terminal stream only.
- Prefer short, single-purpose commands over long chained one-liners.
	- Run one command, read output, interpret, then run the next command.

## Terminal Discovery (VS Code)

Before opening a new SSH connection, always locate and reuse an existing terminal when possible.

1. **Probe existing terminals first**
	- Query likely terminal IDs (for example: `1..12`) and keep IDs that return output.
	- Treat "No terminal found" as closed/inactive; do not fail the workflow.
2. **Identify the SSH terminal**
	- Prefer terminals whose prompt/output indicates a remote shell (for example `user@host`, `root@diskstation`, remote paths like `/volume1/...`).
	- If output is mostly logs, send a harmless command (`pwd` or `whoami && hostname`) to confirm the active shell context.
3. **Reuse, do not multiply terminals**
	- Send commands to the confirmed terminal instead of launching fresh sessions repeatedly.
	- Only start a new `ssh user@host` session when no active terminal can be confirmed.
 	- Keep one `LOCAL` and one `REMOTE` terminal identity in your notes and switch intentionally.
4. **Handle interactive prompts correctly**
	- If a password/passphrase prompt appears, stop sending other commands and wait for user input.
	- Do not flood input; send one response per prompt and wait for the next prompt/output.
	- After authentication, immediately run `whoami && hostname && pwd` as proof of context.
5. **Recover from noisy log streams**
	- If attached logs hide prompts, send `echo READY` first; then run the next command once prompt responsiveness is confirmed.

## Phase 1 — Remote Diagnostics

1. **Open the session** — run `ssh user@host` from the `LOCAL` shell only. Tell the user to authenticate if needed, then continue.
2. **Confirm the session** — run `whoami && hostname && pwd` and report which machine is active.
3. **Investigate step-by-step** — one command at a time; read output before deciding the next step.
4. **Capture the root cause** — note the exact error, file path, log line, or state that explains the bug.
5. **Close the session** — run `exit` when diagnostics are complete and return focus to the `LOCAL` shell.

## Phase 2 — Code Fix (when applicable)

After confirming the root cause with the user:

1. **Locate the relevant code** — search the local workspace for the module/function the diagnostic implicated.
2. **Read the code** before editing — never modify code you haven't read.
3. **Apply a minimal, targeted fix** — change only what the diagnostic justifies.
4. **Verify** — run `./run.sh test` and `./run.sh quality` after changes.
	- This verification is local-only; never execute these project wrapper commands on DiskStation.
5. **Summarise** — explain what was wrong and what was changed, referencing the specific log line or error.

## Interactive Prompt Discipline

- Treat prompts as blocking states:
	- `password:`
	- `passphrase:`
	- host key confirmation (`Are you sure you want to continue connecting`)
	- `sudo` password prompt
- While blocked on a prompt:
	- Do not issue unrelated commands.
	- Wait for user entry (or ask concise questions when required by the tool flow).
	- Resume only after the shell prompt returns.

## Constraints

- DO NOT run destructive commands (`rm -rf`, `reboot`, `dd`, `mkfs`, etc.) without explicit user confirmation.
- DO NOT store or repeat passwords, API keys, or other secrets.
- DO NOT assume the SSH session is still alive between messages — verify with `echo ok` if unsure.
- ONLY interact with the host the user specified; do not hop to other machines without asking.
- DO NOT make sweeping refactors; scope code changes to exactly what the diagnostic revealed.
- DO NOT run nested SSH from a remote shell unless explicitly requested.
- DO NOT use local editor artifact paths as a substitute for remote terminal output.
- DO NOT run project wrapper test/quality commands on remote hosts (for example DiskStation);
	use the local workspace wrapper flow for validation.

## Output Format

**During diagnostics:** For each command show the command, trimmed output, and a one-sentence interpretation.

**After diagnostics:** Short bullet summary — what was found, what the root cause is, proposed fix.

**After code fix:** State the file(s) changed, what was changed, and why.
