# Runtime Workflows

Canonical scenario semantics live in
[reconciliation_scenarios.md](reconciliation_scenarios.md); architecture in
[architecture.md](architecture.md). This page summarizes when which pass runs.

## Triggers

| Trigger | Pass | Latency |
|---|---|---|
| Radarr/Sonarr Connect webhook (`POST /api/hooks/{radarr,sonarr}`) | consistency | `runtime.debounce_seconds` (default 8s) |
| Interval | consistency | every `runtime.consistency_interval_seconds` (default 300s) |
| Interval | full | every `runtime.full_interval_minutes` (default 60m) |
| Startup | `runtime.startup_scope` (default full) | immediate |
| API (`POST /api/reconcile`) | chosen scope | queued into the loop (or immediate with `dry_run`) |

There are no filesystem watchers. Arr-side changes arrive via webhooks within
seconds; user-side changes (manual folder drops, moves, renames) are picked up
by the next full pass. If an hourly full pass is too slow for your workflow,
lower `full_interval_minutes` or trigger a full pass from the UI/API after
making changes.

## Pass Contents

**Consistency** (cheap, no tree walk):
1. Fetch all movies/series (+episode files) from Arr.
2. Per item: verify library-file inode against the cached managed folder.
3. Ingest new imports/upgrades (hardlink into managed), relink user
   replacements, restore missing library files, sync per-item projections.

**Full** (one managed-tree walk):
1. Build the inode index across managed roots.
2. Everything the consistency pass does, plus resolving items without cache
   hints (user moves).
3. Discovery: report/auto-add/adopt unmatched managed folders.
4. Prune stale library/shadow folders (items removed from Arr).

## Deployment Notes

- Webhooks: point Radarr/Sonarr Connect at
  `http://librariarr:8787/api/hooks/radarr` / `.../sonarr`. Optional shared
  secret via `LIBRARIARR_WEBHOOK_SECRET` (header
  `X-Librariarr-Webhook-Secret`).
- `--once` runs a single full pass and prints the report as JSON;
  `--once --dry-run` prints the plan without touching anything.
- `--web` serves the UI/API and runs the loop; `--web-no-runtime` serves the
  API only.
