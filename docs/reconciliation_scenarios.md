# Reconciliation Scenarios and Coverage

Status: canonical scenario matrix.
Architecture background: [architecture.md](architecture.md).

## What Reconciliation Means

One reconcile pass makes Arr state, the managed tree, and the library/shadow
projections consistent. Two scopes exist:

- **consistency** — per-Arr-item stat/inode verification, no tree walk.
  Triggered by webhooks (debounced) and a short interval.
- **full** — consistency + one managed-tree walk (inode index) + discovery/
  auto-add + stale-projection prune. Triggered at startup and a long interval.

Both scopes converge to the same target state; the scope only affects how much
work is done to find drift.

## Scenario Matrix

Test coverage, three layers:

- **Unit** (`tests/unit/core/`): every scenario for both Radarr and Sonarr
  against the engine directly (fake Arr clients, tmp filesystems).
- **Filesystem e2e** (`tests/e2e/filesystem/`, marker `fs_e2e`): the closest
  practical approximation of production. `test_scenarios.py` covers every
  scenario row with Radarr *and* Sonarr variants (test names carry the
  scenario number); `test_runtime_stack.py` runs the deployed wiring —
  service + runtime loop thread + webhook/API-style triggers + status
  tracking — over a real filesystem, including concurrent-trigger
  serialization and startup reconcile.
- **Live smoke** (`tests/e2e/{radarr,sonarr}/`, marker `e2e`): real Radarr and
  Sonarr containers; covers the flows that need a real Arr API to be
  meaningful (first-contact adopt/auto-add with real metadata lookup,
  projection, idempotency, prune). Upgrade/replacement flows are not
  exercised live because they require a real download/import cycle; they are
  fully covered by the two layers above.

| # | Scenario | Mechanism | Expected result |
|---|---|---|---|
| 1 | New Arr import | Webhook → consistency pass. Library inode unknown, no managed folder for the item → ingest | Library folder content hardlinked into `<managed_root>/<Arr folder name>/`; Arr's files untouched; cache learns the mapping |
| 2 | Quality/file upgrade | Library inode unknown, managed folder known, library file newer → ingest file | New inode hardlinked into managed folder; superseded managed videos (movies: all others; series: same SxxEyy only) quarantined to `.deletedByLibrariarr` (or deleted, per `ingest.replacement_delete_mode`) |
| 3 | User rename/move in managed tree | Inode unchanged → identity survives; full pass re-derives folder via index | No filesystem actions; cache updated; Arr never touched |
| 4 | Manual add in managed root | Full pass discovery: video inodes unknown to Arr | Exact single lookup match + auto-add enabled → added + projected + rescan. Ambiguous/no match → unmatched report. Manual resolution: add the title in the Arr UI → adopted next full pass |
| 5 | Arr entry without file (file-less) | Discovery adopt: exact title+year folder match | Managed folder projected into the Arr folder, rescan triggered, identity established by inode from then on |
| 6 | Extras and unknown files | Projection allowlist | Videos + allowlisted extras projected; unknown files stay managed-side only; non-video unknown files in library folders are left alone |
| 7 | Missing sources | Library file missing on disk → restore from managed; nothing known anywhere → warn + rescan | No invalid projections; self-heals via scenario 5 once Arr marks the item file-less |
| 8 | Idempotency / duplicate prevention | Inode comparison everywhere | Re-running any pass produces zero actions; projections are never re-ingested (their inodes are in the managed tree) |
| 9 | Stale library/shadow folders (item removed from Arr) | Full pass prune | Folder removed when its contents are provably projections (inode in managed tree or nlink > 1); sole-copy videos are never deleted (warn + leave); managed data always survives |
| 10 | User replaces a file in the managed tree | Library inode unknown, managed folder known, managed file newer → relink | Library path relinked to the managed inode; Arr rescan triggered; nothing quarantined |

## Conflict Tie-Break (Scenarios 2 vs 10)

When the library file's inode is unknown to the managed tree but a managed
folder is known for the item, either Radarr wrote a new file (upgrade) or the
user replaced the managed file. These are structurally identical; the **newer
mtime wins** (the newer side is the intended change). Both directions are unit
tested; the decision is logged as a warning when the user side wins.

## Related Docs

- Architecture: [architecture.md](architecture.md)
- Runtime flow: [workflows.md](workflows.md)
- Configuration reference: [configuration.md](configuration.md)
