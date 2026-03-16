# LibrariArr Workflow and Reconcile Flows

This document describes how LibrariArr behaves in common lifecycle cases.
It focuses on the reconcile pipeline, link management, and Arr sync behavior.

## Terms

- **Nested root**: Real media storage location (source of truth for discovered folders).
- **Shadow root**: Virtual library root where LibrariArr creates symlinks for Arr.
- **Link**: Symlink in shadow root pointing to a discovered nested folder.
- **Full reconcile**: Scan all mapped roots.
- **Incremental reconcile**: Scan only affected scopes from filesystem events or scoped API path.

## Core Reconcile Pipeline

On every reconcile cycle, LibrariArr runs this sequence:

1. Ensure shadow roots exist.
2. Refresh Arr root-folder availability state.
3. Run ingest (if enabled).
4. Resolve scope:
   - Full reconcile when no affected paths are provided.
   - Incremental reconcile when affected paths are provided.
5. Collect existing shadow links.
6. Build Arr indices (title/year, path, external IDs) when sync is enabled.
7. For each discovered folder:
   - Match to Arr item (external IDs -> exact title/year -> existing link/path -> fuzzy).
   - Auto-add if enabled and still unmatched.
   - Ensure a link exists.
   - Update Arr item path to that link when matched.
8. Cleanup stale/orphan links.

## Trigger Sources

### Runtime loop

- Watches nested roots and shadow roots with debounce.
- Shadow-root events are considered for top-level entries and for nested changes under real top-level shadow directories.
- Runs:
  - **Initial reconcile** once on startup.
  - **Filesystem-triggered reconcile** (incremental).
  - **Scheduled maintenance reconcile** (full).
  - **Poll-triggered reconcile** when missing Arr roots become available.

### Manual API

- `POST /api/maintenance/reconcile`
  - No `path` query: full reconcile.
  - With absolute `path`: scoped/incremental reconcile for that path.

## Link Naming Rules (Current Behavior)

- Link names are derived from the **folder name** (canonicalized from folder), not Arr metadata title.
- Auto-add canonical paths follow the same folder-derived naming policy.
- Existing link reuse rules:
  - Reuse exact canonical link for the folder when valid.
  - Reuse collision-qualified variants (`<base>--...`) for the same folder.
  - Do **not** keep a stale wrong-named link just because it points to the same folder.

This prevents wrong-title persistence after NFO corrections.

## Scenario Flows

## 1) First Reconcile After Startup

Expected flow:

1. Preflight checks Arr connectivity and root configuration.
2. Runtime runs initial full reconcile.
3. All discoverable folders under nested roots are scanned.
4. Links are created or reused under corresponding shadow roots.
5. If Arr sync is enabled and items are matched, Arr paths are updated to link paths.
6. Orphans/stale links are cleaned depending on cleanup settings.

Result:

- Shadow library reflects current nested folders.
- Radarr/Sonarr paths converge to LibrariArr-managed link paths.

## 2) Movie/Series Added in Nested Directory (Filesystem First)

Example: a new folder appears under a nested root and contains media files.

Expected flow:

1. Watcher records create/move events and debounces.
2. Incremental reconcile scans only affected scope.
3. Folder is discovered as movie/series candidate.
4. Match attempt order:
   - External IDs from folder/NFO (`tmdb`, `imdb`, `tvdb` as applicable)
   - Exact title/year from folder name
   - Existing link/path based match
   - Fuzzy title/year fallback
5. If matched, Arr path is updated to folder-derived link path.
6. If unmatched and auto-add enabled, item is added in Arr and then synced to link path.
7. Orphan/stale links in affected scope are cleaned.

Result:

- New folder gets a shadow link.
- Arr path points to that link when sync match/add succeeds.

## 3) Movie/Series Added in Radarr/Sonarr First (No Filesystem Change)

If an item is created in Arr only (without new nested-folder filesystem events):

- No immediate event-triggered incremental reconcile is generated from nested roots.
- The item is considered on the next full/maintenance/manual reconcile.
- A link is created only if a discoverable nested folder exists.

If the Arr item path is created directly in the shadow root and ingest is enabled:

1. Shadow-root top-level create/move/delete event triggers reconcile.
2. Ingest may move that real folder to nested root (subject to stability/collision policy).
3. Source shadow folder becomes a symlink to nested destination.
4. Reconcile then syncs Arr path to the managed link.

## 4) Folder Rename in Nested Root

Expected flow:

1. Move/rename event contributes source and destination paths to affected set.
2. Incremental scope removes old discovered folder from known set and discovers new path.
3. Reconcile creates/keeps link for the new folder name.
4. Old link becomes stale and is removed during cleanup.
5. Matched Arr item path is updated to new link path.

Result:

- Arr path follows the renamed folder via updated link.

## 5) Folder Move Between Nested Roots (Same or Different Mapping)

Expected flow:

1. Event paths drive incremental scan roots.
2. Folder disappears from old scope and appears in new scope.
3. New link is created under destination mapping's shadow root.
4. Old link is removed as stale/orphan.
5. Arr item path updates to the new link if matched.

If multiple nested roots map to one shadow root and names collide, collision suffixes (`--...`) are used.

## 6) NFO Initially Wrong, Later Corrected

Example: folder is `EO (2022)` but NFO initially points to another movie ID.

Expected flow:

1. First run may match wrong Arr item via external ID from NFO.
2. Link name remains folder-derived (not metadata-derived).
3. After NFO fix, next reconcile matches the correct Arr item.
4. Arr path for correct item is updated to the same folder-derived link.
5. Any stale wrong-named link is not preserved as the canonical result and is cleaned as stale/orphan.

Result:

- Path converges to a folder-consistent link even if prior metadata was wrong.

## 7) Folder Deleted from Nested Root

Expected flow:

1. Incremental/full reconcile no longer discovers the folder.
2. Link targeting that missing folder is removed as orphan.
3. Missing-item action can be queued for Arr based on cleanup config:
   - `none`
   - `unmonitor`
   - `delete`
4. Action is applied after `missing_grace_seconds`.
5. Missing-item actions are evaluated in both full and incremental cleanup paths.

## 8) Arr Root Not Configured Yet

If a shadow root is missing in Radarr/Sonarr root folders:

- Matching/sync for that root is skipped.
- Existing links for that root are preserved (when present).
- Polling checks for root availability and triggers reconcile once available.

Result:

- Filesystem link management can continue without destructive sync behavior until root is available.

## Ingest Workflow (When `ingest.enabled=true`)

Ingest handles real directories dropped directly into shadow roots:

1. Candidate must be a non-hidden real directory (not symlink) containing media and no partial files.
2. Candidate must satisfy quiescence (`min_age_seconds`).
3. Folder is moved to the mapped nested root.
4. Original shadow location is replaced by symlink to moved destination.
5. Collision behavior:
   - `skip`: leave candidate in place.
   - `qualify`: move to suffixed destination (`[ingest-2]`, ...).
6. Failed ingest can be quarantined if configured.

## Practical Summary

- Nested folder structure is the naming authority for links.
- External IDs in NFO strongly influence matching, but no longer control link naming.
- Reconcile is idempotent: repeated runs converge paths/links to current filesystem truth.
- Auto-add is optional and only used when no safe match exists.
- Cleanup removes stale/orphan links and can enforce Arr missing-item policy after grace period.