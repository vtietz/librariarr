# LibrariArr Architecture: Inode-Based Reconcile

Canonical architecture document.

## Premise

The user-curated nested tree (**managed root**) is authoritative. Radarr/Sonarr
work against flat roots (**library root** for movies, **shadow root** for
series) that LibrariArr keeps in sync via hardlinks.

A **bucket** is one configured `managed_root` <-> `library_root` pairing (one
entry in `movie_root_mappings`/`series_root_mappings`). Buckets typically
represent a content classification the user cares about — e.g. one bucket per
age rating (`age_06`/`age_12`/`age_16`) — and a config can have several. The
term appears throughout these docs and in the "bucket relocation"/"bucket
move" scenario below.

## The Three Invariants

1. **Identity by inode.** A movie's library file and its managed counterpart
   are the same inode (hardlink). Matching managed folders <-> Arr entries is
   pure inode comparison — no name parsing after first contact, no provenance
   database. A user rename/move in the managed tree does not change the inode,
   so identity survives it for free.
2. **Library/shadow roots are machine-only.** Users never place files there.
   Every file in a library root is classifiable with zero history:
   - inode exists in the managed tree → it is a projection (relink/prune freely),
   - inode is new → it is a fresh Arr import or upgrade → ingest it.
3. **Arr paths are never rewritten.** Whatever folder/file name Arr chose at
   import stays. Ingest is "hardlink the library file into the managed tree" —
   Arr never notices; no data is ever moved. LibrariArr writes to the Arr API
   only to add items and to trigger rescans.

## Components

```
librariarr/
  core/
    engine.py      ReconcileEngine: scopes, wiring, inode index construction
    movies.py      MovieReconciler: per-movie consistency/ingest/projection/prune
    series.py      SeriesReconciler: per-episode variant of the same model
    discovery.py   Unmatched-folder discovery, adopt, conservative auto-add
    index.py       InodeIndex (one walk) + AdvisoryCache (id -> managed folder)
    relocate.py    Bucket relocation: the one place a managed folder moves
    fsops.py       Hardlink/trash/prune primitives, exclusion matching
    model.py       Action / ReconcileReport / UnmatchedFolder
    status.py      Thread-safe status snapshot for the API
  runtime/loop.py  Interval scheduler + debounced webhook triggers
  service.py       Thin facade: config + engine + status
  web/app.py       Slim FastAPI: status, reconcile, unmatched, config, logs, hooks
  clients/         Radarr/Sonarr HTTP wrappers (retries, circuit breaker)
  config/          Dataclasses + YAML loader
```

## Three Reconcile Scopes

**Targeted pass** (`scope=targeted`) — the per-item flow for an explicit list
of Arr ids, fetched with `get_movies_by_ids`/`get_series_by_ids`. Identical
decisions to a consistency pass; only the iteration narrows, and an Arr with no
ids in the request is skipped entirely (a Radarr webhook never touches the
Sonarr library). Two things stay off, both because a partial item list cannot
support them: pruning ("delete what Arr no longer lists" would condemn every
folder outside the subset) and discovery. Runs on a webhook that names an item,
on a detected bucket drift, and from `POST /api/reconcile {"scope":
"targeted", "radarr_movie_ids": [...]}`.

**Consistency pass** (`scope=consistency`) — no tree walk. One bulk Arr API
call, then per item: stat the library file, stat the cached managed path,
compare inodes. Runs every `runtime.consistency_interval_seconds`, and on any
webhook that does not name an item. It is also the safety net that makes the
targeted path safe to rely on: anything a lost or unidentifiable webhook left
unreconciled is picked up here within one interval. Handles: new imports,
upgrades, user-replacements, missing-file restore.

**Full pass** (`scope=full`) — everything above, plus: builds the inode index
(the only managed-tree walk), resolves items with no cache hint (e.g. after a
user move), runs discovery/auto-add for unmatched folders, and prunes stale
library/shadow folders. Runs at startup (configurable) and every
`runtime.full_interval_minutes`.

### Bucket-Drift Poll

One Arr-side change reaches LibrariArr through no webhook at all: reassigning an
item's root folder. Radarr's `MoveMovieService` publishes `MovieMovedEvent`,
which only health checks consume — it is never routed to notification providers
— and the `OnMovieRename` notification fires for file renames, not folder moves.
So scenario 11 is **polled, not pushed**: every
`runtime.bucket_drift_interval_seconds`, `ReconcileEngine.list_bucket_drift`
compares each item's Arr path (mapped to a bucket) against the bucket its cached
managed folder sits in. That costs one Arr list call, in-memory comparisons and
one `is_dir` per cached item — no tree walk, nothing per file — and the drifted
ids then go through a targeted pass. Items with no cached folder are skipped
rather than searched for; the full pass owns whatever the poll cannot see.
Exposed read-only as `GET /api/bucket-drift` (the Status panel's "Pending bucket
moves" card).

The advisory cache (`librariarr-idcache.json` next to the config) maps Arr ids
to managed folders so consistency passes never need the walk. It is **advisory
only**: every entry is stat-verified before use; deleting the file costs one
full pass, nothing else. There is no other persistent state.

## Per-Movie Decision Tree

For each Radarr movie with a file (`movieFile.path` = the library file):

1. **Library file missing on disk** → restore by hardlinking the managed
   primary video to the library path (+rescan); if no managed source is known,
   warn and rescan so Radarr flags it file-less (self-heals via adopt on a
   later full pass).
2. **Library inode found in managed tree** (cache hint or index) → identity
   holds. First, **bucket reconciliation** (see below), then: sync projection,
   hardlink managed extras/additional videos into the library folder, remove
   stale projections.
3. **Library inode unknown, managed folder known** → bucket reconciliation runs
   here too, *before* the inode question is resolved, so an ingest lands in the
   bucket Arr now says the item belongs to rather than duplicating into the old
   one. Then two possible truths,
   resolved by mtime (the newer side is the intended change — so a manual
   replacement must carry a fresh mtime; copies that preserve old timestamps
   read as the losing side):
   - library file newer → **Radarr upgrade**: hardlink it into the managed
     folder; other managed videos of that movie are superseded → trash
     (`.deletedByLibrariarr`) or delete per `ingest.replacement_delete_mode`.
   - managed video newer → **user replacement wins**: relink the library path
     to the managed inode, trigger a rescan.
4. **Library inode unknown, no managed folder** → **new import**: hardlink the
   library folder's videos + allowlisted extras into
   `<managed_root>/<Arr folder name>/`. The user can sort it deeper into the
   hierarchy at any time — identity survives the move.

### Bucket Reconciliation

If an item's current Arr root folder maps to a *different*
`movie_root_mappings`/`series_root_mappings` entry than the one its managed
folder is physically under (e.g. the user moved it to another root folder in
Arr's UI), the managed folder is relocated — a real same-filesystem rename, so
the inode and therefore the Arr-side hardlink survive — to the corresponding
location under the new bucket's `managed_root`, preserving the user's own
subfolder structure and naming verbatim. This treats an Arr-side root-folder
change as a deliberate reclassification signal, same as moving the folder in the
managed tree directly would be.

The rules live in `core/relocate.py` so that full, consistency and targeted
passes move a folder on identical terms — divergent rules per trigger would mean
one pass refusing what the next performs. It refuses, warning and touching
nothing, when: the destination already exists (`destination_exists` — no merge,
no overwrite), more than one Arr item claims the same managed folder
(`ambiguous_owner` — a folder with two owners cannot be reclassified for one of
them without silently reclassifying the other), or the two buckets turn out to
be on different filesystems (`cross_filesystem`, the per-move backstop behind
the startup check). The unit that moves is the managed *folder*, not the video's
parent directory, so multi-disc and subfolder layouts move whole.

Series work the same way per **episode file**, with two additions: superseding
only applies to files with the same SxxEyy key, and managed videos unknown to
Sonarr (user-added episodes) are projected into the shadow folder and a rescan
is triggered so Sonarr imports them.

## Discovery and Auto-Add

A managed folder none of whose video inodes are known to Arr is **unmatched**.
Name parsing happens only here, at first contact:

- exact title+year match against a **file-less Arr entry** → adopt: project
  into the Arr folder + rescan (this is also the manual resolution path — the
  user adds the title in the Arr UI, nothing else),
- exact title+year match against an Arr entry **with a file** (movies): never
  auto-add (it can only fail). If the entry is already synced from another
  managed folder → reported as `duplicate`; if its Arr path is outside this
  bucket's library root → reported as `already_in_arr` with guidance; if it
  lives in this bucket's library root → adopt (cache association only; the
  reconciler resolves the files on the next pass via the upgrade/replacement
  tie-break),
- confident lookup match (single exact title+year) and auto-add enabled →
  add via API, project, rescan — unless the looked-up tmdb/tvdb id already
  exists in Arr (`already_in_arr`; retrying the add would 400 forever),
- otherwise → reported in the unmatched list with a reason
  (`no_match` / `ambiguous` / `lookup_failed` / `unparseable` /
  `auto_add_disabled` / `add_failed` / `duplicate` / `already_in_arr`).

Movie candidates are directories that directly contain video files. Series
candidates are the highest directories whose video files are all unknown,
refined downwards past grouping levels until a folder with direct videos or
season-like subfolders is found.

## Safety Model

- Managed files are **never deleted**. The only destructive operation on
  managed data is upgrade supersession, which defaults to a quarantine move to
  `<managed_root>/.deletedByLibrariarr/`. Every such removal goes through
  `core/supersede.py`, including the case that is easy to miss: an import whose
  *filename matches* the managed file it replaces. Ordinary supersession works
  by name — keep the ingested names, quarantine the rest — so a same-named
  upgrade is invisible to it and would be overwritten in place by the hardlink
  itself (`ensure_hardlink` unlinks its target first), destroying a sole-copy
  managed file outright. Such a target is therefore superseded *before* the
  link is made, by the same rules. This applies to allowlisted extras too: an
  import still wins over the managed copy, but the replaced copy — possibly the
  user's own subtitle — stays recoverable instead of vanishing.
- Bucket relocation (moving a managed folder to follow an Arr-side root-folder
  change) is non-destructive — same inode, same data, only the location
  changes — and refuses rather than overwrites when the destination already has
  content.
- Library/shadow cleanup only removes files provably safe to remove: inode
  present in the managed tree, or nlink > 1. A stale library folder containing
  a sole-copy video is left in place with a warning.
- Every operation is idempotent; a crashed run is simply re-run. Dry-run mode
  (`--once --dry-run` or `POST /api/reconcile {"dry_run": true}`) reports the
  full plan without touching anything.

## Requirements

- All roots (managed + library/shadow) must be on **one filesystem**
  (hardlinks), shared with the Arr containers under identical mount paths.
  This is enforced, not just documented: the engine checks every configured
  root's device id at startup and refuses to start if any two differ
  (`RootFilesystemMismatch`, `core/fsops.py:check_single_filesystem`). A
  cross-device "move" silently becomes a copy, which would otherwise let a
  manual reorganization recreate a duplicate instead of relocating anything —
  failing loudly at startup is cheaper than discovering that later. Roots
  that don't exist yet (first run, before volumes are populated) are skipped
  rather than treated as an error.
- Library/shadow roots must not be written to by users (machine-only).

## Naming Is Cosmetic, Not Synced

Renaming/reorganizing inside the managed tree never breaks anything (same
inode), but it also never changes what Radarr/Sonarr *display* — invariant #3
means Arr's path is fixed at import time and LibrariArr never writes back to
it. This is deliberate: the project's original design tried to keep paths
synced in both directions, and that two-way reconciliation was the main
source of fragility this architecture was built to escape. The resulting
mismatch is cosmetic, not a bug, so instead of touching Arr's tracked files
the web UI's Status panel surfaces it directly — a "Naming differences" table
listing, for any item where Arr's folder name and the managed folder name
have diverged, both paths side by side (backed by `GET /api/path-differences`,
which reads the advisory cache only — no tree walk).
