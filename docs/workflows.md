# LibrariArr Workflow and Reconcile Flows

This document describes the **current** runtime behavior.

## Transition State (Current)

- **Movies (Radarr): projection-first, hooks-first**
  - Source: `paths.movie_root_mappings[].managed_root`
  - Target: `paths.movie_root_mappings[].library_root`
  - Projection mode: hardlink managed video + allowlisted extras
  - Trigger model: Radarr webhook queue + periodic/full reconcile
- **Series (Sonarr): projection-first, hooks-first**
  - Source: `paths.series_root_mappings[].nested_root`
  - Target: `paths.series_root_mappings[].shadow_root`
  - Projection mode: hardlink managed episode files + allowlisted extras
  - Trigger model: Sonarr webhook queue + periodic/full reconcile

Important: legacy Sonarr link matching/path-update/cleanup flows are removed from the
runtime reconcile path. Movie ingest is available as an optional reconciliation step via
`ingest.enabled`.

## Terms

- **Managed root**: Arr-owned source storage root.
- **Library root**: Curated target root populated by projection.
- **Projection**: Hardlinking managed files into library roots.
- **Full reconcile**: No affected-path scope; broad cycle.
- **Incremental reconcile**: Affected-path scope from filesystem/manual path trigger.

## Core Reconcile Pipeline

On each reconcile cycle, LibrariArr performs:

1. Refresh Arr root-folder availability state.
2. Consume scoped movie ids from the Radarr webhook queue (if any).
3. Consume scoped series ids from the Sonarr webhook queue (if any).
4. Run movie projection from Radarr movie inventory + movie root mappings.
5. Run series projection from Sonarr series inventory + series root mappings.
6. Publish reconcile metrics/status.

When `ingest.enabled=true`, a movie pre-step moves movie folders that currently resolve under
movie library roots back into their managed roots, updates Radarr movie paths, and scopes those
movie ids for projection.

## Trigger Sources

### Runtime loop

- Watches configured managed roots and library roots.
- Runs:
  - initial reconcile at startup,
  - filesystem-triggered reconcile (incremental),
  - scheduled maintenance reconcile (full),
  - poll-triggered reconcile when Arr roots become available.

### Webhook queues

- `POST /api/hooks/radarr` enqueues movie ids.
- `POST /api/hooks/sonarr` enqueues series ids.
- Queues are deduped/coalesced.
- Next reconcile consumes ids and scopes projection work.

### Manual API

- `POST /api/maintenance/reconcile`
  - without `path`: full reconcile,
  - with absolute `path`: incremental/scoped reconcile.

## Movie Projection Behavior

- Folder naming uses sanitized Radarr title/year naming.
- Managed files include:
  - video extensions from `radarr.projection.managed_video_extensions`,
  - extras from `radarr.projection.managed_extras_allowlist`.
- Unknown library files are preserved (`preserve_unknown_files=true`).
- Reconcile is idempotent and re-links replaced managed files.

## Series Projection Behavior

- Folder naming uses sanitized Sonarr title/year naming.
- Managed files include:
  - video extensions from `sonarr.projection.managed_video_extensions`,
  - extras from `sonarr.projection.managed_extras_allowlist`.
- Unknown library files are preserved (`preserve_unknown_files=true`).
- Reconcile is idempotent and re-links replaced managed files.

## Main Scenarios Covered by E2E

### Filesystem E2E

- projection creates expected hardlink layout,
- projection respects movie root mappings,
- projection scopes to webhook movie ids,
- projection runtime performs optional movie ingest moves when enabled.

### Radarr E2E

- managed-folder naming projection,
- optional Radarr title/year naming projection,
- webhook-scoped movie projection,
- relink when managed source file is replaced,
- preserve unknown files in library folders,
- runtime loop processing of queued webhook projection,
- multi-mapping and extras projection behavior.

### Sonarr E2E

- series projection into library roots,
- Sonarr title/year naming projection mode,
- webhook-scoped series projection,
- runtime loop projection for managed-root file creation,
- projection edge cases (unmapped managed roots, extras allowlist behavior).

## Practical Summary

- Both movie and series flows are projection-first.
- Legacy symlink and path-mutation orchestration is removed from active runtime behavior.
- Wrapper validations stay green when this projection-only architecture is preserved.
