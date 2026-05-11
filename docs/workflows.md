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
runtime reconcile path. Movie and series ingest are available as optional reconciliation steps via
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
4. Optionally ingest movies/series from library or shadow roots back into managed roots.
5. Run discovery/auto-add for unmatched managed folders.
6. Run movie projection from Radarr movie inventory + movie root mappings.
7. Run series projection from Sonarr series inventory + series root mappings.
8. Run conservative stale-shadow cleanup for provenance-managed stale outputs.
9. Publish reconcile metrics/status.

For detailed scenario-by-scenario outcomes (including manual/startup/full reconcile semantics),
use `docs/reconciliation_scenarios.md` as the canonical reference.

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
- Unknown library files are replaced by projection when destinations collide.
- Reconcile is idempotent and re-links replaced managed files.

## Series Projection Behavior

- Folder naming uses sanitized Sonarr title/year naming.
- Managed files include:
  - video extensions from `sonarr.projection.managed_video_extensions`,
  - extras from `sonarr.projection.managed_extras_allowlist`.
- Unknown library files are replaced by projection when destinations collide.
- Reconcile is idempotent and re-links replaced managed files.

## Scenario Coverage Reference

E2E scenario coverage is tracked in one place:

- `docs/reconciliation_scenarios.md`

## Practical Summary

- Both movie and series flows are projection-first.
- Legacy symlink and path-mutation orchestration is removed from active runtime behavior.
- Wrapper validations stay green when this projection-only architecture is preserved.

## Scenario Reference

For a scenario-by-scenario behavior matrix (including reconciliation definition,
legacy broken-link diagnostics, and filesystem e2e coverage), see
`docs/reconciliation_scenarios.md`.
