---
name: ssh
description: SSH into a remote host for diagnostics, log inspection, or maintenance — then optionally translate findings into local code fixes. Use when the user asks to investigate production issues, check server state, or debug remote environments. Trigger phrases: "ssh into", "check the server", "look at production logs", "diagnose on host".
argument-hint: "[user@host] [task description]"
context: fork
allowed-tools: Bash(ssh *) Bash(echo *) Read Glob Grep Edit Write
---

SSH into `$ARGUMENTS` and follow the two-phase playbook below.

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
4. **Handle interactive prompts correctly**
	- If a password/passphrase prompt appears, ask the user for the value through the proper question flow and continue in the same terminal.
	- After authentication, immediately run `whoami && hostname && pwd` as proof of context.
5. **Recover from noisy log streams**
	- If attached logs hide prompts, send `echo READY` first; then run the next command once prompt responsiveness is confirmed.

## Phase 1 — Remote Diagnostics

1. **Open the session** — run `ssh user@host`. Tell the user to authenticate if needed, then continue.
2. **Confirm the session** — run `whoami && hostname && pwd` and report which machine is active.
3. **Investigate step-by-step** — one command at a time; read output before deciding the next step.
4. **Capture the root cause** — note the exact error, file path, log line, or state that explains the bug.
5. **Close the session** — run `exit` when diagnostics are complete.

## Phase 2 — Code Fix (when applicable)

After confirming the root cause with the user:

1. **Locate the relevant code** — search the local workspace for the module/function the diagnostic implicated.
2. **Read the code** before editing — never modify code you haven't read.
3. **Apply a minimal, targeted fix** — change only what the diagnostic justifies.
4. **Verify** — run `./run.sh test` and `./run.sh quality` after changes.
5. **Summarise** — explain what was wrong and what was changed, referencing the specific log line or error.

## Constraints

- DO NOT run destructive commands (`rm -rf`, `reboot`, `dd`, `mkfs`, etc.) without explicit user confirmation.
- DO NOT store or repeat passwords, API keys, or other secrets.
- DO NOT assume the SSH session is still alive between messages — verify with `echo ok` if unsure.
- ONLY interact with the host the user specified; do not hop to other machines without asking.
- DO NOT make sweeping refactors; scope code changes to exactly what the diagnostic revealed.

## Output Format

**During diagnostics:** For each command show the command, trimmed output, and a one-sentence interpretation.

**After diagnostics:** Short bullet summary — what was found, what the root cause is, proposed fix.

**After code fix:** State the file(s) changed, what was changed, and why.
